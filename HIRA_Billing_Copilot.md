# HIRA Billing Copilot 정리

## 1. 문제의식

병원 원무부의 진료비 청구는 이미 전산화되어 있지만, **심평원(HIRA) 및 보건복지부의 규정 변경을 확인하고 이를 실제 청구 기준에 반영하는 과정에는 여전히 사람의 확인과 해석이 많이 필요하다.**

심평원 관련 기준은 한 번 정해지고 끝나는 것이 아니라 지속적으로 변경된다.

- 요양급여비용 청구방법
- 수가 및 코드
- 급여 / 비급여 / 선별급여 기준
- 본인부담률
- 약제 및 치료재료 인정기준
- 검사·시술별 세부 인정조건
- 청구 명세서 작성방법

규정이 변경되더라도 모든 환자의 청구 규칙이 한 번에 바뀌는 것은 아니다.  
**특정 진료행위, 약제, 치료재료 또는 환자 조건에 해당하는 경우에만 새로운 규칙이 적용될 수 있다.**

또한 중요한 것은 **공고일과 실제 적용일이 항상 같지 않다는 점**이다.

예를 들어 새로운 규정이 발표되더라도 다음날부터 무조건 적용되는 것이 아니라, 각 고시에 명시된 시행일 또는 적용 진료분을 기준으로 판단해야 한다.

따라서 원무부에서는 단순히 현재 규정을 알고 있는 것보다,

> **현재 어떤 규정이 바뀌었는지 확인하고, 해당 규정이 특정 환자의 진료와 어떤 관계가 있는지 빠르게 판단하는 과정**

이 중요하다.

---

## 2. Pain Point

### 2.1 심평원 규정 변경을 지속적으로 확인해야 함

심평원 및 보건복지부에서는 청구와 관련된 규정, 수가, 급여기준 등을 지속적으로 업데이트한다.

원무부 입장에서는 새로운 공지가 올라올 때마다 다음 내용을 확인해야 한다.

- 어떤 규정이 변경되었는가
- 기존 규정과 무엇이 달라졌는가
- 어떤 진료과 또는 진료행위가 영향을 받는가
- 수가 또는 본인부담률이 변경되었는가
- 언제부터 적용되는가
- 특정 환자의 청구에 실제 영향을 주는가

이 과정을 사람이 매번 직접 확인하면 반복적인 업무가 발생한다.

---

### 2.2 규정은 많지만 실제 환자에게 필요한 규정은 일부임

심평원에는 수많은 의료행위, 약제, 치료재료 및 세부 인정기준이 존재한다.

하지만 특정 환자의 진료비를 계산할 때 필요한 것은 전체 규정이 아니라,

> **해당 환자의 조건 + 해당 진료내역과 관련된 규정**

이다.

따라서 전체 규정을 사람이 직접 검색하고 비교하는 과정은 비효율적이다.

---

### 2.3 환자 정보와 심평원 규정을 사람이 직접 매칭해야 함

실제 청구 판단에는 단순히 진료코드만 필요한 것이 아니라 여러 환자 정보가 함께 필요할 수 있다.

예:

- 환자의 나이
- 보험 관련 정보
- 진단
- 검사
- 처치
- 약제
- 진료일
- 과거 치료 여부
- 치료 횟수

원무부 담당자는 이러한 환자 정보를 확인한 뒤 다시 심평원 규정과 비교해야 한다.

즉 현재 업무는 본질적으로 다음과 같은 매칭 과정이다.

```text
환자 정보
    +
진료 정보
    +
심평원 규정
    ↓
청구 가능 여부 및 진료비 판단
```

---

### 2.4 환자 개인정보를 AI에 직접 전달하면 안 됨

AI가 청구 판단을 수행하더라도 환자의 이름, 환자 ID 등 민감한 식별정보를 AI가 볼 필요는 없다.

AI에게 필요한 것은 **청구 판단에 필요한 최소한의 환자 조건과 진료정보**이다.

따라서 환자 식별은 SQL 조회 단계에서만 사용하고, AI에 전달되는 SELECT 결과에서는 환자 ID와 민감정보를 제외해야 한다.

---

## 3. Pain Point 해결 방향

본 시스템은 기존 병원 청구 시스템 전체를 새로 만드는 것이 아니라,

> **원무부가 특정 환자의 진료비를 확인할 때 환자 진료정보와 최신 심평원 규정을 자동으로 연결해주는 Copilot**

을 목표로 한다.

핵심은 다음 세 가지이다.

### 3.1 심평원 업데이트 자동 추적

매일 아침 GitHub Workflow를 실행하여 심평원에 새로운 업데이트가 있는지 확인한다.

