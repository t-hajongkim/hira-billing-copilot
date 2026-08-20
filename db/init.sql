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

-- ── 가명화 ────────────────────────────────────────────────────────────────
-- 해시만 쓰면 환자ID 사전을 만들어 되짚을 수 있다. 컨테이너마다 새로 뽑는
-- 비밀키를 섞어야 그 경로가 막힌다. 결정적이라 같은 환자는 늘 같은 토큰이다.

CREATE SCHEMA private;
REVOKE ALL ON SCHEMA private FROM PUBLIC;

-- pgcrypto 를 private 에 둔다. 그래야 아래 함수의 search_path(pg_catalog, private)
-- 안에서 hmac 이 잡히고, public 을 열어 둘 필요가 없다.
CREATE EXTENSION IF NOT EXISTS pgcrypto SCHEMA private;

CREATE TABLE private.masking_secret (
    id     boolean PRIMARY KEY DEFAULT true CHECK (id),
    secret text NOT NULL
);
INSERT INTO private.masking_secret (secret)
VALUES (encode(private.gen_random_bytes(32), 'hex'));

CREATE FUNCTION private.token(kind text, value text)
RETURNS text
LANGUAGE sql STABLE STRICT SECURITY DEFINER
SET search_path = pg_catalog, private
AS $$
    SELECT kind || '_' || left(encode(hmac(value, secret, 'sha256'), 'hex'), 12)
    FROM private.masking_secret WHERE id
$$;
REVOKE ALL ON FUNCTION private.token(text, text) FROM PUBLIC;

-- 토큰을 컬럼으로 굳힌다.
--
-- 뷰 안에서 함수를 부르면 EXECUTE 권한을 호출자(llm_reader)에게 줘야 한다.
-- 그러면 AI 가 P00001..P00050 을 넣어 토큰을 계산해 보고 환자 ID 를 역추적할 수 있다.
-- 미리 계산해 두면 그 권한 자체가 필요 없어진다 — AI 는 토큰을 받기만 하고 만들지는 못한다.

ALTER TABLE public.patient_master   ADD COLUMN patient_token   text;
ALTER TABLE public.treatment_claim  ADD COLUMN patient_token   text;
ALTER TABLE public.treatment_claim  ADD COLUMN encounter_token text;

UPDATE public.patient_master  SET patient_token   = private.token('PT', patient_id);
UPDATE public.treatment_claim SET patient_token   = private.token('PT', patient_id),
                                  encounter_token = private.token('EN', encounter_id);

ALTER TABLE public.patient_master  ALTER COLUMN patient_token   SET NOT NULL;
ALTER TABLE public.treatment_claim ALTER COLUMN patient_token   SET NOT NULL,
                                   ALTER COLUMN encounter_token SET NOT NULL;

-- ── AI 가 보는 표면 ────────────────────────────────────────────────────────
-- 청구 판단에 필요한 것만 있다. 없는 열은 가려진 게 아니라 존재하지 않는다.

CREATE SCHEMA llm;
REVOKE ALL ON SCHEMA llm FROM PUBLIC;

CREATE VIEW llm.claim WITH (security_barrier = true) AS
SELECT
    t.patient_token,
    t.encounter_token,
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

-- 원무 담당자가 넣은 환자 ID 를 토큰으로 바꾼다.
-- 워크플로가 에이전트 실행 "전에" 앱 자격증명으로 호출한다.
-- llm_reader 에게는 주지 않는다 — AI 는 환자 ID 를 알 일도, 넣을 일도 없다.
CREATE FUNCTION public.resolve_patient_token(p_patient_id text)
RETURNS text
LANGUAGE sql STABLE STRICT
AS $$
    SELECT patient_token FROM public.patient_master WHERE patient_id = p_patient_id
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA llm    FROM PUBLIC;
REVOKE ALL ON SCHEMA public               FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;

-- 빌드 게이트. 하나라도 어긋나면 이미지가 만들어지지 않는다.
-- 런타임 테스트만 두면 이미 나간 이미지를 확인할 뿐이다.
DO $$
DECLARE n int; s text;
BEGIN
    SELECT count(*) INTO n FROM public.patient_master;
    IF n <> 50 THEN RAISE EXCEPTION '게이트 A — 환자 50명이 아니다: %', n; END IF;

    SELECT count(*) INTO n FROM public.treatment_claim;
    IF n <> 50 THEN RAISE EXCEPTION '게이트 A — 진료 50건이 아니다: %', n; END IF;

    -- 식별 열이 뷰에 아예 없어야 한다. 가려진 게 아니라 부재여야 한다.
    SELECT count(*) INTO n FROM information_schema.columns
    WHERE table_schema = 'llm' AND column_name IN
        ('patient_id','patient_name','birth_date','mobile_phone',
         'resident_id_token','treatment_id','encounter_id');
    IF n > 0 THEN RAISE EXCEPTION '게이트 B — 식별 열이 뷰에 있다: %개', n; END IF;

    -- 같은 환자는 같은 토큰이어야 한다(이전 치료·치료 횟수 판단이 성립하려면).
    SELECT count(*) INTO n FROM (
        SELECT t.patient_id FROM public.treatment_claim t
        JOIN llm.claim v ON v.patient_token = t.patient_token
        GROUP BY t.patient_id HAVING count(DISTINCT v.patient_token) > 1) x;
    IF n > 0 THEN RAISE EXCEPTION '게이트 C — 같은 환자가 다른 토큰을 받았다: %건', n; END IF;

    -- 나이는 있고 생년월일은 없어야 한다.
    SELECT count(*) INTO n FROM llm.claim WHERE age IS NULL OR age < 0 OR age > 120;
    IF n > 0 THEN RAISE EXCEPTION '게이트 D — 나이가 이상한 행 %건', n; END IF;

    SELECT private.token('PT', 'P00001') INTO s;
    RAISE NOTICE '경계 게이트 통과 — 예시 토큰 %', s;
END $$;
