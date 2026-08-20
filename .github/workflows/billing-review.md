---
description: Judge one patient's claims against the current HIRA rules and produce a downloadable report.
on:
  workflow_dispatch:
    inputs:
      patient_token:
        description: 환자 토큰 (billing-intake 가 환자 ID 를 바꿔 넘긴다)
        required: true
        type: string
      treatment_date:
        description: 진료일 필터 (비우면 전체)
        required: false
        type: string
env:
  PATIENT_TOKEN: ${{ inputs.patient_token }}
  TREATMENT_DATE: ${{ inputs.treatment_date }}
permissions:
  contents: read
  packages: read
  copilot-requests: write
imports:
  - shared/billing-db.md
safe-outputs:
  # staged 는 "만들되 게시하지 않는다" 는 뜻이다. 에이전트에게 출력 창구는 주되,
  # 이슈·PR·커밋 어디에도 남기지 않는다. 판단 결과에는 그 환자의 진료 내용이
  # 들어 있고, 레포에 남기면 레포를 볼 수 있는 사람 모두에게 계속 남는다.
  # 아래 post-steps 가 그 출력을 HTML 로 바꿔 내려받게 한다.
  staged: true
  add-comment:
    target: "*"
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

원무 담당자가 환자 한 명의 진료비를 물었다. 그 환자의 진료내역과 현재 심평원 규정을
대조해 청구 가능 여부와 예상 진료비를 판단하고, 근거와 함께 보고서로 낸다.

## 당신이 받는 것

- `PATIENT_TOKEN` — 환자 하나를 가리키는 토큰.
- `TREATMENT_DATE` — 진료일 필터. 비어 있으면 그 환자의 전체 진료내역을 본다.
- `rules/HIRA_RULES.md` — 현재까지 기록된 심평원 규정.
- `query-billing-db` — 비식별 `llm.claim` 뷰 조회.

**환자 ID·이름·생년월일은 당신에게 오지 않는다.** 뷰에 열 자체가 없다.
`PATIENT_TOKEN` 은 되돌릴 수 없고, 다른 값의 토큰을 만들 수도 없다.
이슈 본문도 받지 않는다 — 거기엔 환자 ID 가 들어 있기 때문이다.

당신의 답은 **내려받는 HTML 보고서 하나**가 된다. 이슈에도 PR 에도 커밋에도 남지 않는다.

## Task

1. 그 환자의 진료내역을 조회한다. 필요한 열만 고른다 — `SELECT *` 를 쓰지 않는다.

   ```sql
   SELECT treatment_date, visit_type, department_name,
          primary_diagnosis_code, secondary_diagnosis_codes,
          order_type, hira_fee_code, order_name, drug_code, material_code,
          quantity, unit, coverage_type, copayment_rate,
          unit_price_krw, total_charge_krw, patient_charge_krw, insurer_charge_krw,
          claim_status, order_reason_summary,
          age, sex, insurance_type, insurance_eligibility, copayment_type, special_case_type
   FROM claim
   WHERE patient_token = '<PATIENT_TOKEN>'
   ORDER BY treatment_date
   ```

   `TREATMENT_DATE` 가 있으면 `AND treatment_date = '<TREATMENT_DATE>'` 를 붙인다.
   조회 결과가 없으면 그 사실만 적고 끝낸다. 지어내지 않는다.

2. 판단에 쓸 환자 조건을 정리한다 — 나이, 성별, 보험 유형(`insurance_type`),
   자격(`insurance_eligibility`), 본인부담 구분(`copayment_type`),
   산정특례(`special_case_type`).

3. 같은 환자의 과거 진료를 확인한다. 횟수 제한이나 이전 치료 여부가 조건인 규정이 있다.

   ```sql
   SELECT hira_fee_code, order_name, count(*) AS 횟수,
          min(treatment_date) AS 최초, max(treatment_date) AS 최근
   FROM claim WHERE patient_token = '<PATIENT_TOKEN>'
   GROUP BY 1, 2 ORDER BY 3 DESC
   ```

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

6. 금액을 확인한다. `total_charge_krw`, `patient_charge_krw`, `insurer_charge_krw` 가
   `copayment_rate` 와 맞는지 산술로 검증한다. 어긋나면 그 사실을 적는다 —
   **금액을 고쳐 쓰지 말고, 어긋났다고 보고한다.**

7. 결과를 낸다. 형식은 아래 그대로 — 이 마크다운이 그대로 표가 있는 HTML 로 바뀐다.

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
- 환자 단위 행이나 토큰을 보고서에 그대로 쓰지 않는다. 진료 건 단위 판단으로 적는다.
- 이 답변은 원무 담당자의 확인이 필요한 참고자료다. 마지막에 그 사실을 한 줄로 적는다.