변경사항이 존재하면 해당 내용을 반영하여 심평원 규정 MD 파일을 업데이트한다.

```text
심평원
   ↓
매일 아침 GitHub Workflow
   ↓
새로운 규정 / 수가 / 청구정보 확인
   ↓
변경사항 정리
   ↓
HIRA Rule MD 업데이트
```

이를 통해 원무부 담당자가 매일 직접 심평원 홈페이지를 확인해야 하는 부담을 줄인다.

---

### 3.2 환자 및 진료정보 자동 조회

병원 내부에는 이미 Docker Container에서 환자 및 진료 정보를 저장하는 DB가 실행되고 있다고 가정한다.

DB는 크게 두 개의 테이블을 사용한다.

```text
Database
   ↓
┌───────────────┬───────────────┐
│ Patient Table │ Treatment Table│
│     환자       │      진료      │
└───────────────┴───────────────┘
```

원무부 담당자가 Issue에 환자 ID와 확인하고 싶은 진료내역을 입력하면 해당 ID를 이용해 SQL 조회를 수행한다.

---

### 3.3 AI를 이용한 환자 진료정보와 심평원 규정 매칭

SQL을 통해 반환된 환자 및 진료 정보에서 민감정보를 제거한 뒤 AI에 전달한다.

AI는 다음 두 정보를 함께 사용한다.

1. SQL SELECT 결과
2. 최신 심평원 규정 MD

그리고 해당 환자의 진료에 적용되는 심평원 규정을 찾아 진료비를 판단한다.

```text
SQL SELECT 결과
        +
HIRA Rule MD
        ↓
       AI
        ↓
진료비 및 청구 판단
```

---

# 4. Architecture

## 4.1 전체 구조

```text
                    [매일 아침]

HIRA ──> GitHub Workflow ──> HIRA Rule.md
                                │
                                │
                                ▼

원무과 ──> GitHub Issue ──> SQL ──> Patient Table
             환자 ID            │
                                ├──> Treatment Table
                                │
                                ▼
                           JOIN + SELECT
                                │
                          민감정보 제외
                                │
                                ▼
                               AI
                                ▲
                                │
                         HIRA Rule.md
                                │
                                ▼
                    진료비 / 청구 결과 판단
                                │
                                ▼
                         Issue에 결과 반환
```

---

## 4.2 Step 0-1. 심평원 규정 업데이트

하루에 한 번, 아침에 GitHub Workflow를 실행한다.

Workflow는 심평원에서 새로운 규정, 수가 또는 청구 관련 업데이트가 존재하는지 확인한다.

```text
GitHub Workflow
      ↓
심평원 업데이트 확인
      ↓
변경사항 존재?
      ↓
규정 내용 반영
      ↓
HIRA Rule.md 업데이트
```

MD 파일은 이후 AI가 환자의 진료정보와 비교할 Knowledge Base 역할을 한다.

---

## 4.3 Step 0-2. 환자 / 진료 Database

기존에 실행 중인 Docker Container 내부 DB를 사용한다.

주요 데이터는 두 테이블에 존재한다.

### Patient Table

환자와 관련된 정보를 저장한다.

예:

```text
patient_id
age
insurance_type
...
```

### Treatment Table

진료와 관련된 정보를 저장한다.

예:

```text
patient_id
treatment_date
diagnosis
procedure
drug
price
...
```

두 테이블은 `patient_id`를 기준으로 연결할 수 있다.

---

## 4.4 Step 1. 원무부 Issue 생성

원무부 담당자는 GitHub Issue를 통해 진료비 확인을 요청한다.

예:

```text
환자 ID: 12345

해당 환자의 이번 진료내역에 대해
청구 가능한 진료비를 확인해주세요.
```

Issue는 전체 파이프라인을 시작시키는 Trigger 역할을 한다.

---

## 4.5 Step 2. SQL 조회

Issue에 입력된 환자 ID를 이용하여 Patient Table을 조회한다.

이후 해당 환자의 진료내역을 Treatment Table과 JOIN한다.

```sql
Patient
   ↓
WHERE patient_id = ?
   ↓
Treatment JOIN
   ↓
필요한 Column SELECT
```

이 단계에서는 AI 판단에 필요한 정보만 SELECT한다.

AI에 전달하기 전에 다음과 같은 민감정보는 제외한다.

```text
patient_id
name
resident_number
phone
address
email
...
```

최종적으로 AI에게 전달되는 데이터는 예를 들어 다음과 같다.

```text
age
insurance_type
diagnosis
procedure
drug
treatment_date
previous_treatment
treatment_count
...
```

---

