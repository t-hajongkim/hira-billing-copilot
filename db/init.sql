-- 원무 청구 DB — 환자 / 진료 두 테이블.
--
-- 경계 설계: AI 에게 식별자를 "가린 뒤 전달"하지 않는다. 애초에 SELECT 하지 않는다.
-- 이름·주민번호토큰·전화·생년월일·환자ID 는 llm 뷰에 열 자체가 없다.
-- 나이는 진료일 기준으로 계산해서 넣는다 — 생년월일은 나가지 않는다.
--
-- 다만 환자 단위 연결은 살려야 한다("이전 치료 여부", "치료 횟수" 판단에 필요).
-- 그래서 patient_id 는 지우는 대신 컨테이너마다 새로 뽑는 비밀키로 HMAC 토큰화한다.

CREATE TABLE public.patient_master (
    patient_id            text PRIMARY KEY,
    patient_name          text NOT NULL,
    birth_date            date NOT NULL,
    sex                   text NOT NULL,
    mobile_phone          text NOT NULL,
    resident_id_token     text NOT NULL,
    insurance_type        text NOT NULL,
    insurance_eligibility text NOT NULL,
    copayment_type        text NOT NULL,
    special_case_type     text,
    registered_at         date NOT NULL,
    updated_at            date NOT NULL
);

CREATE TABLE public.treatment_claim (
    treatment_id             text PRIMARY KEY,
    encounter_id             text NOT NULL,
    patient_id               text NOT NULL REFERENCES public.patient_master(patient_id),
    treatment_date           date NOT NULL,
    visit_type               text NOT NULL,
    department_code          text NOT NULL,
    department_name          text NOT NULL,
    primary_diagnosis_code   text NOT NULL,
    secondary_diagnosis_codes text,
    order_type               text NOT NULL,
    hira_fee_code            text,
    order_name               text NOT NULL,
    drug_code                text,
    material_code            text,
    quantity                 numeric,
    unit                     text,
    frequency_per_day        numeric,
    days_supply              numeric,
    coverage_type            text NOT NULL,
    copayment_rate           numeric,
    unit_price_krw           bigint,
    total_charge_krw         bigint,
    patient_charge_krw       bigint,
    insurer_charge_krw       bigint,
    claim_status             text NOT NULL,
    order_reason_summary     text,
    created_at               timestamp NOT NULL
);

COPY public.patient_master FROM '/data/patient_master.csv'
    WITH (FORMAT csv, HEADER, ENCODING 'UTF8');
COPY public.treatment_claim FROM '/data/treatment_claim.csv'
    WITH (FORMAT csv, HEADER, ENCODING 'UTF8');

CREATE INDEX ON public.treatment_claim (patient_id, treatment_date);

-- ── AI 에게 나갈 수 있는 열 ──────────────────────────────────────────────
-- 청구 판단에 필요한 것만 있다. 이름·생년월일·연락처는 가려진 게 아니라 존재하지 않는다.
--
-- patient_id 는 이 뷰에 있다. 조회를 그 열로 걸어야 하기 때문이다.
-- 기획서 §5.2 — "환자 식별은 SQL 조회 단계에서만 사용하고, AI 에 전달되는 SELECT
-- 결과에서는 환자 ID 와 민감정보를 제외한다." 열은 두되 llm_reader 에게는
-- 그 열만 빼고 권한을 준다(아래 열 단위 GRANT).

CREATE SCHEMA llm;
REVOKE ALL ON SCHEMA llm FROM PUBLIC;

CREATE VIEW llm.claim WITH (security_barrier = true) AS
SELECT
    t.patient_id,   -- 조회 키. AI 에게 가는 결과에는 넣지 않는다.
    -- 진료일 기준 만 나이. 생년월일 자체는 나가지 않는다.
    date_part('year', age(t.treatment_date, p.birth_date))::int AS age,
    p.sex,
    p.insurance_type,
    p.insurance_eligibility,
    p.copayment_type,
    p.special_case_type,
    t.treatment_date,
    t.visit_type,
    t.department_code,
    t.department_name,
    t.primary_diagnosis_code,
    t.secondary_diagnosis_codes,
    t.order_type,
    t.hira_fee_code,
    t.order_name,
    t.drug_code,
    t.material_code,
    t.quantity,
    t.unit,
    t.frequency_per_day,
    t.days_supply,
    t.coverage_type,
    t.copayment_rate,
    t.unit_price_krw,
    t.total_charge_krw,
    t.patient_charge_krw,
    t.insurer_charge_krw,
    t.claim_status,
    t.order_reason_summary
FROM public.treatment_claim t
JOIN public.patient_master  p USING (patient_id);

REVOKE ALL ON ALL TABLES IN SCHEMA llm    FROM PUBLIC;
REVOKE ALL ON SCHEMA public               FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;

-- 여기까지가 데이터와 표면이다. 읽을 역할(llm_reader)과 그 권한, 그리고 권한을
-- 확인하는 게이트는 02-create-llm-role.sh 에 있다 — 비밀번호가 시크릿으로 들어오고,
-- SQL 파일은 환경변수를 못 읽기 때문이다.

-- 데이터 게이트. 하나라도 어긋나면 이미지가 만들어지지 않는다.
DO $$
DECLARE n int;
BEGIN
    SELECT count(*) INTO n FROM public.patient_master;
    IF n <> 50 THEN RAISE EXCEPTION '게이트 A — 환자 50명이 아니다: %', n; END IF;

    SELECT count(*) INTO n FROM public.treatment_claim;
    IF n <> 50 THEN RAISE EXCEPTION '게이트 A — 진료 50건이 아니다: %', n; END IF;

    -- 식별 열은 뷰에 아예 없어야 한다. 가려진 게 아니라 부재여야 한다.
    SELECT count(*) INTO n FROM information_schema.columns
    WHERE table_schema = 'llm' AND column_name IN
        ('patient_name','birth_date','mobile_phone',
         'resident_id_token','treatment_id','encounter_id');
    IF n > 0 THEN RAISE EXCEPTION '게이트 B — 식별 열이 뷰에 있다: %개', n; END IF;

    -- 나이는 있고 생년월일은 없어야 한다.
    SELECT count(*) INTO n FROM llm.claim WHERE age IS NULL OR age < 0 OR age > 120;
    IF n > 0 THEN RAISE EXCEPTION '게이트 D — 나이가 이상한 행 %건', n; END IF;

    SELECT count(*) INTO n FROM llm.claim;
    RAISE NOTICE '데이터 게이트 통과 - 뷰 %건', n;
END $$;
