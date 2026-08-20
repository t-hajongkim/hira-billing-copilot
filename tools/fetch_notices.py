"""심평원·복지부 공고 목록을 받아 파일로 떨군다.

왜 파이썬인가 — gh aw 는 에이전트를 squid 프록시 뒤 샌드박스에 가둔다.
도메인을 허용목록에 넣어도 프록시가 한국 정부 사이트에 닿지 못한다(CONNECT 타임아웃).
반면 워크플로의 steps: 는 방화벽 밖 러너에서 돌고, 거기서는 1초에 200 이 온다.

그래서 받아오는 일은 여기서 하고, 무엇이 우리 청구에 닿는지는 에이전트가 판단한다.
네트워크를 타는 쪽과 판단하는 쪽이 나뉘어 있으면 AI 가 공고를 지어낼 수 없다 —
이 파일에 있는 것만 근거로 쓸 수 있다.

  python tools/fetch_notices.py --since 2026-08-01 --out .hira-fetch
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))

HEADERS = {
    # 정부 사이트는 기본 파이썬 UA 에 다르게 응답하는 경우가 있다.
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

# 제목에 이 말이 들어간 공고만 상세를 열고 첨부를 받는다.
# 전체를 다 받으면 채용·행사 공고까지 딸려 와서 에이전트가 볼 양이 의미 없이 커진다.
# 넓게 잡아 두고 최종 판단은 에이전트가 한다 — 여기서 놓치면 뒤에서 복구할 수 없다.
IMPORTANT_KEYWORDS = [
    "청구방법",
    "요양급여비용",
    "적용기준 및 방법에 관한 세부사항",
    "급여기준",
    "급여상한금액표",
    "본인일부부담금",
    "산정특례",
    "수가",
    "별도보상",
    "일부개정",
    "집행정지",
]

MAX_FILE_BYTES = 20 * 1024 * 1024      # 첨부 하나당
MAX_TOTAL_BYTES = 120 * 1024 * 1024    # 실행 전체
MAX_DETAILS = 40                        # 상세를 여는 공고 수 상한

SOURCES = [
    {
        "id": "hira-notice",
        "name": "심평원 공지사항",
        "url": "https://www.hira.or.kr/bbsDummy.do"
               "?pgmid=HIRAA020002000100&WT.gnb=%EA%B3%B5%EC%A7%80%EC%82%AC%ED%95%AD",
        "base": "https://www.hira.or.kr/bbsDummy.do",
    },
    {
        "id": "mohw-notice",
        "name": "보건복지부 고시·훈령·예규",
        "url": "https://www.mohw.go.kr/board.es?mid=a10409010000&bid=0026",
        "base": "https://www.mohw.go.kr/board.es",
    },
]

DATE_RE = re.compile(r"(20\d{2})[-.]\s?(\d{1,2})[-.]\s?(\d{1,2})")
ROW_RE = re.compile(r"<(?:tr|li)[^>]*>(.*?)</(?:tr|li)>", re.S)
LINK_RE = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S)
TAG_RE = re.compile(r"<[^>]+>")


def get(url: str, retries: int = 3, timeout: int = 30) -> tuple[int, str]:
    """받아온다. 실패는 감추지 않고 그대로 올린다."""
    ctx = ssl.create_default_context()
    last = ""
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                raw = r.read()
                for enc in ("utf-8", "euc-kr", "cp949"):
                    try:
                        return r.status, raw.decode(enc)
                    except UnicodeDecodeError:
                        continue
                return r.status, raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, ""
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"{retries}회 시도 실패: {last}")


def clean(html_fragment: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", html_fragment)).strip()


def parse_rows(html: str, base: str) -> list[dict]:
    """행마다 (날짜, 제목, 링크)를 뽑는다. 셋이 다 있는 행만 남긴다."""
    items, seen = [], set()
    for row in ROW_RE.findall(html):
        d = DATE_RE.search(row)
        a = LINK_RE.search(row)
        if not (d and a):
            continue
        title = clean(a.group(2))
        if not title or len(title) < 4:
            continue
        y, m, day = (int(x) for x in d.groups())
        try:
            published = date(y, m, day).isoformat()
        except ValueError:
            continue
        href = a.group(1).replace("&amp;", "&")
        link = urllib.parse.urljoin(base, href)
        key = (published, title)
        if key in seen:
            continue
        seen.add(key)
        items.append({"published": published, "title": title, "url": link})
    return items


def matched_keywords(title: str) -> list[str]:
    return [k for k in IMPORTANT_KEYWORDS if k in title]


META_FIELDS = {
    "제.개정일": re.compile(r"제\s*\.?\s*개정일\s*([0-9]{4}-[0-9]{2}-[0-9]{2})"),
    "발령번호": re.compile(r"발령번호\s*(제\s*[0-9\-\s]+호)"),
    "제개정구분": re.compile(r"제\s*\.?\s*개정\s*구분\s*(\S+)"),
    "분류": re.compile(r"분류\s*(고시|훈령|예규|지침|공고)"),
    "담당부서": re.compile(r"담당부서\s*(\S+)"),
}
FILE_RE = re.compile(r'<a[^>]+href=["\']([^"\']*(?:boardDownload|fileDown|download)[^"\']*)["\']', re.I)
EFFECTIVE_RE = re.compile(r"(?:시행일|시행)\s*[:은는]?\s*((?:20\d{2})\s*[.년-]\s*\d{1,2}\s*[.월-]\s*\d{1,2})")


def fetch_detail(item: dict, base: str, files_dir: Path, budget: dict) -> dict:
    """상세 페이지를 열어 메타데이터를 뽑고 첨부를 받는다.

    시행일은 목록에 없다 — 상세에만 있다. 공고일과 시행일이 다르기 때문에
    이걸 못 가져오면 어느 진료분부터 적용되는지 판단할 수 없다.
    """
    try:
        status, html = get(item["url"])
    except Exception as exc:  # noqa: BLE001
        return {"detail_status": f"unreachable: {exc}"[:120]}
    if status != 200:
        return {"detail_status": f"http_{status}"}

    text = re.sub(r"\s+", " ", TAG_RE.sub(" ", re.sub(
        r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)))

    out: dict = {"detail_status": "ok"}
    for name, rx in META_FIELDS.items():
        m = rx.search(text)
        if m:
            out[name] = re.sub(r"\s+", "", m.group(1))
    m = EFFECTIVE_RE.search(text)
    if m:
        out["시행일_추정"] = re.sub(r"\s+", "", m.group(1))

    # 본문은 에이전트가 읽을 만큼만. 전체를 넣으면 프롬프트가 터진다.
    body = text[:4000]
    out["body_excerpt"] = body

    saved = []
    for href in dict.fromkeys(FILE_RE.findall(html)):
        if budget["total"] >= MAX_TOTAL_BYTES:
            saved.append({"skipped": "총량 한도 초과"})
            break
        url = urllib.parse.urljoin(base, href.replace("&amp;", "&"))
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read(MAX_FILE_BYTES + 1)
                if len(blob) > MAX_FILE_BYTES:
                    saved.append({"url": url, "skipped": "파일 한도 초과"})
                    continue
                disp = r.headers.get("Content-Disposition", "")
                fname = ""
                fm = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disp)
                if fm:
                    fname = urllib.parse.unquote(fm.group(1)).strip()
                if not fname:
                    fname = re.sub(r"[^\w.-]", "_", href)[-60:] or "attachment"
                fname = re.sub(r"[\\/:*?\"<>|]", "_", fname)[:120]
                path = files_dir / f"{item['slug']}__{fname}"
                path.write_bytes(blob)
                budget["total"] += len(blob)
                saved.append({"file": path.name, "bytes": len(blob), "url": url})
        except Exception as exc:  # noqa: BLE001
            saved.append({"url": url, "error": str(exc)[:100]})
        time.sleep(0.5)

    out["attachments"] = saved
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="", help="이 날짜 이후 공고만 (YYYY-MM-DD)")
    ap.add_argument("--out", default=".hira-fetch")
    ap.add_argument("--min-items", type=int, default=3,
                    help="소스당 이 개수 미만이면 구조가 바뀐 것으로 본다")
    args = ap.parse_args()

    since = args.since.strip()
    if since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
        sys.exit(f"--since 형식이 잘못됨: {since}")

    out = Path(args.out)
    files_dir = out / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    budget = {"total": 0}

    manifest = {
        "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
        "since": since or None,
        "keywords": IMPORTANT_KEYWORDS,
        "sources": [],
    }
    ok_count = 0

    for src in SOURCES:
        entry = {"id": src["id"], "name": src["name"], "url": src["url"]}
        try:
            status, html = get(src["url"])
        except Exception as exc:  # noqa: BLE001
            entry |= {"status": "unreachable", "error": str(exc)[:200], "items": 0}
            manifest["sources"].append(entry)
            print(f"[{src['id']}] 접속 실패 — {exc}", file=sys.stderr)
            continue

        if status != 200:
            entry |= {"status": f"http_{status}", "items": 0}
            manifest["sources"].append(entry)
            print(f"[{src['id']}] HTTP {status}", file=sys.stderr)
            continue

        items = parse_rows(html, src["base"])
        if len(items) < args.min_items:
            # 200 인데 항목이 없으면 페이지 구조가 바뀐 것이다.
            # "변경 없음"과 구분해야 한다 — 조용히 넘어가면 안 된다.
            entry |= {"status": "parse_failed", "items": len(items),
                      "note": "HTTP 200 이지만 목록을 뽑지 못했습니다. 페이지 구조 변경 의심."}
            manifest["sources"].append(entry)
            print(f"[{src['id']}] 파싱 실패 — 항목 {len(items)}건", file=sys.stderr)
            continue

        fresh = [i for i in items if not since or i["published"] >= since]
        for n, i in enumerate(fresh):
            i["slug"] = f"{src['id']}-{i['published']}-{n:02d}"
            i["keywords"] = matched_keywords(i["title"])

        important = [i for i in fresh if i["keywords"]]
        for i in important[:MAX_DETAILS]:
            i["detail"] = fetch_detail(i, src["base"], files_dir, budget)
            time.sleep(0.6)

        entry |= {"status": "ok", "items": len(items), "items_in_window": len(fresh),
                  "keyword_hits": len(important),
                  "details_fetched": sum(1 for i in important if "detail" in i),
                  "latest": items[0]["published"] if items else None}
        manifest["sources"].append(entry)
        ok_count += 1

        lines = [f"# {src['name']}", "",
                 f"- 출처: {src['url']}",
                 f"- 받은 시각: {manifest['fetched_at']}",
                 f"- 전체 {len(items)}건 · 기간 내 {len(fresh)}건 · "
                 f"키워드 일치 {len(important)}건"
                 + (f" (since {since})" if since else ""),
                 "",
                 "키워드 일치 건만 상세 페이지를 열어 시행일·발령번호·첨부를 받았습니다.",
                 "나머지는 제목만 있습니다 — 필요하면 링크를 참고하되, 내용을 추측하지 마세요.",
                 ""]

        if important:
            lines += ["## 키워드 일치 — 상세 확인함", ""]
            for i in important:
                d = i.get("detail", {})
                lines += [f"### {i['title']}", "",
                          f"- 공고일: {i['published']}",
                          f"- 일치 키워드: {', '.join(i['keywords'])}",
                          f"- 링크: {i['url']}"]
                for k in ("분류", "제개정구분", "제.개정일", "발령번호", "담당부서", "시행일_추정"):
                    if d.get(k):
                        lines.append(f"- {k}: {d[k]}")
                if d.get("detail_status") != "ok":
                    lines.append(f"- ⚠️ 상세 조회 실패: {d.get('detail_status')}")
                atts = [a for a in d.get("attachments", []) if a.get("file")]
                if atts:
                    lines.append("- 첨부:")
                    lines += [f"  - `.hira-fetch/files/{a['file']}` ({a['bytes']:,} bytes)"
                              for a in atts]
                skipped = [a for a in d.get("attachments", []) if not a.get("file")]
                if skipped:
                    lines.append(f"- 받지 못한 첨부 {len(skipped)}건 (한도/오류)")
                if d.get("body_excerpt"):
                    lines += ["", "```text", d["body_excerpt"][:2500], "```"]
                lines.append("")

        others = [i for i in fresh if not i["keywords"]]
        if others:
            lines += ["## 키워드 불일치 — 제목만", "",
                      "| 공고일 | 제목 | 링크 |", "|---|---|---|"]
            lines += [f"| {i['published']} | {i['title'].replace('|', '｜')} | {i['url']} |"
                      for i in others]
            lines.append("")
        if not fresh:
            lines += ["기간 내 새 공고가 없습니다.", ""]

        (out / f"{src['id']}.md").write_text("\n".join(lines), encoding="utf-8")
        print(f"[{src['id']}] 전체 {len(items)} · 기간내 {len(fresh)} · "
              f"키워드 {len(important)} · 첨부 {budget['total']:,}B → {out}/{src['id']}.md")
        time.sleep(1)  # 정부 사이트에 예의

    manifest["downloaded_bytes"] = budget["total"]
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if ok_count == 0:
        print("::error::모든 출처에서 목록을 받지 못했습니다.", file=sys.stderr)
        return 1
    if ok_count < len(SOURCES):
        print(f"::warning::{len(SOURCES) - ok_count}개 출처 실패 — manifest.json 확인", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
