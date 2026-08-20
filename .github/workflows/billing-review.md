---
description: Judge one patient's already-queried claims against the current HIRA rules and produce a downloadable report.
on:
  workflow_dispatch:
    inputs:
      claims:
        description: 비식별 진료내역 JSON (billing-intake 가 SQL 로 뽑아 넘긴다)
        required: true
        type: string
      treatment_date:
        description: 진료일 필터 (보고서 머리말에만 쓴다)
        required: false
        type: string
      model:
        description: 판단에 쓸 모델 (비우면 auto)
        required: false
        type: string
        default: ""
# 실행할 때 고른 모델을 그대로 쓴다. 비우면 auto —
# Copilot 이 알아서 고르고, 어떤 요금제에서든 돈다.
model: ${{ inputs.model }}
env:
  TREATMENT_DATE: ${{ inputs.treatment_date }}
# 데이터베이스가 없다. 기획서 §5.2 — 환자 식별은 SQL 조회 단계에서만 쓰고
# AI 에게는 그 결과만 준다. 조회는 billing-intake 가 앱 자격증명으로 이미 끝냈다.
# 그래서 이 실행에는 postgres 서비스도, 조회 도구도, 환자를 가리키는 값도 없다.
# 요청마다 자기 줄을 쓴다.
# gh aw 기본값은 워크플로 하나에 줄 하나여서, 두 사람이 잇달아 요청하면 뒤에 온 것이
# 앞의 것을 대기열에서 밀어내고 취소시킨다. 실제로 그렇게 취소됐다.
# 요청끼리는 서로 볼 일이 없으니 각자 돌게 둔다.
concurrency:
  group: "billing-review-${{ github.run_id }}"

permissions:
  contents: read
  # gh aw 자신이 쓰는 컨테이너를 받아 온다. DB 이미지는 이제 이 실행에 없다.
  packages: read
  copilot-requests: write
steps:
  - name: 진료내역을 파일로 둔다
    env:
      CLAIMS: ${{ inputs.claims }}
    run: |
      set -euo pipefail
      printf '%s' "$CLAIMS" > claims.json
      # 여기서 한 번 더 본다. 식별값이 섞여 들어오면 에이전트에 닿기 전에 세운다.
      if grep -qE 'P[0-9]{5}' claims.json; then
        echo "::error::진료내역에 환자 ID 가 들어 있습니다"; exit 1
      fi
      python3 -c "import json;d=json.load(open('claims.json'));print(f'진료 {len(d)}건을 받았습니다')"
safe-outputs:
  # staged 는 "만들되 게시하지 않는다" 는 뜻이다. 에이전트에게 출력 창구는 주되,
  # 이슈·PR·커밋 어디에도 남기지 않는다. 판단 결과에는 그 환자의 진료 내용이
  # 들어 있고, 레포에 남기면 레포를 볼 수 있는 사람 모두에게 계속 남는다.
  # 아래 post-steps 가 그 출력을 HTML 로 바꿔 내려받게 한다.
  #
  # create-issue 를 쓰는 이유는 붙일 대상이 필요 없어서다. add-comment 는 이슈
  # 번호를 요구하는데 여기엔 이슈가 없다. 그래서 에이전트가 창구를 못 찾고
  # noop 으로 빠져 요약 한 줄만 남겼다 — 실제로 그렇게 됐다.
  # create-issue 는 제목과 본문만 있으면 되고, staged 라 이슈는 만들어지지 않는다.
  staged: true
  create-issue:
post-steps:
  - name: 결과 HTML 굽기
    if: always()
    env:
      REPORT_DATE: ${{ github.run_started_at }}
    run: |
      python3 tools/render_report.py         --input /tmp/gh-aw/safeoutputs.jsonl         --out "$RUNNER_TEMP/billing-report.html"

  - name: 결과 파일 올리기
    if: always()
    uses: actions/upload-artifact@v7
    with:
      name: billing-report
      path: ${{ runner.temp }}/billing-report.html
      retention-days: 7

  - name: 내려받는 곳
    if: always()
    run: |
      {
        echo "## 진료비 판단 결과"
        echo
        echo "이 실행 페이지 아래 **Artifacts** 의 \`billing-report\` 를 내려받아 여세요."
        echo
        echo "결과는 여기에만 있습니다 — 이슈·PR·커밋 어디에도 남기지 않습니다."
      } >> "$GITHUB_STEP_SUMMARY"
timeout-minutes: 30
---

# 진료비 청구 판단

원무 담당자가 환자 한 명의 진료비를 물었다. **그 환자의 진료내역은 이미 조회되어
`claims.json` 에 들어 있다.** 현재 심평원 규정과 대조해 청구 가능 여부와 예상 진료비를
판단하고, 근거와 함께 보고서로 낸다.

## 당신이 받는 것

- `claims.json` — 진료 건의 배열. 조회는 파이프라인이 앱 자격증명으로 이미 끝냈다.
- `rules/HIRA_RULES.md` — 현재까지 기록된 심평원 규정.
- `TREATMENT_DATE` — 진료일 필터가 걸렸다면 그 날짜. 비어 있으면 전체 기간이다.

**환자 ID·이름·생년월일은 당신에게 오지 않는다.** SQL SELECT 단계에서 빠졌다 —
가려진 것이 아니라 결과에 없다. 나이는 진료일 기준으로 이미 계산되어 있다.
요청 원문도 받지 않는다 — 거기엔 환자 ID 가 들어 있기 때문이다.

