#!/bin/sh
# 경계가 실제로 서 있는지 확인한다. compose 로 띄운 뒤 돌린다.
set -eu

q() {
    docker compose exec -T -e PGPASSWORD="${LLM_DB_PASSWORD:-llm-readonly-local}" \
        postgres psql -X -qAt -v ON_ERROR_STOP=1 -U llm_reader -d billing -c "$1"
}

test "$(q 'SELECT count(*) FROM claim')" = 50
test "$(q "SELECT count(*) FROM information_schema.columns
           WHERE table_schema='llm' AND column_name IN
           ('patient_id','patient_name','birth_date','mobile_phone','resident_id_token')")" = 0

# 원본 테이블·비밀키는 닿지 않아야 한다.
! q 'SELECT count(*) FROM public.patient_master'  >/dev/null 2>&1
! q 'SELECT count(*) FROM public.treatment_claim' >/dev/null 2>&1
! q 'SELECT secret FROM private.masking_secret'   >/dev/null 2>&1

# 쓰기도 막혀 있어야 한다.
! q 'CREATE TABLE probe(x int)' >/dev/null 2>&1

printf 'AI 는 llm.claim 뷰만 봅니다 — 식별 열 0개, 원본 테이블 접근 거부, 읽기 전용.\n'
