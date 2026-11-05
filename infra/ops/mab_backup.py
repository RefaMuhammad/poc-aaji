"""Backup dan pemulihan Platform MAB: database PostgreSQL + objek dokumen di S3/MinIO (U8).

Pemakaian (di image ops, lihat infra/docker/ops.Dockerfile):
    python mab_backup.py backup                      # buat backup baru, lalu hapus yang lewat masa simpan
    python mab_backup.py list                        # daftar backup
    python mab_backup.py restore latest --target-database-url ... [--target-bucket ...]
    python mab_backup.py verify <id> [--target-database-url ...] [--target-bucket ...]

Isi satu backup di bucket backup, prefix <BACKUP_PREFIX>/<id>/:
    db.dump         pg_dump format custom
    objects/<key>   salinan setiap objek dokumen
    manifest.json   sha256 dump, jumlah baris per tabel, sha256 dan ukuran setiap objek

Pemulihan selalu ke database KOSONG (database baru atau hasil DROP/CREATE), lalu diverifikasi:
jumlah baris per tabel dan sha256 setiap objek harus sama persis dengan manifest. Exit code 0 = cocok.

Lingkungan:
    DATABASE_URL, S3_ENDPOINT_URL, S3_BUCKET, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD, S3_REGION, S3_SSE, S3_KMS_KEY_ID
    BACKUP_BUCKET (bawaan mab-backups), BACKUP_PREFIX (bawaan backups), BACKUP_RETENTION_DAYS (bawaan 30)
    BACKUP_S3_ENDPOINT_URL / BACKUP_S3_ACCESS_KEY / BACKUP_S3_SECRET_KEY: bila bucket backup ada di lokasi lain
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

FORMAT_VERSION = 1


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


# --- Koneksi ---

def libpq(url: str) -> tuple[str, dict]:
    """URL SQLAlchemy -> (URI libpq tanpa password, env dengan PGPASSWORD). Password tidak muncul di argumen proses."""
    parts = urlsplit(url.replace("postgresql+psycopg://", "postgresql://", 1))
    env = dict(os.environ)
    netloc = parts.netloc
    if "@" in netloc:
        cred, host = netloc.rsplit("@", 1)
        user, _, password = cred.partition(":")
        if password:
            env["PGPASSWORD"] = unquote(password)
        netloc = f"{user}@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, "")), env


def run(cmd: list[str], env: dict, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, env=env, check=True, text=kw.pop("text", True), capture_output=True, **kw)


def s3_client(endpoint: str | None, key: str | None, secret: str | None):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3", endpoint_url=endpoint or None, aws_access_key_id=key or None, aws_secret_access_key=secret or None,
        region_name=os.environ.get("S3_REGION", "us-east-1"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 5}),
    )


def doc_s3():
    return s3_client(os.environ.get("S3_ENDPOINT_URL"), os.environ.get("MINIO_ROOT_USER"), os.environ.get("MINIO_ROOT_PASSWORD"))


def backup_s3():
    return s3_client(
        os.environ.get("BACKUP_S3_ENDPOINT_URL") or os.environ.get("S3_ENDPOINT_URL"),
        os.environ.get("BACKUP_S3_ACCESS_KEY") or os.environ.get("MINIO_ROOT_USER"),
        os.environ.get("BACKUP_S3_SECRET_KEY") or os.environ.get("MINIO_ROOT_PASSWORD"),
    )


def sse_args() -> dict:
    sse = os.environ.get("S3_SSE", "")
    if not sse:
        return {}
    args = {"ServerSideEncryption": sse}
    if sse == "aws:kms" and os.environ.get("S3_KMS_KEY_ID"):
        args["SSEKMSKeyId"] = os.environ["S3_KMS_KEY_ID"]
    return args


def ensure_bucket(client, bucket: str) -> None:
    existing = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
    if bucket not in existing:
        client.create_bucket(Bucket=bucket)
        sse = os.environ.get("S3_SSE", "")
        if sse:
            rule = {"SSEAlgorithm": sse}
            if sse == "aws:kms" and os.environ.get("S3_KMS_KEY_ID"):
                rule["KMSMasterKeyID"] = os.environ["S3_KMS_KEY_ID"]
            client.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={
                "Rules": [{"ApplyServerSideEncryptionByDefault": rule}]})


def list_keys(client, bucket: str, prefix: str = ""):
    token = None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        page = client.list_objects_v2(**kw)
        for obj in page.get("Contents", []):
            yield obj["Key"], obj["Size"]
        if not page.get("IsTruncated"):
            return
        token = page["NextContinuationToken"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- Database ---

def _count_sql(tables: list[str]):
    """SELECT 'nama', count(*) per tabel; nama tabel di-quote sebagai identifier dan literal."""
    from psycopg import sql

    return sql.SQL(" UNION ALL ").join(
        sql.SQL("SELECT {}, count(*) FROM {}").format(sql.Literal(t), sql.Identifier("public", t)) for t in tables)


def _tables(cur) -> list[str]:
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
    return [r[0] for r in cur.fetchall()]


def table_counts(db_url: str) -> dict[str, int]:
    import psycopg

    with psycopg.connect(db_url.replace("postgresql+psycopg://", "postgresql://", 1)) as conn, conn.cursor() as cur:
        tables = _tables(cur)
        if not tables:
            return {}
        cur.execute(_count_sql(tables))
        return {name: int(n) for name, n in cur.fetchall()}


def dump_consistent(db_url: str, dump: Path) -> dict[str, int]:
    """pg_dump dan hitungan baris dari snapshot yang sama, supaya cocok walau aplikasi tetap menulis selama backup."""
    import psycopg

    with psycopg.connect(db_url.replace("postgresql+psycopg://", "postgresql://", 1)) as conn:
        conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        with conn.cursor() as cur:
            cur.execute("SELECT pg_export_snapshot()")
            snapshot = cur.fetchone()[0]
            uri, env = libpq(db_url)
            run(["pg_dump", "--format=custom", "--no-owner", "--no-acl", f"--snapshot={snapshot}", "--file", str(dump), uri], env)
            tables = _tables(cur)
            counts = {}
            if tables:
                cur.execute(_count_sql(tables))
                counts = {name: int(n) for name, n in cur.fetchall()}
        conn.execute("COMMIT")
    return counts


# --- Perintah ---

def cmd_backup(args) -> int:
    db_url = os.environ["DATABASE_URL"]
    doc_bucket = os.environ.get("S3_BUCKET", "mab-documents")
    bucket = os.environ.get("BACKUP_BUCKET", "mab-backups")
    prefix = os.environ.get("BACKUP_PREFIX", "backups")
    backup_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{prefix}/{backup_id}"
    src, dst = doc_s3(), backup_s3()
    ensure_bucket(dst, bucket)

    with tempfile.TemporaryDirectory() as tmp:
        dump = Path(tmp) / "db.dump"
        log("pg_dump ...")
        counts = dump_consistent(db_url, dump)
        dump_sha = sha256_file(dump)
        dst.upload_file(str(dump), bucket, f"{base}/db.dump", ExtraArgs=sse_args())
        log(f"database: {dump.stat().st_size} byte, {len(counts)} tabel, {sum(counts.values())} baris")

    objects = []
    for key, size in list_keys(src, doc_bucket):
        body = src.get_object(Bucket=doc_bucket, Key=key)["Body"].read()
        dst.put_object(Bucket=bucket, Key=f"{base}/objects/{key}", Body=body, **sse_args())
        objects.append({"key": key, "size": size, "sha256": sha256(body)})
    log(f"objek dokumen: {len(objects)} file, {sum(o['size'] for o in objects)} byte")

    manifest = {
        "format": FORMAT_VERSION, "id": backup_id, "created_at": datetime.now(timezone.utc).isoformat(),
        "source_bucket": doc_bucket, "db_dump_sha256": dump_sha, "table_counts": counts, "objects": objects,
    }
    dst.put_object(Bucket=bucket, Key=f"{base}/manifest.json", Body=json.dumps(manifest, indent=1).encode(),
                   ContentType="application/json", **sse_args())
    log(f"backup selesai: {backup_id}")
    prune(dst, bucket, prefix, int(os.environ.get("BACKUP_RETENTION_DAYS", "30")))
    return 0


def backup_ids(client, bucket: str, prefix: str) -> list[str]:
    ids = set()
    for key, _ in list_keys(client, bucket, prefix + "/"):
        rest = key[len(prefix) + 1:]
        if rest.endswith("/manifest.json") and rest.count("/") == 1:
            ids.add(rest.split("/")[0])
    return sorted(ids)


def prune(client, bucket: str, prefix: str, days: int) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y%m%dT%H%M%SZ")
    ids = backup_ids(client, bucket, prefix)
    # Backup terbaru tidak pernah dihapus, berapa pun umurnya.
    for old in [i for i in ids[:-1] if i < cutoff]:
        keys = [k for k, _ in list_keys(client, bucket, f"{prefix}/{old}/")]
        for i in range(0, len(keys), 1000):
            client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]]})
        log(f"hapus backup lama (>{days} hari): {old}")


def resolve_id(client, bucket: str, prefix: str, wanted: str) -> str:
    ids = backup_ids(client, bucket, prefix)
    if not ids:
        raise SystemExit("Belum ada backup")
    if wanted == "latest":
        return ids[-1]
    if wanted not in ids:
        raise SystemExit(f"Backup {wanted} tidak ditemukan")
    return wanted


def load_manifest(client, bucket: str, prefix: str, backup_id: str) -> dict:
    return json.loads(client.get_object(Bucket=bucket, Key=f"{prefix}/{backup_id}/manifest.json")["Body"].read())


def cmd_list(args) -> int:
    client = backup_s3()
    bucket = os.environ.get("BACKUP_BUCKET", "mab-backups")
    prefix = os.environ.get("BACKUP_PREFIX", "backups")
    for bid in backup_ids(client, bucket, prefix):
        m = load_manifest(client, bucket, prefix, bid)
        print(f"{bid}  {sum(m['table_counts'].values()):>8} baris  {len(m['objects']):>6} objek")
    return 0


def cmd_restore(args) -> int:
    client = backup_s3()
    bucket = os.environ.get("BACKUP_BUCKET", "mab-backups")
    prefix = os.environ.get("BACKUP_PREFIX", "backups")
    backup_id = resolve_id(client, bucket, prefix, args.backup_id)
    manifest = load_manifest(client, bucket, prefix, backup_id)
    target_db = args.target_database_url
    target_bucket = args.target_bucket or manifest["source_bucket"]

    existing = table_counts(target_db)
    if existing and not args.allow_nonempty:
        raise SystemExit("Database tujuan tidak kosong. Pulihkan ke database baru (lihat runbook), "
                         "atau tambahkan --allow-nonempty bila memang disengaja.")

    with tempfile.TemporaryDirectory() as tmp:
        dump = Path(tmp) / "db.dump"
        client.download_file(bucket, f"{prefix}/{backup_id}/db.dump", str(dump))
        if sha256_file(dump) != manifest["db_dump_sha256"]:
            raise SystemExit("sha256 db.dump tidak cocok dengan manifest; backup rusak")
        uri, env = libpq(target_db)
        log(f"pg_restore {backup_id} ...")
        run(["pg_restore", "--no-owner", "--no-acl", "--exit-on-error", "--dbname", uri, str(dump)], env)

    dst = doc_s3()
    ensure_bucket(dst, target_bucket)
    for obj in manifest["objects"]:
        body = client.get_object(Bucket=bucket, Key=f"{prefix}/{backup_id}/objects/{obj['key']}")["Body"].read()
        dst.put_object(Bucket=target_bucket, Key=obj["key"], Body=body, **sse_args())
    log(f"objek dipulihkan: {len(manifest['objects'])} ke bucket {target_bucket}")
    return verify(manifest, target_db, target_bucket)


def verify(manifest: dict, target_db: str, target_bucket: str) -> int:
    counts = table_counts(target_db)
    diff_tables = {t: (n, counts.get(t)) for t, n in manifest["table_counts"].items() if counts.get(t) != n}
    dst = doc_s3()
    bad_objects = []
    for obj in manifest["objects"]:
        try:
            body = dst.get_object(Bucket=target_bucket, Key=obj["key"])["Body"].read()
            if sha256(body) != obj["sha256"]:
                bad_objects.append(obj["key"])
        except Exception:  # noqa: BLE001 - objek hilang juga dihitung tidak cocok
            bad_objects.append(obj["key"])
    report = {
        "backup_id": manifest["id"],
        "tables_checked": len(manifest["table_counts"]),
        "rows_expected": sum(manifest["table_counts"].values()),
        "rows_found": sum(counts.get(t, 0) for t in manifest["table_counts"]),
        "objects_checked": len(manifest["objects"]),
        "table_mismatches": diff_tables,
        "object_mismatches": bad_objects,
        "ok": not diff_tables and not bad_objects,
    }
    print(json.dumps(report, indent=1))
    log("VERIFIKASI COCOK" if report["ok"] else "VERIFIKASI GAGAL")
    return 0 if report["ok"] else 2


def cmd_verify(args) -> int:
    client = backup_s3()
    bucket = os.environ.get("BACKUP_BUCKET", "mab-backups")
    prefix = os.environ.get("BACKUP_PREFIX", "backups")
    manifest = load_manifest(client, bucket, prefix, resolve_id(client, bucket, prefix, args.backup_id))
    return verify(manifest, args.target_database_url or os.environ["DATABASE_URL"],
                  args.target_bucket or manifest["source_bucket"])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backup dan pemulihan Platform MAB")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backup").set_defaults(fn=cmd_backup)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    r = sub.add_parser("restore")
    r.add_argument("backup_id", help="id backup atau 'latest'")
    r.add_argument("--target-database-url", required=True)
    r.add_argument("--target-bucket")
    r.add_argument("--allow-nonempty", action="store_true")
    r.set_defaults(fn=cmd_restore)
    v = sub.add_parser("verify")
    v.add_argument("backup_id")
    v.add_argument("--target-database-url")
    v.add_argument("--target-bucket")
    v.set_defaults(fn=cmd_verify)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except subprocess.CalledProcessError as e:
        print(e.stderr, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
