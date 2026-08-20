# 데이터를 담은 Postgres 이미지 하나. 병원 안에서 이미 돌고 있는 DB 를 흉내 낸다.
#
# docker-entrypoint-initdb.d 를 쓴다 — 첫 기동 때 01-init.sql 과 02-create-llm-role.sh 가
# 순서대로 돈다. 각 파일 끝의 게이트가 같이 돌아, 경계가 열린 채로는 준비되지 않는다.
FROM postgres:17-alpine

COPY ["data/patient_master.csv",  "/data/patient_master.csv"]
COPY ["data/treatment_claim.csv", "/data/treatment_claim.csv"]
COPY ["init.sql",                 "/docker-entrypoint-initdb.d/01-init.sql"]
# 역할과 권한은 컨테이너가 뜰 때 만든다. 비밀번호를 이미지에 박지 않으려는 것이다 —
# 이 이미지는 공개 패키지로 나간다.
COPY ["create-llm-role.sh",       "/docker-entrypoint-initdb.d/02-create-llm-role.sh"]
RUN chmod +x /docker-entrypoint-initdb.d/02-create-llm-role.sh

HEALTHCHECK --interval=5s --timeout=3s --retries=30 \
  CMD pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" || exit 1
