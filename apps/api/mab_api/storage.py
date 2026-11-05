"""Penyimpanan file dokumen: MinIO/S3 (produksi) atau memori (tes)."""
from __future__ import annotations

from typing import Protocol


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...


class S3Storage:
    """MinIO atau S3 cloud.

    sse: "" (tanpa header), "AES256" (SSE-S3, MinIO dengan KMS bawaan), atau "aws:kms" (SSE-KMS dengan kms_key_id).
    Bucket baru juga diberi enkripsi bawaan, sehingga objek yang ditulis tanpa header tetap terenkripsi.
    endpoint_url kosong = endpoint S3 bawaan cloud (kredensial dari IAM/workload identity bila access_key kosong).
    """

    def __init__(self, endpoint_url: str | None, bucket: str, access_key: str | None, secret_key: str | None,
                 region: str = "us-east-1", sse: str = "", kms_key_id: str | None = None):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.sse = sse
        self.kms_key_id = kms_key_id
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self._bucket_ready = False

    @classmethod
    def from_settings(cls, s) -> "S3Storage":
        return cls(s.s3_endpoint_url, s.s3_bucket, s.minio_root_user, s.minio_root_password,
                   region=s.s3_region, sse=s.s3_sse, kms_key_id=s.s3_kms_key_id)

    def _sse_args(self) -> dict:
        if not self.sse:
            return {}
        args = {"ServerSideEncryption": self.sse}
        if self.sse == "aws:kms" and self.kms_key_id:
            args["SSEKMSKeyId"] = self.kms_key_id
        return args

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        existing = {b["Name"] for b in self.client.list_buckets().get("Buckets", [])}
        if self.bucket not in existing:
            self.client.create_bucket(Bucket=self.bucket)
            if self.sse:
                rule = {"SSEAlgorithm": self.sse}
                if self.sse == "aws:kms" and self.kms_key_id:
                    rule["KMSMasterKeyID"] = self.kms_key_id
                self.client.put_bucket_encryption(
                    Bucket=self.bucket,
                    ServerSideEncryptionConfiguration={"Rules": [{"ApplyServerSideEncryptionByDefault": rule}]},
                )
        self._bucket_ready = True

    def ping(self) -> None:
        self._ensure_bucket()
        self.client.head_bucket(Bucket=self.bucket)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._ensure_bucket()
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type, **self._sse_args())

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    def get(self, key: str) -> bytes:
        return self.objects[key][0]