## 4.6 Step 3. AI 청구 판단

AI는 Issue 원문을 직접 보지 않는다.

Issue에는 환자 ID가 포함되어 있기 때문에, 시스템 프롬프트 및 Workflow 구조를 통해 AI가 Issue 내용을 직접 입력으로 받지 않도록 구성한다.

```text
Issue
[Patient ID 포함]
      │
      ├──────────── X ────────────> AI
      │
      ▼
     SQL
      ↓
환자 / 진료정보 조회
      ↓
민감정보 제외
      ↓
SELECT Result
      │
      └───────────────────────────> AI
```

AI에게 실제로 전달되는 정보는 두 가지이다.

```text
1. 비식별화된 환자 / 진료 정보

2. HIRA Rule.md
```

AI는 두 정보를 매칭하여 해당 진료에 대한 예상 청구금액과 판단 근거를 반환한다.

---

## 4.7 결과 반환

AI 판단 결과는 다시 GitHub Issue에 반환한다.

예:

```text
진료일
2026-08-13

진료내역
OO 검사

청구 판단
급여 인정

예상 진료비
XX,XXX원

적용 규정
심평원 OO 기준

판단 근거
- 해당 환자 조건 충족
- 해당 진료행위 급여기준 충족
- 현재 적용 중인 심평원 기준에 따라 산정
```

이를 통해 원무부 담당자는 별도로 심평원 규정을 검색하지 않고도 결과와 근거를 함께 확인할 수 있다.

---

# 5. 구현 시 조심할 점

## 5.1 AI가 Issue 원문을 직접 보지 않도록 구성

Issue에는 환자 ID가 들어가기 때문에 AI에게 Issue Body 전체를 그대로 전달하면 안 된다.

반드시 다음 순서를 유지한다.

```text
Issue
   ↓
SQL에서 환자 ID 사용
   ↓
DB 조회
   ↓
민감정보 제거
   ↓
SELECT 결과만 AI 전달
```

AI는 환자 ID를 알 필요가 없다.

---

## 5.2 SQL SELECT 단계에서 개인정보 제거

가능하면 AI에게 전달한 이후 개인정보를 제거하는 방식보다 **SQL SELECT 단계에서부터 불필요한 개인정보를 가져오지 않는 방식**을 사용한다.

```sql
SELECT
    age,
    insurance_type,
    diagnosis,
    procedure,
    treatment_date
```

처럼 필요한 column을 명시적으로 선택한다.

`SELECT *` 사용은 지양한다.

---

## 5.3 심평원 규정의 시행일 확인

심평원 규정은 공고된 다음날부터 자동 적용되는 것이 아니다.

각 규정마다 다음 정보가 다를 수 있다.

```text
published_at
effective_from
적용 진료분
```

따라서 MD를 업데이트할 때 단순히 새로운 문장을 추가하는 것만 아니라 **언제부터 적용되는 규정인지 함께 기록해야 한다.**

예:

```markdown
## Rule XXXXX

- 공고일: 2026-07-25
- 시행일: 2026-08-01
- 적용 기준: 2026-08-01 진료분부터
```

AI가 특정 환자의 진료일에 맞는 규정을 선택할 수 있도록 해야 한다.

---

## 5.4 규정 변경과 가격 변경을 구분

심평원 업데이트가 발생했다고 항상 진료가격이 변경되는 것은 아니다.

업데이트의 종류를 구분할 필요가 있다.

```text
수가 변경
본인부담률 변경
급여조건 변경
코드 신설
코드 삭제
약제 기준 변경
치료재료 기준 변경
청구방법 변경
```

예를 들어 가격은 동일하지만 본인부담률만 달라질 수도 있고, 가격은 그대로인데 급여 인정조건만 변경될 수도 있다.

---

## 5.5 기존 규정을 무조건 덮어쓰지 않기

환자 진료일에 따라 적용되는 규정이 달라질 수 있다.

따라서 새로운 규정이 올라왔다고 이전 규정 내용을 완전히 제거하면 과거 진료건을 다시 확인하기 어려울 수 있다.

MD 내부에서 최소한 시행일과 이전 규정 정보를 추적할 수 있도록 관리하는 것이 필요하다.

---

## 5.6 심평원 업데이트 실패 감지

매일 실행되는 Workflow가 실패했는데도 정상적으로 업데이트된 것처럼 처리되면 AI가 오래된 규정을 사용할 수 있다.

따라서 Workflow에서는 최소한 다음 상태를 확인해야 한다.

```text
마지막 업데이트 확인 시간
심평원 조회 성공 여부
변경사항 존재 여부
MD 업데이트 성공 여부
```

