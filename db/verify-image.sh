#!/usr/bin/env bash
# 이미지를 띄워 경계가 실제로 서는지 확인한다. GHCR 로 올리기 전에 돈다.
set -euo pipefail
IMAGE="${1:?사용: verify-image.sh <image>}"
PW="verify-only-$$"

CID=$(docker run -d -e POSTGRES_DB=billing -e POSTGRES_USER=billing \
        -e POSTGRES_PASSWORD=billing -e LLM_DB_PASSWORD="$PW" "$IMAGE")
trap 'docker rm -f "$CID" >/dev/null 2>&1 || true' EXIT

for _ in $(seq 1 60); do
    docker exec "$CID" pg_isready -h 127.0.0.1 -U billing -d billing >/dev/null 2>&1 && break
    sleep 1
done

q() { docker exec -e PGPASSWORD="$PW" "$CID" \
        psql -X -qAt -h 127.0.0.1 -U llm_reader -d billing -c "$1"; }
say() { printf '  %-40s %s\n' "$1" "$2"; }

fail=0
n=$(q 'SELECT count(*) FROM claim');           say "뷰가 조회된다" "$n 건";  [ "$n" -eq 50 ] || fail=1
n=$(q "SELECT count(*) FROM information_schema.columns WHERE table_schema='llm'
       AND column_name IN ('patient_id','patient_name','birth_date','mobile_phone',
                           'resident_id_token','treatment_id','encounter_id')")
say "식별 열이 뷰에 없다" "$n 개"; [ "$n" -eq 0 ] || fail=1

for probe in "SELECT patient_name FROM public.patient_master LIMIT 1" \
             "SELECT secret FROM private.masking_secret" \
             "SELECT private.token('PT','P00001')" \
             "SELECT public.resolve_patient_token('P00001')" \
             "CREATE TABLE probe(x int)"; do
    if q "$probe" >/dev/null 2>&1; then
        say "차단되어야 할 접근" "열려 있음: ${probe:0:40}"; fail=1
    fi
done
say "원본·비밀키·토큰계산·쓰기" "전부 거부됨"

[ "$fail" -eq 0 ] || { echo "::error::경계 위반 — 이미지를 내보내지 않는다."; exit 1; }
echo "경계 검사 통과"
