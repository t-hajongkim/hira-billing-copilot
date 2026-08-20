"""청구 현황 대시보드를 파일 하나로 굽는다.

무엇을 보여 주나
  화면의 주인공은 검색창이다 — 환자 ID 를 넣으면 워크플로가 돌고 결과가 그 자리에 온다.
  아래로 내려두는 것은 참고용 데이터다: llm.claim 뷰의 청구 건을 rules/HIRA_RULES.md 와
  대조해, 어떤 규정이 걸리는지 · 진료일이 시행일 이후인지 · 금액이 맞는지.

왜 AI 가 아니라 여기서 계산하나
  이 판정들은 전부 결정적이다 — 날짜 비교와 산술이다. 지어낼 여지가 없어야 하고,
  같은 입력이면 늘 같은 화면이 나와야 한다. AI 의 판단은 내려받는 보고서에 있고,
  이 화면은 그 판단을 검증할 수 있는 바닥 사실을 보여 준다.

이 도구는 러너에서 돈다 — build-dashboard 워크플로가 DB 를 service 로 띄우고 호출한다.
로컬에서 돌릴 일을 상정하지 않는다. 전 과정이 GitHub 안에서 재현되어야 한다.

  python tools/build_dashboard.py --check     # DB 없이 빌드 로직만 점검
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "rules/HIRA_RULES.md"
TEMPLATE = ROOT / "site/dashboard.template.html"
OUT = ROOT / "site/index.html"

# 화면이 쓰는 열만 읽는다. patient_id 는 애초에 읽을 수 없다 —
# llm_reader 에게 그 열만 권한이 없어서, SELECT * 를 쓰면 권한 오류가 난다.
COLUMNS = [
    "treatment_date", "visit_type", "department_name",
    "primary_diagnosis_code", "order_type", "hira_fee_code", "order_name",
    "coverage_type", "copayment_rate", "unit_price_krw", "total_charge_krw",
    "patient_charge_krw", "insurer_charge_krw", "claim_status", "age", "sex",
    "insurance_type", "copayment_type", "special_case_type",
]

CODE_RE = re.compile(r"\b[A-Z]{1,2}\d{3,7}\b")


def patient_range(dsn: str) -> dict:
    """화면에 넣을 환자 ID 범위. 진료 내용과 잇지 않는다 — 몇 번부터 몇 번까지 있는지만.

    검색창에 무엇을 넣어야 할지 알려 주려고 읽는다. 이 질의만 앱 자격증명을 쓴다.
    실패해도 화면은 그대로 나온다 — 안내 한 줄이 빠질 뿐이다.
    """
    sql = "SELECT min(patient_id), max(patient_id), count(*) FROM public.patient_master"
    out = subprocess.run(["psql", dsn, "-X", "-qAt", "-F", "|", "-v", "ON_ERROR_STOP=1", "-c", sql],
                         capture_output=True, text=True, encoding="utf-8", check=False)
    if out.returncode != 0 or not out.stdout.strip():
        print("환자 ID 범위를 읽지 못했습니다 - 안내 없이 굽습니다.")
        return {}
    first, last, n = out.stdout.strip().split("|")
    return {"first": first, "last": last, "count": int(n)}


def query(dsn: str) -> list[dict]:
    sql = f"SELECT {', '.join(COLUMNS)} FROM llm.claim ORDER BY treatment_date, hira_fee_code"
    out = subprocess.run(
        ["psql", dsn, "-X", "-qAt", "-F", "\x1f", "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True, text=True, encoding="utf-8", check=False)
    if out.returncode != 0:
        sys.exit(f"DB 조회 실패:\n{out.stderr.strip()[:400]}")
    rows = []
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        rows.append(dict(zip(COLUMNS, line.split("\x1f"))))
    return rows


def parse_rules(text: str) -> list[dict]:
    """규정 문서에서 판정에 쓸 것만 뽑는다 — 대상 코드, 시행일, 변경 유형."""
    rules = []
    for block in re.split(r"\n(?=## )", text):
        if "규정 ID:" not in block:
            continue
        title = block.split("\n", 1)[0].lstrip("# ").strip()

        def field(name: str) -> str:
            m = re.search(rf"- {name}:\s*(.+)", block)
            return m.group(1).strip().strip("`") if m else ""

        target = field("대상")
        codes = sorted(set(CODE_RE.findall(target)))
        eff = re.search(r"(20\d{2}-\d{2}-\d{2})", field("시행일") or "")
        rules.append({
            "id": field("규정 ID"),
            "title": title,
            "effective": eff.group(1) if eff else "",
            "effective_raw": field("시행일"),
            "kind": field("변경 유형"),
            "published": field("공고일"),
            "basis": field("근거 고시"),
            "target": target,
            "codes": codes,
            "note": (re.search(r"### 판단 시 주의\n(.+?)(?=\n##|\Z)", block, re.S).group(1).strip()
                     if "### 판단 시 주의" in block else ""),
            "changed": (re.search(r"### 무엇이 달라졌나\n(.+?)(?=\n###|\n##|\Z)", block, re.S).group(1).strip()
                        if "### 무엇이 달라졌나" in block else ""),
        })
    return rules


def judge(claim: dict, rules: list[dict]) -> dict:
    """건 하나를 판정한다. 전부 날짜 비교와 산술이라 결정적이다.

    판정은 이 건에 문제가 있느냐만 말한다. 규정이 몇 건 걸렸는지는 판정이 아니다 —
    시행일 전이라 적용도 안 되는 규정이 걸렸다고 '적용 규정 있음' 이라 적으면
    읽는 사람이 그 건을 정상으로 읽는다. 그건 틀린 말이었다.
    """
    code = claim["hira_fee_code"]
    tdate = claim["treatment_date"]
    hits, flags = [], []

    for r in rules:
        if code not in r["codes"]:
            continue
        applies = bool(r["effective"]) and tdate >= r["effective"]
        hits.append({**{k: r[k] for k in
                        ("id", "title", "effective", "effective_raw", "kind", "basis", "note", "changed")},
                     "applies": applies})
        if applies and "삭제" in r["kind"]:
            flags.append({
                "level": "danger",
                "text": f"{r['effective']} 자로 삭제된 코드입니다. 이 진료일({tdate})에는 청구할 수 없습니다.",
            })
        elif not applies and r["effective"] and "신설" in r["kind"]:
            # 시행일 전에는 그 코드가 없었다. 없는 코드로는 급여를 청구할 수 없다.
            flags.append({
                "level": "danger",
                "text": f"이 코드는 {r['effective']} 신설입니다. 진료일({tdate})이 시행일보다 앞서 "
                        f"이 진료분에는 청구할 수 없습니다.",
            })

    # 금액 검산 — 고치지 않고 어긋난 사실만 보고한다.
    try:
        total = int(claim["total_charge_krw"])
        pat = int(claim["patient_charge_krw"])
        ins = int(claim["insurer_charge_krw"])
        rate = float(claim["copayment_rate"])
        expect = round(total * rate)
        if abs(expect - pat) > 1:
            flags.append({"level": "warn",
                          "text": f"본인부담금이 계산과 다릅니다 — {total:,}×{rate:.0%}={expect:,}원, 청구 {pat:,}원"})
        if total != pat + ins:
            flags.append({"level": "warn",
                          "text": f"총액이 본인+공단과 맞지 않습니다 — {pat:,}+{ins:,}={pat + ins:,}, 총액 {total:,}"})
    except (ValueError, KeyError, TypeError):
        flags.append({"level": "warn", "text": "금액을 검산할 수 없습니다."})

    if claim["claim_status"] in ("ADJUSTED", "REJECTED"):
        flags.append({"level": "warn", "text": f"이미 {claim['claim_status']} 된 건입니다."})

    if any(f["level"] == "danger" for f in flags):
        verdict = "불인정"
    elif flags:
        verdict = "확인 필요"
    else:
        verdict = "이상 없음"

    return {
        "verdict": verdict,
        "rules": hits,
        "flags": flags,
        # 규정을 찾았는지는 판정과 따로 적는다. 규정이 없는 것과 규정을 못 찾은 것은 다르다.
        "applied": sum(1 for h in hits if h["applies"]),
        "matched": len(hits),
    }


def build(claims: list[dict], rules: list[dict], patients: dict) -> dict:
    days: dict[str, list] = {}
    for c in claims:
        c["judgement"] = judge(c, rules)
        days.setdefault(c["treatment_date"], []).append(c)

    counts: dict[str, int] = {}
    for c in claims:
        v = c["judgement"]["verdict"]
        counts[v] = counts.get(v, 0) + 1

    return {
        "meta": {
            "claims": len(claims),
            "days": len(days),
            "rules": len(rules),
            "counts": counts,
            "built_on": date.today().isoformat(),
            # 화면의 "진료비 확인" 이 어느 저장소의 워크플로를 부를지 알려 준다.
            # 러너가 굽기 때문에 저장소를 하드코딩할 필요가 없다 —
            # 템플릿에서 갈라져 나온 저장소는 자기 것을 부른다.
            # 검색창에 무엇을 넣을지 알려 주는 범위. 진료 내용과 잇히지 않는다.
            "patients": patients,
            "repo": os.environ.get("GITHUB_REPOSITORY", ""),
            "server": os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
            "ref": os.environ.get("GITHUB_REF_NAME", "main"),
        },
        "rules": rules,
        "days": [{"date": d, "claims": days[d]} for d in sorted(days, reverse=True)],
    }


def self_check() -> int:
    """DB 없이 빌드 로직만 점검한다."""
    rules = parse_rules(RULES.read_text(encoding="utf-8"))
    assert rules, "규정을 하나도 못 읽었습니다"
    with_codes = [r for r in rules if r["codes"]]
    assert with_codes, "대상 코드가 붙은 규정이 없습니다"
    assert all(r["effective"] for r in rules),         f"시행일 없는 규정: {[r['id'] for r in rules if not r['effective']]}"

    sample = {
        "hira_fee_code": with_codes[0]["codes"][0], "treatment_date": "2026-08-20",
        "total_charge_krw": "100000", "patient_charge_krw": "30000",
        "insurer_charge_krw": "70000", "copayment_rate": "0.3",
        "claim_status": "SUBMITTED",
    }
    j = judge(sample, rules)
    assert j["rules"], "대상 코드인데 규정이 안 걸렸습니다"
    assert j["verdict"] in ("불인정", "확인 필요", "이상 없음"), f"모르는 판정: {j['verdict']}"

    bad = {**sample, "patient_charge_krw": "50000"}
    assert any("본인부담금" in f["text"] for f in judge(bad, rules)["flags"]), "금액 검산이 동작하지 않습니다"

    # 신설 코드를 시행일 전 진료에 청구한 건은 불인정이어야 한다.
    # 예전에는 규정이 걸렸다는 이유로 "적용 규정 있음" 이라 적었다 — 읽는 사람이 정상으로 읽는다.
    new_rules = [r for r in with_codes if "신설" in r["kind"]]
    if new_rules:
        r = new_rules[0]
        y, m, d = (int(x) for x in r["effective"].split("-"))
        before = f"{y - 1:04d}-{m:02d}-{d:02d}"
        early = {**sample, "hira_fee_code": r["codes"][0], "treatment_date": before}
        assert judge(early, rules)["verdict"] == "불인정",             "시행일 전 신설코드 청구가 불인정으로 잡히지 않습니다"

    print(f"빌드 로직 OK — 규정 {len(rules)}건, 코드 붙은 규정 {len(with_codes)}건")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default="postgresql://llm_reader:llm-readonly@localhost:5432/billing")
    # 환자 ID 범위만 읽는다. 없으면 그 안내만 빠지고 나머지는 그대로 굽는다.
    ap.add_argument("--app-dsn", default="")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if args.check:
        return self_check()

    rules = parse_rules(RULES.read_text(encoding="utf-8"))
    claims = query(args.dsn)
    if not claims:
        sys.exit("청구 건을 하나도 읽지 못했습니다.")

    payload = build(claims, rules, patient_range(args.app_dsn) if args.app_dsn else {})
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    OUT.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", blob),
                   encoding="utf-8")

    m = payload["meta"]
    print(f"대시보드: 청구 {m['claims']}건 · {m['days']}일 · 규정 {m['rules']}건 → {OUT}")
    if m["patients"]:
        print(f"  환자 ID 범위: {m['patients']['first']} ~ {m['patients']['last']} "
              f"({m['patients']['count']}명)")
    for v, n in sorted(m["counts"].items(), key=lambda x: -x[1]):
        print(f"  {v}: {n}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