실패 시 로그 또는 Issue를 통해 확인할 수 있도록 한다.

---

## 5.7 AI 답변에 근거 규정을 같이 반환

AI가 단순히

```text
진료비는 32,000원입니다.
```

라고 답하면 원무부 담당자가 결과를 검증하기 어렵다.

따라서 항상 다음을 함께 반환하도록 한다.

```text
청구 결과
적용된 심평원 규정
시행일
판단에 사용한 환자 / 진료 조건
판단 근거
```

즉 AI의 역할은 단순 가격 출력이 아니라 **가격과 그 가격이 나온 이유를 함께 제공하는 것**이다.

---

# 6. 최종 목표

본 시스템의 목적은 기존 병원 청구 시스템을 대체하는 것이 아니다.

기존 DB와 원무 프로세스를 유지하면서,

```text
심평원 업데이트 확인
        ↓
환자 / 진료정보 검색
        ↓
관련 규정 검색
        ↓
규정과 환자정보 매칭
        ↓
진료비 판단
```

이라는 반복적인 과정을 자동화하는 것이 목표이다.

최종적으로는 원무부 담당자가 GitHub Issue에 환자 ID와 확인하고 싶은 진료내역을 입력하면,

> **현재 해당 환자의 진료에 적용되는 심평원 규정을 자동으로 찾아 예상 진료비와 판단 근거를 제공하는 HIRA Billing Copilot**

형태로 동작하도록 한다.
---

# 7. PoC Database Schema

본 PoC에서는 실제 병원 HIS / OCS / 원무 시스템이 사용하는 데이터를 그대로 복제하지 않고, **실제 병원에서 흔히 분리되어 있는 Patient Master, Encounter, Diagnosis, Order, Charge, Claim 정보를 `Patient Table`과 `Treatment Table` 두 개로 flatten하여 구성한다.**

즉 실제 운영 환경의 개념은 대략 다음과 같다.

```text
PATIENT
   │
   └── ENCOUNTER
          │
          ├── DIAGNOSIS
          ├── ORDER
          ├── PROCEDURE / DRUG / MATERIAL
          └── CHARGE / CLAIM
```

PoC에서는 이를 아래 두 개의 Table로 단순화한다.

```text
Patient Table
    │
    │ patient_id
    ▼
Treatment Table
```

`patient_id`는 Issue에서 환자를 찾고 두 Table을 JOIN하기 위한 Key로만 사용한다.  
AI에는 SQL 조회 이후 `patient_id`, 이름, 연락처 등 식별정보를 제외한 결과만 전달한다.

> **주의:** 함께 제공되는 CSV의 환자와 진료 데이터는 모두 합성 데이터이다. `DEMO-*` 형태의 수가·약제·치료재료 코드는 구조 시연을 위한 값이며 실제 심평원 청구코드로 사용하면 안 된다. 금액과 본인부담률 역시 PoC 동작 검증을 위한 예시 값이다.

## 7.1 Patient Table

환자 자체의 비교적 안정적인 정보와 보험 관련 속성을 저장한다.

| Column | 설명 | AI 전달 |
|---|---|---|
| `patient_id` | 병원 내부 환자 식별자 및 JOIN Key | X |
| `patient_name` | 환자 이름 | X |
| `birth_date` | 생년월일. SQL에서 진료일 기준 나이 계산에 사용 | 원본 X |
| `sex` | 성별 | 필요 시 O |
| `mobile_phone` | 연락처 | X |
| `resident_id_token` | 주민등록번호를 대신한 합성 식별 토큰 | X |
| `insurance_type` | 건강보험 / 의료급여 등 보험 유형 | O |
| `insurance_eligibility` | 보험 자격 상태 | O |
| `copayment_type` | 일반 / 경감 / 면제 등 본인부담 구분 | O |
| `special_case_type` | 산정특례 등 특수 보험 조건 | O |
| `registered_at` | 최초 등록일 | X |
| `updated_at` | 환자정보 최종 수정일 | X |

### Patient Table 역할

```text
Issue의 patient_id
        ↓
Patient Table 조회
        ↓
보험 / 연령 / 산정특례 등
청구 판단에 필요한 환자 조건 획득
```

`birth_date` 자체를 AI에 전달하기보다는 SQL에서 진료일 기준 나이로 변환한 뒤 `age_at_treatment` 형태로 넘기는 것을 기준으로 한다.

---

## 7.2 Treatment Table

실제 병원의 Encounter, Diagnosis, Order, Charge, Claim 정보를 하나의 Table에 flatten한 구조이다.

한 번의 내원 또는 입원은 `encounter_id`로 묶고, 같은 Encounter 안에서 검사·처치·약제 등이 여러 row로 존재할 수 있다.

