"""MinIO upload/download/delete helpers."""
import io

from minio import Minio

from ..config import settings

_client = Minio(
    settings.minio_endpoint,
    access_key=settings.minio_access_key,
    secret_key=settings.minio_secret_key,
    secure=settings.minio_secure,
)


def ensure_bucket() -> None:
    if not _client.bucket_exists(settings.minio_bucket):
        _client.make_bucket(settings.minio_bucket)


def upload_audio(key: str, data: bytes, content_type: str) -> None:
    _client.put_object(
        settings.minio_bucket,
        key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


def download_audio(key: str, dest_path: str) -> None:
    _client.fget_object(settings.minio_bucket, key, dest_path)


def delete_audio(key: str) -> None:
    _client.remove_object(settings.minio_bucket, key)
