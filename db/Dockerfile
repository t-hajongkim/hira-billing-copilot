# 데이터를 담은 Postgres 이미지 하나. 병원 안에서 이미 돌고 있는 DB 를 흉내 낸다.
#
# docker-entrypoint-initdb.d 를 쓴다 — 첫 기동 때 init.sql 이 돈다.
# init.sql 끝의 경계 게이트가 같이 돌아, 식별 열이 뷰에 새어 든 이미지는 만들어지지 않는다.
FROM postgres:17-alpine

COPY ["data/patient_master.csv",  "/data/patient_master.csv"]
COPY ["data/treatment_claim.csv", "/data/treatment_claim.csv"]
COPY ["init.sql",                 "/docker-entrypoint-initdb.d/01-init.sql"]

# 마스킹 비밀키를 빌드 때 한 번만 뽑아 박는다.
#
# 컨테이너 기동마다 뽑으면 같은 환자가 실행마다 다른 토큰을 받는다.
# 워크플로가 둘로 나뉘어 있어서 — intake 가 환자 ID 를 토큰으로 바꾸고,
# review 가 그 토큰으로 조회한다 — 토큰이 실행 간에 안정적이지 않으면
# 조회가 0건이 된다. 실제로 그렇게 됐다.
#
# 치환이 안 되면 여기서 빌드를 세운다. 조용히 넘어가면 런타임에 0건으로만 보인다.
RUN set -eu; \
    secret="$(od -An -tx1 -N32 /dev/urandom | tr -d '[:space:]')"; \
    test -n "$secret"; \
    sed -i "s/__MASKING_SECRET__/$secret/" /docker-entrypoint-initdb.d/01-init.sql; \
    if grep -q "__MASKING_SECRET__" /docker-entrypoint-initdb.d/01-init.sql; then \
        echo "마스킹 비밀키 치환 실패" >&2; exit 1; \
    fi

HEALTHCHECK --interval=5s --timeout=3s --retries=30 \
  CMD pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" || exit 1
