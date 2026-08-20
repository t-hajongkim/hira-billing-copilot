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
