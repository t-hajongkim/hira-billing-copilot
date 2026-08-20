# 데이터를 담은 Postgres 이미지 하나. 병원 안에서 이미 돌고 있는 DB 를 흉내 낸다.
#
# docker-entrypoint-initdb.d 를 쓴다 — 첫 기동 때 init.sql 이 돈다.
# init.sql 끝의 경계 게이트가 같이 돌아, 식별 열이 뷰에 새어 든 이미지는 만들어지지 않는다.
FROM postgres:17-alpine

COPY ["data/patient_master.csv",  "/data/patient_master.csv"]
COPY ["data/treatment_claim.csv", "/data/treatment_claim.csv"]
COPY ["init.sql",                 "/docker-entrypoint-initdb.d/01-init.sql"]

HEALTHCHECK --interval=5s --timeout=3s --retries=30 \
  CMD pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" || exit 1
