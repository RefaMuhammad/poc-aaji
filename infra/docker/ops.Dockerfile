# Image operasi (U8): backup dan pemulihan database + objek dokumen.
# Berbasis postgres:16-alpine supaya pg_dump/pg_restore sama versinya dengan server PostgreSQL 16.
FROM postgres:16-alpine

RUN apk add --no-cache python3 py3-boto3 py3-psycopg \
    && adduser -D -u 10001 -h /home/ops ops

WORKDIR /ops
COPY infra/ops/mab_backup.py /ops/mab_backup.py

USER 10001
ENTRYPOINT ["python3", "/ops/mab_backup.py"]
CMD ["list"]