| Column | 설명 |
|---|---|
| `treatment_id` | 개별 진료/오더 row ID |
| `encounter_id` | 동일 내원·입원 건을 묶는 ID |
| `patient_id` | Patient Table JOIN Key |
| `treatment_date` | 진료일. 심평원 규정 시행일 매칭의 핵심 기준 |
| `visit_type` | 외래 / 입원 / 응급 |
| `department_code` | 진료과 코드 |
| `department_name` | 진료과 이름 |
| `primary_diagnosis_code` | 주상병 코드 |
| `secondary_diagnosis_codes` | 부상병 코드 |
| `order_type` | 검사 / 처치 / 약제 / 치료재료 등의 구분 |
| `hira_fee_code` | 청구 수가코드 필드 |
| `order_name` | 검사·처치·약제 등의 표시명 |
| `drug_code` | 약제 코드. 약제가 아니면 공란 |
| `material_code` | 치료재료 코드. 치료재료가 아니면 공란 |
| `quantity` | 산정 수량 |
| `unit` | 회 / 개 / 정 등 단위 |
| `frequency_per_day` | 약제 등에서 1일 투여 횟수 |
| `days_supply` | 처방 일수 |
| `coverage_type` | 급여 / 선별급여 / 관리급여 / 비급여 구분 |
| `copayment_rate` | 해당 row에 사용된 본인부담률 |
| `unit_price_krw` | 단가 |
| `total_charge_krw` | 해당 row의 총 진료비 |
| `patient_charge_krw` | 환자 부담액 |
| `insurer_charge_krw` | 보험자 청구액 |
| `claim_status` | 미청구 / 제출 / 인정 / 조정 등 청구 상태 |
| `order_reason_summary` | 오더를 시행한 임상적 사유의 요약 |
| `created_at` | 진료 row 생성 시각 |

### Treatment Table 역할

```text
Patient Table
      +
Treatment Table
      ↓
patient_id JOIN
      ↓
진료일
진단
검사 / 처치 / 약제
보험 조건
현재 입력되어 있는 가격
      ↓
HIRA Rule.md와 매칭
```

특히 `treatment_date`는 중요하다.

```text
2026-07-31 진료
→ 2026-07-31에 유효한 HIRA Rule

2026-08-01 진료
→ 2026-08-01에 유효한 HIRA Rule
```

처럼 AI가 진료일을 기준으로 적용 규정을 선택해야 한다.

---

## 7.3 SQL JOIN 이후 AI에 전달할 값

AI가 Issue 원문이나 Patient Master 전체를 볼 필요는 없다.

SQL에서는 필요한 정보를 JOIN한 뒤 AI 판단에 필요한 Column만 반환한다.

예:

```text
age_at_treatment
sex
insurance_type
insurance_eligibility
copayment_type
special_case_type

treatment_date
visit_type
department_code
primary_diagnosis_code
secondary_diagnosis_codes

order_type
hira_fee_code
order_name
drug_code
material_code

quantity
frequency_per_day
days_supply

coverage_type
copayment_rate
unit_price_krw
total_charge_krw

order_reason_summary
```

다음 값은 SQL 결과에서 제외한다.

```text
patient_id
patient_name
mobile_phone
resident_id_token
```

전체 흐름은 다음과 같다.

```text
GitHub Issue
patient_id 포함
      ↓
SQL
      ↓
Patient + Treatment JOIN
      ↓
필요한 Column만 SELECT
      ↓
환자 식별정보 제거
      ↓
AI
      +
HIRA Rule.md
      ↓
예상 진료비 / 청구 판단
      ↓
Issue 결과 반환
```

---

## 7.4 Sample Dataset

PoC 테스트를 위해 다음 합성 CSV를 사용한다.

### `patient_master_50.csv`

- Patient Table 구조
- Header 제외 50개 환자 row
- 모든 이름·연락처·식별 토큰은 합성값
- 실제 개인정보 없음

### `treatment_claim_50.csv`

- Treatment Table 구조
- Header 제외 50개 진료/청구 row
- 여러 진료 row가 동일 환자 또는 동일 Encounter에 연결될 수 있음
- Patient Table의 `patient_id`와 참조 무결성 유지
- `total_charge_krw = patient_charge_krw + insurer_charge_krw`
- `DEMO-*` 코드는 실제 심평원 코드가 아닌 PoC 전용 합성 코드

이 Dataset의 목적은 **GitHub Issue → SQL JOIN → PII 제거 → HIRA Rule.md 매칭 → AI 청구 판단** 파이프라인을 구현하고 검증하는 것이다.
