#!/bin/sh
# 경계가 실제로 서 있는지 확인한다.
#
#   db/test-access.sh                     compose 로 띄운 DB 에 대해
#   db/test-access.sh <image>             이미지를 직접 띄워서 (GHCR 반출 전 검사)
set -eu

IMAGE="${1:-}"
PW="llm-readonly"

if [ -n "$IMAGE" ]; then
    CID=$(docker run -d -e POSTGRES_DB=billing -e POSTGRES_USER=billing \
            -e POSTGRES_PASSWORD=billing "$IMAGE")
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
       AND column_name IN ('patient_name','birth_date','mobile_phone',
                           'resident_id_token','treatment_id','encounter_id')")
say "식별 열이 뷰에 없다" "$n 개"; [ "$n" = 0 ] || fail=1

# patient_id 는 뷰에 있다 - 조회를 그 열로 걸어야 하기 때문이다.
# 대신 llm_reader 에게는 그 열만 권한이 없다. 그래서 SELECT * 도 막힌다.
n=$(q "SELECT has_column_privilege('llm_reader','llm.claim','patient_id','SELECT')::int")
say "환자 ID 열은 못 읽는다" "권한 $n"; [ "$n" = 0 ] || fail=1

# 원본 테이블·환자ID·전체열·쓰기 - 전부 막혀 있어야 한다.
for probe in "SELECT patient_name FROM public.patient_master LIMIT 1" \
             "SELECT patient_id FROM claim LIMIT 1" \
             "SELECT * FROM claim LIMIT 1" \
             "CREATE TABLE probe(x int)"; do
    if q "$probe" >/dev/null 2>&1; then
        say "차단되어야 할 접근" "열려 있음 - $probe"; fail=1
    fi
done
say "원본·환자ID·전체열·쓰기" "전부 거부됨"

[ "$fail" = 0 ] || { echo "::error::경계 위반"; exit 1; }
echo "llm_reader 는 환자 ID 없이 llm.claim 만 봅니다 - 경계 검사 통과"
