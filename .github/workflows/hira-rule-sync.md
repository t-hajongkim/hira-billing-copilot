---
description: Check HIRA and MOHW for billing rule updates each morning and propose a rules/HIRA_RULES.md change in a pull request.
on:
  schedule:
    - cron: "0 21 * * *"   # 06:00 KST
  workflow_dispatch:
    inputs:
      since:
        description: 이 날짜 이후 공고만 확인 (YYYY-MM-DD). 비우면 마지막 동기화일부터.
        required: false
        type: string
env:
  REQUESTED_SINCE: ${{ inputs.since }}
# 쓰기 권한은 주지 않는다. 이슈 생성도 safe-outputs 를 거친다 —
# 에이전트가 무엇을 만들 수 있는지가 선언으로 고정된다.
permissions:
  contents: read
  packages: read
  copilot-requests: write
imports:
  - shared/billing-db.md
# 이 steps 는 에이전트가 뜨기 전, 방화벽 밖 러너에서 돈다.
# gh aw 의 squid 프록시는 한국 정부 사이트에 닿지 못하지만(CONNECT 타임아웃),
# 러너에서는 1초에 200 이 온다. 그래서 받아오는 일만 여기서 하고
# 무엇이 우리 청구에 닿는지는 에이전트가 판단한다.
steps:
  - name: 심평원·복지부 공고 받아오기
    run: python tools/fetch_notices.py --since "${REQUESTED_SINCE:-}" --out .hira-fetch
    env:
      REQUESTED_SINCE: ${{ inputs.since }}
safe-outputs:
  create-pull-request:
    title-prefix: "심평원 규정 동기화: "
    draft: false
    fallback-as-issue: false
    allowed-files:
      - "rules/**"
    protected-files: allowed
  create-issue:
    title-prefix: "[동기화 실패] "
timeout-minutes: 30
---

# 심평원 규정 동기화

매일 아침, 심평원과 보건복지부에 청구 관련 규정 변경이 올라왔는지 확인하고
`rules/HIRA_RULES.md` 를 갱신하는 PR 을 연다.

## 왜 이 워크플로가 필요한가

규정은 한 번 정해지고 끝나지 않는다. 그리고 **공고일과 시행일이 다르다.**
원무 담당자가 매일 직접 확인하는 대신, 변경분만 추려 PR 로 올린다.
머지하는 것이 곧 담당자의 확인이다.

## Task

1. `rules/HIRA_RULES.md` 를 먼저 읽는다. 머리말의 `마지막 동기화` 날짜와
   이미 기록된 규정 목록을 파악한다.
2. 확인 기간을 정한다.
   - `REQUESTED_SINCE` 가 `YYYY-MM-DD` 로 유효하면 그 날짜부터.
   - 아니면 `마지막 동기화` 다음 날부터 오늘(Asia/Seoul)까지.
3. `.hira-fetch/` 에 심평원 공지사항이 이미 받아져 있다. 인터넷에 직접 접근하지 않는다 —
   에이전트 방화벽은 심평원에 닿지 못하고, 조용히 실패한다. 여기 있는 것만 근거로 쓴다.

   - `.hira-fetch/manifest.json` — `status` 가 `ok` 인지 먼저 본다.
     `parse_failed` 는 "변경 없음"이 아니라 "게시판 구조가 바뀌었다"는 뜻이다.
     `ok` 가 아니면 파일을 고치지 말고 9번으로 간다.
   - `.hira-fetch/hira-notice.md` — 말머리(`[행위]`·`[치료재료]`·`[질병군]`·`[약제]` 등)와
     청구 키워드를 함께 만족한 **후보**, 각 후보의 본문 발췌(시행일·적용일·코드 주변),
     그리고 받아 둔 첨부 경로.
   - `.hira-fetch/files/` — XLS·HWP·PDF 첨부. 수가파일·별도보상 코드목록·급여상한금액표가
     여기 들어 있다. **규정 조문보다 이 코드 목록이 실제 청구에 더 직접적이다.**

   후보가 아닌 글은 제목만 실려 있다. 내용을 추측하지 않는다.

