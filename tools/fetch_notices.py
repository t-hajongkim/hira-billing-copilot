"""심평원 공지사항에서 청구에 영향을 주는 변경을 받아 파일로 떨군다.

왜 심평원 공지사항 하나인가
  「청구방법 및 급여기준 조회시스템」(rulesvc)은 규정 본문을 조회하는 곳이지
  무엇이 바뀌었는지를 알려 주지 않는다. 그리고 병원이 실제로 필요한 것은 조문보다
  "어떤 코드를 적용하느냐"다 — 수가파일·별도보상 코드목록·급여상한금액표가
  이 게시판에 XLS/HWP 첨부로 함께 올라온다.

왜 파이썬인가
  gh aw 는 에이전트를 squid 프록시 뒤 샌드박스에 가둔다. 도메인을 허용목록에 넣어도
  프록시가 심평원에 닿지 못한다(CONNECT 타임아웃). 반면 워크플로의 steps: 는
  방화벽 밖 러너에서 돌고 거기서는 1초에 200 이 온다.
  받아오는 일은 여기서 하고, 무엇이 우리 청구에 닿는지는 에이전트가 판단한다.
  네트워크를 타는 쪽과 판단하는 쪽이 나뉘면 AI 가 공고를 지어낼 수 없다.

  python tools/fetch_notices.py --since 2026-07-25 --out .hira-fetch
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
ORIGIN = "https://www.hira.or.kr"
LIST_URL = f"{ORIGIN}/bbsDummy.do?pgmid=HIRAA020002000100&pageUnit=30"
DOWNLOAD_URL = f"{ORIGIN}/bbs/bbsCDownLoad.do"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": LIST_URL,
}

# 제목 앞에 붙는 말머리. 청구에 닿는 글은 거의 예외 없이 이 중 하나를 단다.
PREFIXES = [
    "[청구방법]", "[공고]", "[행위]", "[행위 공고]", "[행위 및 치료재료]",
    "[치료재료]", "[약제]", "[질병군]", "[집행정지 안내]",
]

# 말머리만 보면 [행위] 교육 안내까지 걸린다. 아래를 AND 로 건다.
KEYWORDS = [
    "청구방법", "요양급여비용", "수가", "수가파일",
    "급여기준", "적용기준", "세부사항",
    "본인일부부담금", "본인부담률", "산정특례",
    "급여상한금액표", "급여·비급여", "급여ㆍ비급여",
    "별도보상", "코드목록", "코드 목록",
    "일부개정", "신설", "삭제", "변경",
    "집행정지", "급여중지",
]

# 본문에서 이 말 주변만 잘라 에이전트에게 넘긴다.
# 공고일과 시행일이 다르므로 시행일을 못 찾으면 어느 진료분부터인지 판단할 수 없다.
# 목록의 작성일은 공고일이 아니다.
# 실증: 작성일 2025-04-01 / 공고일 2025-03-31 / 시행일 2025-04-01 (brdBltNo=11438).
# 진료일로 적용 규정을 고르는 도메인이라 이 셋을 섞으면 안 된다.
NOTICE_NO_RE = re.compile(
    r"고시\s*제(\d{4})-(\d+)호[,\s]*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.")
EFFECTIVE_RE = re.compile(
    r"\(?시행일\)?[^0-9]{0,10}(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*(진료분부터|청구분부터)?")

BODY_KEYWORDS = [
    "시행일", "적용일", "진료분부터", "청구분부터",
    "신설", "삭제", "변경", "개정",
    "본인부담률", "상한금액", "수가",
    "급여", "비급여", "선별급여", "코드",
]

WANT_EXT = (".xls", ".xlsx", ".hwp", ".hwpx", ".pdf", ".zip")
MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_DETAILS = 30
MAX_PAGES = 10

DATE_RE = re.compile(r"(20\d{2})[-.]\s?(\d{1,2})[-.]\s?(\d{1,2})")
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
LINK_RE = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S)
TAG_RE = re.compile(r"<[^>]+>")
# 첨부는 href 가 아니라 downLoadBbs(fileNo, apndBrdBltNo, apndBrdTyNo, apndBltNo) 로 걸려 있다.
DOWNLOAD_RE = re.compile(
    r"downLoadBbs\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*\)")
FILEROW_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.S)


def get(url: str, retries: int = 3, timeout: int = 45) -> tuple[int, bytes, dict]:
    last = ""
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, b"", {}
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"{retries}회 시도 실패: {last}")


def get_text(url: str) -> tuple[int, str]:
    status, raw, _ = get(url)
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return status, raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return status, raw.decode("utf-8", "replace")


def clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", fragment)).strip()


def is_candidate(title: str) -> tuple[bool, list[str]]:
    """말머리와 키워드를 AND 로 본다.

    말머리만 보면 [행위] 교육 안내까지 걸리고,
    키워드만 보면 '변경'·'개정'이 든 온갖 행정 공지가 걸린다.
    """
    hits = [p for p in PREFIXES if p in title]
    words = [k for k in KEYWORDS if k in title]
    return bool(hits and words), hits + words


def parse_list(html: str) -> list[dict]:
    items, seen = [], set()
    for row in ROW_RE.findall(html):
        d = DATE_RE.search(row)
        a = LINK_RE.search(row)
        if not (d and a):
            continue
        title = clean(a.group(2))
        if len(title) < 4:
            continue
        y, m, dd = (int(x) for x in d.groups())
        try:
            published = date(y, m, dd).isoformat()
        except ValueError:
            continue
        key = (published, title)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "posted": published,
            "title": title,
            "url": urllib.parse.urljoin(LIST_URL, a.group(1).replace("&amp;", "&")),
        })
    return items


def body_context(text: str) -> list[str]:
    """판단에 필요한 말 주변만 잘라 낸다. 전문을 넣으면 프롬프트가 터진다."""
    out: list[str] = []
    used: list[tuple[int, int]] = []
    for kw in BODY_KEYWORDS:
        for m in re.finditer(re.escape(kw), text):
            lo, hi = max(0, m.start() - 90), min(len(text), m.end() + 130)
            if any(lo < u_hi and u_lo < hi for u_lo, u_hi in used):
                continue
            used.append((lo, hi))
            out.append(text[lo:hi].strip())
            break
        if len(out) >= 24:
            break
    return out


def parse_attachments(html: str) -> list[dict]:
    found = []
    for li in FILEROW_RE.findall(html):
        m = DOWNLOAD_RE.search(li)
        if not m:
            continue
        label = clean(li)
        label = re.sub(r"첨부파일\s*다운로드.*$", "", label).strip()
        file_no, blt_no, ty_no, apnd_no = m.groups()
        q = urllib.parse.urlencode({
            "apndNo": file_no, "apndBrdBltNo": blt_no,
            "apndBrdTyNo": ty_no, "apndBltNo": apnd_no,
        })
        found.append({"label": label[:120], "url": f"{DOWNLOAD_URL}?{q}"})
    return list({f["url"]: f for f in found}.values())


def download(att: dict, slug: str, files_dir: Path, budget: dict) -> dict:
    if budget["total"] >= MAX_TOTAL_BYTES:
        return {**att, "skipped": "총량 한도 초과"}
    try:
        status, blob, headers = get(att["url"], retries=2, timeout=90)
    except Exception as exc:  # noqa: BLE001
        return {**att, "error": str(exc)[:120]}
    if status != 200 or not blob:
        return {**att, "error": f"http_{status}"}
    if len(blob) > MAX_FILE_BYTES:
        return {**att, "skipped": f"파일 한도 초과 ({len(blob):,}B)"}

    disp = headers.get("Content-Disposition", "")
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disp)
    name = urllib.parse.unquote(m.group(1)).strip() if m else (att["label"] or "attachment")
    # urllib 은 헤더를 latin-1 로 읽는다. 심평원은 UTF-8 바이트를 그대로 보낸다.
    try:
        name = name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    name = re.sub(r'[\\/:*?"<>|]', "_", name)[:120]
    if not name.lower().endswith(WANT_EXT):
        return {**att, "skipped": f"대상 확장자 아님 ({name})"}

    path = files_dir / f"{slug}__{name}"
    path.write_bytes(blob)
    budget["total"] += len(blob)
    return {**att, "file": path.name, "bytes": len(blob)}


def fetch_detail(item: dict, files_dir: Path, budget: dict) -> dict:
    try:
        status, html = get_text(item["url"])
    except Exception as exc:  # noqa: BLE001
        return {"status": f"unreachable: {exc}"[:120]}
    if status != 200:
        return {"status": f"http_{status}"}

    text = re.sub(r"\s+", " ", TAG_RE.sub(" ", re.sub(
        r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)))

    out: dict = {"status": "ok", "context": body_context(text)}

    m = NOTICE_NO_RE.search(text)
    if m:
        y, no, py, pm, pd = m.groups()
        out["고시번호"] = f"제{y}-{no}호"
        try:
            out["공고일"] = date(int(py), int(pm), int(pd)).isoformat()
        except ValueError:
            pass
    m = EFFECTIVE_RE.search(text)
    if m:
        ey, em, ed, scope = m.groups()
        try:
            out["시행일"] = date(int(ey), int(em), int(ed)).isoformat()
        except ValueError:
            pass
        if scope:
            out["적용범위"] = scope
    atts = parse_attachments(html)
    saved = []
    for a in atts:
        saved.append(download(a, item["slug"], files_dir, budget))
        time.sleep(0.4)
    out["attachments"] = saved
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="", help="이 날짜 이후 공고만 (YYYY-MM-DD)")
    ap.add_argument("--out", default=".hira-fetch")
    args = ap.parse_args()

    since = args.since.strip()
    if since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
        sys.exit(f"--since 형식이 잘못됨: {since}")

    out = Path(args.out)
    files_dir = out / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    budget = {"total": 0}
    fetched_at = datetime.now(KST).isoformat(timespec="seconds")

    # ── 1) 기간이 덮일 때까지 목록을 넘긴다 ──────────────────────────────
    items: list[dict] = []
    pages, status = 0, "ok"
    try:
        for pg in range(1, MAX_PAGES + 1):
            url = LIST_URL + (f"&pageIndex={pg}" if pg > 1 else "")
            code, html = get_text(url)
            if code != 200:
                status = f"http_{code}"
                break
            page_items = parse_list(html)
            if not page_items:
                break
            pages, items = pg, items + page_items
            if since and min(i["posted"] for i in page_items) < since:
                break
            time.sleep(0.8)
    except Exception as exc:  # noqa: BLE001
        status = f"unreachable: {exc}"[:150]

    seen: set = set()
    uniq = []
    for i in items:
        k = (i["posted"], i["title"])
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    items = uniq

    if status == "ok" and len(items) < 3:
        # HTTP 200 인데 목록이 안 뽑히면 페이지 구조가 바뀐 것이다.
        # "변경 없음"과 구분해야 한다 — 조용히 넘어가면 오래된 규정으로 판단하게 된다.
        status = "parse_failed"

    # ── 2) 말머리 + 키워드로 후보를 고른다 ───────────────────────────────
    fresh = [i for i in items if not since or i["posted"] >= since]
    for n, i in enumerate(fresh):
        i["slug"] = f"{i['posted']}-{n:02d}"
        i["candidate"], i["matched"] = is_candidate(i["title"])
    candidates = [i for i in fresh if i["candidate"]]

    # ── 3) 후보만 상세를 열고 첨부를 받는다 ──────────────────────────────
    if status == "ok":
        for i in candidates[:MAX_DETAILS]:
            i["detail"] = fetch_detail(i, files_dir, budget)
            time.sleep(0.6)

    manifest = {
        "fetched_at": fetched_at,
        "since": since or None,
        "source": {"name": "심평원 공지사항", "url": LIST_URL},
        "status": status,
        "pages_read": pages,
        "items": len(items),
        "items_in_window": len(fresh),
        "candidates": len(candidates),
        "details_fetched": sum(1 for i in candidates if "detail" in i),
        "downloaded_bytes": budget["total"],
        "prefixes": PREFIXES,
        "keywords": KEYWORDS,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ── 4) 에이전트가 읽을 파일 ──────────────────────────────────────────
    L = ["# 심평원 공지사항 — 청구 관련 변경", "",
         f"- 출처: {LIST_URL}",
         f"- 받은 시각: {fetched_at}",
         f"- 상태: `{status}` · {pages}페이지 · 전체 {len(items)}건 · "
         f"기간 내 {len(fresh)}건 · 후보 {len(candidates)}건",
         f"- 받은 첨부: {budget['total']:,} bytes", ""]

    if status != "ok":
        L += ["> ⚠️ 수집이 정상적으로 끝나지 않았습니다.",
              "> 이 파일의 내용으로 규정을 갱신하지 마세요.", ""]

    if candidates:
        L += ["## 후보 — 말머리 + 키워드 일치", ""]
        for i in candidates:
            d = i.get("detail", {})
            L += [f"### {i['title']}", "",
                  f"- 작성일: {i['posted']}",
                  f"- 일치: {', '.join(i['matched'])}",
                  f"- 링크: {i['url']}"]
            for k in ("고시번호", "공고일", "시행일", "적용범위"):
                if d.get(k):
                    L.append(f"- {k}: {d[k]}")
            if not d.get("시행일") and d.get("status") == "ok":
                L.append("- ⚠️ 본문에서 시행일을 찾지 못했습니다 — 첨부를 확인하세요.")
            if d.get("status") and d["status"] != "ok":
                L.append(f"- ⚠️ 상세 조회 실패: {d['status']}")
            got = [a for a in d.get("attachments", []) if a.get("file")]
            if got:
                L.append("- 첨부:")
                L += [f"  - `{args.out}/files/{a['file']}` ({a['bytes']:,}B)" for a in got]
            miss = [a for a in d.get("attachments", []) if not a.get("file")]
            if miss:
                L.append(f"- 받지 못한 첨부 {len(miss)}건: "
                         + "; ".join(a.get("skipped") or a.get("error", "?") for a in miss))
            if d.get("context"):
                L += ["", "본문 발췌 (시행일·적용일·코드 주변):", "", "```text"]
                L += [f"… {c} …" for c in d["context"]]
                L += ["```"]
            L.append("")

    others = [i for i in fresh if not i["candidate"]]
    if others:
        L += ["## 후보 아님 — 제목만", "",
              "말머리와 키워드를 함께 만족하지 않아 상세를 열지 않았습니다.", "",
              "| 작성일 | 제목 |", "|---|---|"]
        L += [f"| {i['posted']} | {i['title'].replace('|', '｜')} |" for i in others]
        L.append("")

    (out / "hira-notice.md").write_text("\n".join(L), encoding="utf-8")

    print(f"[심평원 공지사항] {status} · {pages}p · 전체 {len(items)} · "
          f"기간내 {len(fresh)} · 후보 {len(candidates)} · 첨부 {budget['total']:,}B")
    for i in candidates:
        n = len([a for a in i.get("detail", {}).get("attachments", []) if a.get("file")])
        print(f"  * {i['posted']} {i['title'][:56]} (첨부 {n})")

    if status != "ok":
        print(f"::error::수집 실패 — {status}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
