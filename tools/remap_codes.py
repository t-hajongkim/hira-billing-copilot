"""데모 수가코드를 실제 심평원 코드로 바꾼다.

왜 필요한가
  진료내역이 DEMO-EGD001 같은 가짜 코드면 심평원 공고와 절대 겹치지 않는다.
  파이프라인은 정상인데 결론이 늘 "닿는 변경 없음"이 되어, 무엇도 시연되지 않는다.

무엇을 쓰는가
  .hira-fetch/files/ 에 실제로 받아 둔 XLSX 에서 뽑은 코드만 쓴다.
  지어낸 코드는 하나도 없다 — 가짜를 다른 가짜로 바꾸는 것은 의미가 없다.

  python tools/remap_codes.py            # 매핑 적용
  python tools/remap_codes.py --check    # 적용 안 하고 확인만
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

CSV_PATH = Path("db/data/treatment_claim.csv")

# (실제 코드, 실제 명칭, 출처 파일, 공고에서의 상태)
# 전부 .hira-fetch/files/ 의 심평원 첨부에서 뽑았다.
MAPPING = {
    "DEMO-EGD001": (
        "D6583066", "핵산증폭-정성그룹3 코로나바이러스감염증-19 응급용 선별검사",
        "(질병군)행위_별도보상코드목록_260803.xlsx", "별도보상 등재"),
    "DEMO-HOLTER48": (
        "F6051", "걷기검사-6분 걷기검사",
        "수가반영내역(26.7.31.시행).xlsx", "2026-07-31 신설"),
    "DEMO-MAT001": (
        "G1451018", "COMPOSITE MESH (100㎠ 미만)",
        "(질병군)치료재료_별도보상코드목록_260801.xlsx", "별도보상 등재"),
    "DEMO-LAB001": (
        "D5370006", "항-Infliximab 항체 [정밀면역검사] (정량)",
        "수가반영내역(26.8.1.시행).xlsx", "2026-08-01 변경"),
    "DEMO-US001": (
        "M2041029", "전파절삭기 (복강경 등 내시경하 수술용)",
        "(질병군)치료재료_별도보상코드목록_260801.xlsx", "별도보상 등재"),
    "DEMO-MRI001": (
        "F6052", "걷기검사-점증부하 왕복걷기검사",
        "수가반영내역(26.7.31.시행).xlsx", "2026-07-31 신설"),
    "DEMO-XR001": (
        "F6053", "걷기검사-지구력 왕복걷기검사",
        "수가반영내역(26.7.31.시행).xlsx", "2026-07-31 신설"),
    "DEMO-DRUG001": (
        "J4310055", "CONTINUOUS & BOLUS PCA (가스주입식/단일유속형)",
        "(질병군)치료재료_별도보상코드목록_260801.xlsx", "별도보상 등재"),
    "DEMO-PT001": (
        "N0031001", "복강경하 수술시 사용하는 치료재료 비용",
        "(질병군)행위_별도보상코드목록_260803.xlsx", "별도보상 등재"),
    # 삭제된 코드로 청구된 건을 일부러 남긴다.
    # 이런 건이 있어야 "이 청구는 지금 기준으로 성립하지 않는다"를 시연할 수 있다.
    "DEMO-MT001": (
        "AY102", "치과 급여(100대100) 항목",
        "수가반영내역(26.8.1.시행).xlsx", "260814~ 수가삭제"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if not CSV_PATH.exists():
        sys.exit(f"{CSV_PATH} 가 없습니다.")

    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    counts: dict[str, int] = {}
    unmapped: set[str] = set()

    for r in rows:
        old = r.get("hira_fee_code") or ""
        if old in MAPPING:
            code, name, _src, _state = MAPPING[old]
            counts[old] = counts.get(old, 0) + 1
            if not args.check:
                r["hira_fee_code"] = code
                r["order_name"] = name
                # 치료재료 코드면 material_code 도 맞춰 준다.
                if r.get("material_code") and code[0] in "GJMN":
                    r["material_code"] = code
        elif old and not old.startswith(tuple(MAPPING)):
            unmapped.add(old)

    print(f"{'확인' if args.check else '적용'} — 진료 {len(rows)}건")
    for old, (code, name, src, state) in MAPPING.items():
        n = counts.get(old, 0)
        if n:
            print(f"  {old:<15} → {code:<10} {state:<16} {n:>2}건  {name[:40]}")
    if unmapped:
        print(f"  매핑 안 된 코드: {', '.join(sorted(unmapped))}")

    if args.check:
        return 0

    with CSV_PATH.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"\n{CSV_PATH} 갱신됨. db/Dockerfile 을 다시 빌드하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
