---
permissions:
  contents: read
  packages: read
  copilot-requests: write
network:
  allowed:
    - defaults
    # apex 로 적는다 — 등록 도메인은 서브도메인을 자동 포함한다.
    - hira.or.kr
    - mohw.go.kr
    - data.go.kr
tools:
  cli-proxy: true
services:
  postgres:
    image: ghcr.io/${{ github.repository }}-db:latest
    credentials:
      username: ${{ github.actor }}
      password: ${{ secrets.GITHUB_TOKEN }}
    env:
      POSTGRES_DB: billing
      POSTGRES_USER: billing
      POSTGRES_PASSWORD: billing
    ports:
      - 5432:5432
    options: >-
      --health-cmd "pg_isready -h 127.0.0.1 -U billing -d billing"
      --health-interval 5s
      --health-timeout 5s
      --health-retries 30
steps:
  - name: Install PostgreSQL client
    run: sudo apt-get update -qq && sudo apt-get install -y -qq postgresql-client
mcp-scripts:
  query-billing-db:
    description: Run one read-only SELECT or WITH query against the de-identified llm.claim view.
    inputs:
      sql:
        description: Read-only SQL over the llm.claim view.
        required: true
    run: |
      case "$INPUT_SQL" in
        [Ss][Ee][Ll][Ee][Cc][Tt]*|[Ww][Ii][Tt][Hh]*) ;;
        *) printf 'Only SELECT or WITH queries are allowed.\n' >&2; exit 2 ;;
      esac
      psql -X -qAt -v ON_ERROR_STOP=1 \
        -h 127.0.0.1 -U llm_reader -d billing \
        --command "$INPUT_SQL"
    env:
      PGPASSWORD: llm-readonly
---

## 환자 / 진료 데이터베이스

`llm_reader` 역할로 `llm.claim` 뷰 하나만 읽습니다. 이름·생년월일·전화·주민번호토큰은
**가려진 것이 아니라 뷰에 열 자체가 없습니다.** 나이는 진료일 기준으로 이미 계산되어
있습니다.

`patient_id` 는 뷰에 열은 있지만 `llm_reader` 에게 권한이 없습니다 — 조회를 그 열로
걸어야 하는 쪽은 앱 자격증명을 쓰는 워크플로 스텝이고, 그쪽은 결과에서 그 열을 뺍니다.
그래서 `SELECT *` 는 권한 오류가 납니다. 필요한 열을 명시적으로 고르세요.

`llm.claim` 에서 읽을 수 있는 열:

```
age  sex  insurance_type  insurance_eligibility
copayment_type  special_case_type  treatment_date  visit_type
department_code  department_name  primary_diagnosis_code  secondary_diagnosis_codes
order_type  hira_fee_code  order_name  drug_code  material_code
quantity  unit  frequency_per_day  days_supply
coverage_type  copayment_rate  unit_price_krw  total_charge_krw
patient_charge_krw  insurer_charge_krw  claim_status  order_reason_summary
```

항상 지킬 것:

- 조회는 `query-billing-db` 로만, 대상은 `llm.claim` 뿐입니다.
- `SELECT *` 를 쓰지 않습니다 — 권한 오류가 납니다. 필요한 열만 명시적으로 고릅니다.
- 환자 단위 행을 저장소 파일·이슈 댓글에 그대로 쓰지 않습니다.
  보고는 진료 건 단위의 판단과 근거로 합니다.
