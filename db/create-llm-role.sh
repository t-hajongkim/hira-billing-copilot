#!/bin/sh
# AI 쪽이 쓸 읽기 역할을 컨테이너가 뜰 때 만든다.
#
# 비밀번호를 이미지에 박지 않는다. 이미지는 공개 패키지로 나가고, 박아 두면
# 그 값이 그대로 공개된다. 대신 실행할 때 시크릿으로 넣는다.
#
# 역할이 SQL 파일이 아니라 이 스크립트에 있는 이유도 그것이다 —
# .sql 은 환경변수를 못 읽는다.
set -eu

: "${LLM_DB_PASSWORD:?LLM_DB_PASSWORD 가 필요합니다 (저장소 시크릿으로 넣으세요)}"

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     --set=ON_ERROR_STOP=1 --set=llm_password="$LLM_DB_PASSWORD" <<'SQL'
CREATE ROLE llm_reader LOGIN PASSWORD :'llm_password';

REVOKE ALL ON SCHEMA public               FROM llm_reader;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM llm_reader;

GRANT USAGE ON SCHEMA llm TO llm_reader;

-- patient_id 만 빼고 준다. 열을 손으로 나열하면 열이 늘 때 빠뜨린다 —
-- 빠뜨리면 조용히 새는 쪽으로 틀린다. 그래서 뷰 정의에서 뽑아 쓴다.
DO $grant$
DECLARE cols text;
BEGIN
    SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position)
      INTO cols FROM information_schema.columns
     WHERE table_schema = 'llm' AND table_name = 'claim'
       AND column_name <> 'patient_id';
    EXECUTE format('GRANT SELECT (%s) ON llm.claim TO llm_reader', cols);
END $grant$;

ALTER ROLE llm_reader SET search_path = llm, pg_catalog;
ALTER ROLE llm_reader SET default_transaction_read_only = on;
ALTER ROLE llm_reader SET statement_timeout = '10s';

-- 권한 게이트. 어긋나면 컨테이너가 준비되지 않는다.
DO $gate$
BEGIN
    -- patient_id 는 뷰에 있다(조회 키). 대신 llm_reader 가 못 읽어야 한다.
    IF has_column_privilege('llm_reader', 'llm.claim', 'patient_id', 'SELECT') THEN
        RAISE EXCEPTION '게이트 C - llm_reader 가 환자 ID 를 읽을 수 있다';
    END IF;
    IF NOT has_column_privilege('llm_reader', 'llm.claim', 'age', 'SELECT') THEN
        RAISE EXCEPTION '게이트 C - llm_reader 가 진료 열을 못 읽는다';
    END IF;
    RAISE NOTICE '권한 게이트 통과 - 환자 ID 는 llm_reader 에게 닫혀 있다';
END $gate$;
SQL