4. `query-billing-db` 로 **우리 병원이 실제로 청구하는 것**을 먼저 확인한다.
   전체 규정이 아니라 우리 진료내역과 맞물리는 것만 남기기 위해서다.
   최소한 이 세 가지를 본다.

   ```sql
   SELECT DISTINCT hira_fee_code, order_name, order_type FROM claim ORDER BY hira_fee_code;
   SELECT DISTINCT department_code, department_name FROM claim;
   SELECT DISTINCT coverage_type, copayment_rate FROM claim ORDER BY coverage_type;
   ```

5. 확인한 공고 중 **우리 청구에 닿는 것만** 남긴다. 남길지 말지는 다음으로 판단한다.
   - 우리가 쓰는 수가코드·약제코드·치료재료코드에 해당하는가
   - 우리 진료과에서 발생하는 행위인가
   - 본인부담률·급여조건·청구방법이 바뀌는가

   닿지 않으면 기록하지 않는다. 규정을 모으는 것이 목적이 아니라
   **우리 청구에 영향을 주는 것을 놓치지 않는 것**이 목적이다.

6. 남은 규정마다 `rules/HIRA_RULES.md` 에 항목을 **추가**한다. 기존 항목을
   지우거나 덮어쓰지 않는다 — 과거 진료분은 그때의 규정으로 판단해야 한다.

   ```markdown
   ## <규정 제목>

   - 규정 ID: `HIRA-<YYYY>-<연번>`
   - 공고일: YYYY-MM-DD
   - 시행일: YYYY-MM-DD
   - 적용 기준: YYYY-MM-DD 진료분부터
   - 변경 유형: 수가 변경 | 본인부담률 변경 | 급여조건 변경 | 코드 신설 | 코드 삭제 | 약제 기준 변경 | 치료재료 기준 변경 | 청구방법 변경
   - 대상: <해당 수가코드 · 진료과 · 약제 · 치료재료>
   - 출처: <URL>

   ### 무엇이 달라졌나
   <이전 기준 → 새 기준. 바뀌지 않은 것도 명시한다.>

   ### 우리 청구와의 관계
   <query-billing-db 로 확인한 사실. 해당 코드가 우리 진료내역에 몇 건 있는지,
    어느 진료과에서 발생하는지. 건수는 진료 건 단위로만 적는다.>

   ### 판단 시 주의
   <시행일 이전 진료분에는 적용되지 않는다는 점 등>
   ```

   **가격 변경과 조건 변경을 구분한다.** 금액은 그대로인데 본인부담률만 바뀌거나,
   금액은 그대로인데 급여 인정조건만 바뀌는 경우가 있다. 변경 유형에 정확히 적는다.

7. 머리말의 `마지막 동기화` 를 오늘 날짜로 갱신하고, `동기화 이력` 표에 한 줄 추가한다.
   변경이 없었어도 확인했다는 사실을 남긴다.

8. `create-pull-request` 를 한 번 요청한다. `rules/**` 만 바꾼다.
   PR 본문에는 확인 기간, 확인한 출처, 검토한 공고 수, 기록한 규정 수,
   **그리고 검토했지만 기록하지 않은 공고와 그 이유**를 적는다.

9. `manifest.json` 의 `status` 가 `ok` 가 아니면 — 파일을 고치지 말고
   `create-issue` 로 알린다. 제목에 실패한 출처와 날짜를, 본문에 `manifest.json` 의
   `manifest.json` 을 그대로 적는다.
   **조용히 성공한 것처럼 끝내지 않는다.** 그러면 원무 담당자가 오래된 규정으로 판단하게 된다.
10. 확인은 성공했고 우리 청구에 닿는 변경이 없으면, `마지막 동기화` 와 이력만
   갱신하는 PR 을 연다.

## 제약

- 모든 규정 항목에는 출처 URL 이 있어야 한다. 확인하지 못한 것은 적지 않는다.
- 공고일과 시행일을 반드시 구분해 적는다. 같은 날인 경우에도 둘 다 적는다.
- 환자 단위 행을 파일에 쓰지 않는다. 건수 집계만 쓴다.
- 규정 해석이 갈리는 경우 단정하지 말고 그 사실을 `판단 시 주의` 에 적는다.