**데이터베이스에 접속하지 않는다. 접속할 것도 없다** — 이 실행에는 DB 가 없다.
`claims.json` 에 없는 사실은 지어내지 않는다.

## 답을 내는 방법

**`create-issue` 로 낸다.** 제목은 `진료비 청구 판단`, 본문이 보고서 전문이다.

이슈는 실제로 만들어지지 않는다. 이 워크플로는 staged 로 돌아서, 당신이 낸 본문은
게시되지 않고 그대로 **내려받는 HTML 보고서**가 된다. 이슈에도 PR 에도 커밋에도
남지 않는다. 그러니 요약만 적지 말고 **아래 형식의 전문을 본문에 담는다.**

## Task

1. `claims.json` 을 읽는다. 각 원소가 진료 한 건이다.
   비어 있으면(`[]`) 그 사실만 적고 끝낸다.

2. 판단에 쓸 환자 조건을 정리한다 — 나이(`age`), 성별(`sex`), 보험 유형(`insurance_type`),
   자격(`insurance_eligibility`), 본인부담 구분(`copayment_type`),
   산정특례(`special_case_type`). 모든 행에 같은 값이 들어 있다.

3. 같은 `hira_fee_code` 가 여러 번 나오면 횟수와 최초·최근 진료일을 센다.
   횟수 제한이나 이전 치료 여부가 조건인 규정이 있다.

4. `rules/HIRA_RULES.md` 를 읽고, 이 진료건의 `hira_fee_code` 에 닿는 규정을 찾는다.

   **진료일과 시행일을 반드시 대조한다.** 규정은 공고된 다음 날부터 자동 적용되지 않는다.
   각 규정의 `시행일` 과 `적용 기준`(예: "2026-08-01 진료분부터")을 보고,
   **그 진료건의 `treatment_date` 가 시행일 이후인지** 확인한다.
   시행일 이전 진료분에는 이전 기준을 적용한다.

   닿는 규정이 없으면 "기록된 규정 중 이 코드에 닿는 것이 없다"고 적는다.
   규정이 없는 것과 규정을 못 찾은 것은 다르다 — 후자면 그렇게 말한다.

5. 진료건마다 판단한다.

   - **급여 인정** — 조건을 충족한다. 무엇을 충족했는지 적는다.
   - **조건부** — 충족 여부를 이 데이터만으로 확정할 수 없다. 무엇을 더 확인해야 하는지 적는다.
   - **불인정** — 조건을 못 채우거나 코드가 삭제됐다. 근거 규정을 적는다.

   `claim_status` 가 `ADJUSTED`·`REJECTED` 면 이미 조정/반송된 건이다. 그 사실을 함께 적는다.
   기록된 규정에 **수가삭제**로 남은 코드가 청구돼 있으면 반드시 짚는다.
   **신설 코드가 시행일 전 진료에 청구돼 있으면** 그때는 없던 코드다 — 불인정으로 짚는다.

6. 금액을 확인한다. `total_charge_krw`, `patient_charge_krw`, `insurer_charge_krw` 가
   `copayment_rate` 와 맞는지 산술로 검증한다. 어긋나면 그 사실을 적는다 —
   **금액을 고쳐 쓰지 말고, 어긋났다고 보고한다.**

7. 결과를 `create-issue` 본문에 담는다. 형식은 아래 그대로 —
   이 마크다운이 그대로 표가 있는 HTML 보고서로 바뀐다. **요약으로 줄이지 않는다.**

   ```markdown
   ## 진료비 확인 결과

   대상: 진료 N건 (진료일 YYYY-MM-DD ~ YYYY-MM-DD)
   환자 조건: 만 NN세 · 성별 · 보험유형 · 본인부담구분 · 산정특례

   ### 진료일 YYYY-MM-DD — <order_name> (<hira_fee_code>)

   | 항목 | 값 |
   |---|---|
   | 청구 판단 | 급여 인정 / 조건부 / 불인정 |
   | 총액 | NN,NNN원 |
   | 본인부담 | NN,NNN원 (본인부담률 NN%) |
   | 공단부담 | NN,NNN원 |
   | 청구 상태 | SUBMITTED / ADJUSTED / … |

   **적용 규정**: <규정 제목> (`<규정 ID>`)
   - 시행일: YYYY-MM-DD · 적용 기준: YYYY-MM-DD 진료분부터
   - 진료일 YYYY-MM-DD 는 시행일 이후 → 이 규정 적용

   **판단 근거**
   - <환자 조건 중 무엇이 충족/미충족인지>
   - <진료 조건 중 무엇이 충족/미충족인지>
   - <금액 검증 결과>

   ### 확인이 필요한 것
   - <담당자가 사람 눈으로 봐야 할 것>
   ```

   진료건이 여러 개면 건마다 반복한다. 마지막에 합계를 적는다.

## 제약

- 금액만 답하지 않는다. **적용 규정·시행일·판단 근거를 반드시 함께 적는다.**
  담당자가 검증할 수 없는 답은 쓸모가 없다.
- 규정에 없는 조건을 만들어 내지 않는다. 판단이 안 서면 "조건부"로 두고 무엇이 필요한지 적는다.
- 보고서는 진료 건 단위로 적는다. 환자를 가리키는 값은 애초에 받지 않았으니 쓸 일도 없다.
- 이 답변은 원무 담당자의 확인이 필요한 참고자료다. 마지막에 그 사실을 한 줄로 적는다.
