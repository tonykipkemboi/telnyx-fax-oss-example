from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

from app.config import Settings


class StorageBackend(Protocol):
    def save_pdf(self, *, storage_key: str, content: bytes) -> None: ...

    def exists(self, *, storage_key: str) -> bool: ...

    def delete(self, *, storage_key: str) -> bool: ...

    def public_url(self, *, storage_key: str, ttl_seconds: int) -> str: ...

    def local_path(self, *, storage_key: str) -> Path | None: ...


class LocalStorageBackend:
    def __init__(self, settings: Settings):
        self.uploads_path = settings.uploads_path
        self.base_url = settings.base_url.rstrip("/")
        self.app_secret_key = settings.app_secret_key

    def _path(self, storage_key: str) -> Path:
        return self.uploads_path / storage_key

    def _signature(self, *, storage_key: str, expires_at: int) -> str:
        payload = f"{storage_key}|{expires_at}".encode()
        return hmac.new(self.app_secret_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    def save_pdf(self, *, storage_key: str, content: bytes) -> None:
        self._path(storage_key).write_bytes(content)

    def exists(self, *, storage_key: str) -> bool:
        return self._path(storage_key).exists()

    def delete(self, *, storage_key: str) -> bool:
        path = self._path(storage_key)
        if not path.exists():
            return False
        path.unlink(missing_ok=True)
        return True

    def public_url(self, *, storage_key: str, ttl_seconds: int) -> str:
        expires_at = int((datetime.now(UTC) + timedelta(seconds=max(ttl_seconds, 1))).timestamp())
        sig = self._signature(storage_key=storage_key, expires_at=expires_at)
        query = urlencode({"exp": str(expires_at), "sig": sig})
        return f"{self.base_url}/v1/uploads/public/{storage_key}?{query}"

    def local_path(self, *, storage_key: str) -> Path | None:
        return self._path(storage_key)


class S3StorageBackend:
    def __init__(self, settings: Settings):
        try:
            import boto3
            from botocore.exceptions import ClientError
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError(
                "S3 backend requires boto3 and botocore. Install dependencies before enabling TELNYX_FAX_STORAGE_BACKEND=s3."
            ) from exc

        if not settings.s3_bucket:
            raise RuntimeError("TELNYX_FAX_S3_BUCKET is required when TELNYX_FAX_STORAGE_BACKEND=s3")

        self._boto3 = boto3
        self._client_error = ClientError
        self.bucket = settings.s3_bucket
        self.region = settings.s3_region
        self.endpoint_url = settings.s3_endpoint_url
        self.access_key_id = settings.s3_access_key_id
        self.secret_access_key = settings.s3_secret_access_key
        self.prefix = settings.s3_prefix.strip("/")
        self.public_base_url = settings.s3_public_base_url.rstrip("/") if settings.s3_public_base_url else None

        client_kwargs: dict[str, str] = {}
        if self.region:
            client_kwargs["region_name"] = self.region
        if self.endpoint_url:
            client_kwargs["endpoint_url"] = self.endpoint_url
        if self.access_key_id and self.secret_access_key:
            client_kwargs["aws_access_key_id"] = self.access_key_id
            client_kwargs["aws_secret_access_key"] = self.secret_access_key

        self.client = self._boto3.client("s3", **client_kwargs)

    def _object_key(self, storage_key: str) -> str:
        if self.prefix:
            return f"{self.prefix}/{storage_key}"
        return storage_key

    def save_pdf(self, *, storage_key: str, content: bytes) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._object_key(storage_key),
            Body=content,
            ContentType="application/pdf",
        )

    def exists(self, *, storage_key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._object_key(storage_key))
            return True
        except self._client_error:
            return False

    def delete(self, *, storage_key: str) -> bool:
        existed = self.exists(storage_key=storage_key)
        self.client.delete_object(Bucket=self.bucket, Key=self._object_key(storage_key))
        return existed

    def public_url(self, *, storage_key: str, ttl_seconds: int) -> str:
        object_key = self._object_key(storage_key)

        if self.public_base_url:
            return f"{self.public_base_url}/{object_key}"

        return self.client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self.bucket, "Key": object_key},
            ExpiresIn=ttl_seconds,
        )

    def local_path(self, *, storage_key: str) -> Path | None:
        del storage_key
        return None


def create_storage_backend(settings: Settings) -> StorageBackend:
    backend = settings.storage_backend_name
    if backend == "local":
        return LocalStorageBackend(settings)
    if backend == "s3":
        return S3StorageBackend(settings)

    raise RuntimeError(
        f"Unsupported storage backend '{settings.storage_backend}'. Use TELNYX_FAX_STORAGE_BACKEND=local or s3."
    )
