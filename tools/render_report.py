"""청구 판단 결과를 내려받을 HTML 파일 하나로 굽는다.

왜 이렇게 하나
  판단 결과에는 그 환자의 진료 내용이 들어 있다. 이슈 댓글이나 커밋으로 남기면
  레포를 볼 수 있는 사람 모두에게 계속 남는다. 그래서 남기지 않는다 —
  실행 아티팩트로만 내려받게 하고, 아티팩트는 보존 기간이 지나면 사라진다.

  에이전트의 출력은 gh aw 가 /tmp/gh-aw/safeoutputs.jsonl 에 적어 둔다.
  safe-outputs 는 staged 로 두어 아무 데도 게시되지 않는다. 이 도구가 그 파일을
  읽어 HTML 로 바꾼다.

  변환기는 여기 직접 넣었다. 러너에 패키지를 깔면 그 설치가 또 하나의
  실패 지점이 되고, 보고서가 쓰는 마크다운은 제목·표·목록·강조가 전부다.

  python tools/render_report.py --check     # 입력 없이 변환기만 점검
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path

# 환자 ID 가 어떤 경로로든 보고서에 들어오면 여기서 가린다.
# 에이전트에게는 애초에 가지 않지만, 마지막 그물은 있어야 한다.
PATIENT_ID_RE = re.compile(r"\bP\d{5}\b")
TOKEN_RE = re.compile(r"\b(PT|EN)_[0-9a-f]{12}\b")

STYLE = """
:root{--bg:#f1f2f0;--panel:#fff;--line:#e4e6e1;--ink:#0b0b0c;
  --dim:rgba(60,60,67,.55);--accent:#FFE66D;--accent-bg:#FFF9E0;
  --gold:#8a6d00;--danger:#FF4438;--danger-bg:#FFECEA}
*{box-sizing:border-box}
body{margin:0;padding:32px 20px 64px;background:var(--bg);color:var(--ink);
  -webkit-font-smoothing:antialiased;line-height:1.65;
  font-family:Pretendard,-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',
    'Malgun Gothic','맑은 고딕',sans-serif}
.sheet{max-width:860px;margin:0 auto;background:var(--panel);border:1.5px solid var(--line);
  border-radius:20px;padding:34px 38px 40px}
.top{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;
  padding-bottom:18px;margin-bottom:26px;border-bottom:1.5px solid var(--line)}
.top h1{margin:0;font-size:19px;font-weight:800;letter-spacing:-.5px}
.top .meta{font-size:12.5px;font-weight:650;color:var(--dim);
  font-variant-numeric:tabular-nums}
h2{font-size:16.5px;font-weight:800;letter-spacing:-.4px;margin:34px 0 12px}
h3{font-size:14px;font-weight:780;letter-spacing:-.2px;margin:26px 0 10px;
  padding-left:10px;border-left:3px solid var(--accent)}
p{margin:10px 0;font-size:13.5px}
ul{margin:10px 0;padding-left:20px}
li{font-size:13.5px;margin:5px 0}
hr{border:0;border-top:1.5px solid var(--line);margin:30px 0}
code{background:var(--accent-bg);border:1px solid #f0e3ae;border-radius:6px;
  padding:1px 5px;font-size:12.5px;font-variant-numeric:tabular-nums;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
strong{font-weight:750}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}
th,td{border:1px solid var(--line);padding:8px 11px;text-align:left;
  font-variant-numeric:tabular-nums}
th{background:#f6f7f4;font-weight:750;width:34%}
.note{margin-top:34px;padding:13px 16px;background:var(--accent-bg);
  border:1.5px solid #f0e3ae;border-radius:13px;font-size:12.5px;font-weight:650;
  color:var(--gold)}
.empty{padding:40px 0;text-align:center;color:var(--dim);font-weight:650;font-size:13.5px}
@media print{body{background:#fff;padding:0}.sheet{border:0;border-radius:0}}
"""


def inline(text: str) -> str:
    """이스케이프한 뒤에만 서식을 붙인다 — 순서가 바뀌면 태그가 새어 든다."""
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    return out


def render(md: str) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i, n = 0, len(lines)

    def close_list(open_ul: bool) -> bool:
        if open_ul:
            out.append("</ul>")
        return False

    ul = False
    while i < n:
        ln = lines[i]
        s = ln.strip()

        if not s:
            ul = close_list(ul)
            i += 1
            continue

        # 표 — 헤더 줄 다음이 구분선이어야 표로 본다.
        if s.startswith("|") and i + 1 < n and re.fullmatch(r"\|[\s:|-]+\|", lines[i + 1].strip()):
            ul = close_list(ul)
            cells = [c.strip() for c in s.strip("|").split("|")]
            out.append("<table><thead><tr>"
                       + "".join(f"<th>{inline(c)}</th>" for c in cells)
                       + "</tr></thead><tbody>")
            i += 2
            while i < n and lines[i].strip().startswith("|"):
                row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
                i += 1
            out.append("</tbody></table>")
            continue

        if re.fullmatch(r"-{3,}", s):
            ul = close_list(ul)
            out.append("<hr>")
            i += 1
            continue

        m = re.match(r"(#{1,6})\s+(.*)", s)
        if m:
            ul = close_list(ul)
            lvl = min(max(len(m.group(1)), 2), 3)
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            i += 1
            continue

        m = re.match(r"[-*]\s+(.*)", s)
        if m:
            if not ul:
                out.append("<ul>")
                ul = True
            out.append(f"<li>{inline(m.group(1))}</li>")
            i += 1
            continue

        if s.startswith(">"):
            ul = close_list(ul)
            out.append(f'<p class="quote">{inline(s.lstrip("> "))}</p>')
            i += 1
            continue

        ul = close_list(ul)
        para = [s]
        i += 1
        while i < n and lines[i].strip() and not re.match(r"^(#{1,6}\s|[-*]\s|\||>|-{3,}$)",
                                                          lines[i].strip()):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline(' '.join(para))}</p>")

    close_list(ul)
    return "\n".join(out)


def read_report(path: Path) -> str:
    """gh aw 가 남긴 safeoutputs.jsonl 에서 보고서 본문만 뽑는다."""
    if not path.exists():
        return ""
    bodies = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            item = json.loads(ln)
        except json.JSONDecodeError:
            continue
        # body 가 보고서 전문이다. 에이전트가 창구를 못 찾아 noop 으로 빠지면
        # message 에 요약 한 줄만 남는다 — 그때라도 빈 화면보다는 낫다.
        for key in ("body", "message"):
            v = item.get(key)
            if isinstance(v, str) and v.strip():
                bodies.append(v.strip())
                break
    return "\n\n---\n\n".join(bodies)


def scrub(text: str) -> str:
    """마스킹은 반드시 변환 뒤에 한다 — 변환 전에 하면 P**** 의 별표를
    마크다운 굵게 문법이 먹어 치운다."""
    text = PATIENT_ID_RE.sub("P****", text)
    return TOKEN_RE.sub(lambda m: f"{m.group(1)}_****", text)


def page(body_html: str, run: str, repo: str, when: str) -> str:
    meta = " · ".join(x for x in [repo, f"실행 #{run}" if run else "", when] if x)
    return f"""<!doctype html>
<html lang="ko">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>진료비 청구 판단 결과</title>
<style>{STYLE}</style>
<div class="sheet">
  <div class="top">
    <h1>진료비 청구 판단 결과</h1>
    <span class="meta">{html.escape(meta)}</span>
  </div>
  {body_html}
  <div class="note">이 결과는 원무 담당자의 확인이 필요한 참고자료입니다.
  확정 청구 판단을 대체하지 않습니다. 환자 식별정보는 판단 과정에 사용되지 않았습니다.</div>
</div>
</html>
"""


def self_check() -> int:
    md = ("## 진료비 확인 결과\n\n대상: 진료 2건\n\n"
          "### 진료일 2026-08-19 — 걷기검사 (`F6052`)\n\n"
          "| 항목 | 값 |\n|---|---|\n| 청구 판단 | 불인정 |\n| 총액 | 460,000원 |\n\n"
          "**판단 근거**\n- 진료일이 시행일보다 앞선다\n- 환자 P00013 토큰 PT_9420e20e1801\n")
    h = scrub(render(md))
    assert "<table>" in h and "<th>항목</th>" in h, "표가 변환되지 않았습니다"
    assert "<h3>" in h, "제목이 변환되지 않았습니다"
    assert "<li>" in h, "목록이 변환되지 않았습니다"
    assert "<strong>판단 근거</strong>" in h, "강조가 변환되지 않았습니다"
    assert "<code>F6052</code>" in h, "코드 서식이 변환되지 않았습니다"
    assert "P00013" not in h and "P****" in h, "환자 ID 가 가려지지 않았습니다"
    assert "9420e20e1801" not in h, "토큰이 가려지지 않았습니다"
    assert "<script" not in scrub(render("<script>alert(1)</script>")), "이스케이프가 뚫립니다"
    print("변환기 OK — 표·제목·목록·강조·마스킹·이스케이프")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="/tmp/gh-aw/safeoutputs.jsonl")
    ap.add_argument("--out", default="billing-report.html")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if args.check:
        return self_check()

    md = read_report(Path(args.input))
    body = scrub(render(md)) if md.strip() else \
        '<div class="empty">판단 결과가 비어 있습니다. 실행 로그를 확인해 주세요.</div>'

    Path(args.out).write_text(
        page(body,
             os.environ.get("GITHUB_RUN_NUMBER", ""),
             os.environ.get("GITHUB_REPOSITORY", ""),
             os.environ.get("REPORT_DATE", "")),
        encoding="utf-8")

    print(f"결과 HTML: {args.out} ({len(md)}자 → {Path(args.out).stat().st_size}바이트)")
    if not md.strip():
        print("::warning::에이전트 출력이 비어 있습니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
