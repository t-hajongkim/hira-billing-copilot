#!/bin/sh
# 경계가 실제로 서 있는지 확인한다.
#
#   db/test-access.sh                     compose 로 띄운 DB 에 대해
#   db/test-access.sh <image>             이미지를 직접 띄워서 (GHCR 반출 전 검사)
set -eu

IMAGE="${1:-}"
PW="${LLM_DB_PASSWORD:-llm-readonly-local}"

if [ -n "$IMAGE" ]; then
    PW="verify-$$"
    CID=$(docker run -d -e POSTGRES_DB=billing -e POSTGRES_USER=billing \
            -e POSTGRES_PASSWORD=billing -e LLM_DB_PASSWORD="$PW" "$IMAGE")
    trap 'docker rm -f "$CID" >/dev/null 2>&1 || true' EXIT
    i=0; while [ $i -lt 60 ]; do
        docker exec "$CID" pg_isready -h 127.0.0.1 -U billing -d billing >/dev/null 2>&1 && break
        i=$((i+1)); sleep 1
    done
    q() { docker exec -e PGPASSWORD="$PW" "$CID" \
            psql -X -qAt -h 127.0.0.1 -U llm_reader -d billing -c "$1"; }
else
    q() { docker compose exec -T -e PGPASSWORD="$PW" \
            postgres psql -X -qAt -h 127.0.0.1 -U llm_reader -d billing -c "$1"; }
fi

say() { printf '  %-38s %s\n' "$1" "$2"; }
fail=0

n=$(q 'SELECT count(*) FROM claim')
say "뷰가 조회된다" "$n 건"; [ "$n" = 50 ] || fail=1

n=$(q "SELECT count(*) FROM information_schema.columns WHERE table_schema='llm'
       AND column_name IN ('patient_id','patient_name','birth_date','mobile_phone',
                           'resident_id_token','treatment_id','encounter_id')")
say "식별 열이 뷰에 없다" "$n 개"; [ "$n" = 0 ] || fail=1

# 원본·비밀키·토큰계산·환자ID해석·쓰기 — 전부 막혀 있어야 한다.
for probe in "SELECT patient_name FROM public.patient_master LIMIT 1" \
             "SELECT secret FROM private.masking_secret" \
             "SELECT private.token('PT','P00001')" \
             "SELECT public.resolve_patient_token('P00001')" \
             "CREATE TABLE probe(x int)"; do
    if q "$probe" >/dev/null 2>&1; then
        say "차단되어야 할 접근" "열려 있음 — $probe"; fail=1
    fi
done
say "원본·비밀키·토큰계산·쓰기" "전부 거부됨"

[ "$fail" = 0 ] || { echo "::error::경계 위반"; exit 1; }
echo "AI 는 llm.claim 뷰만 봅니다 — 경계 검사 통과"
