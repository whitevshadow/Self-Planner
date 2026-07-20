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


def stat_audio(key: str) -> tuple[int, str]:
    """Return (size_bytes, content_type) for a stored object."""
    st = _client.stat_object(settings.minio_bucket, key)
    return st.size, st.content_type or "application/octet-stream"


def get_audio_stream(key: str, offset: int = 0, length: int = 0):
    """Ranged read for HTTP streaming. Returns a urllib3 HTTPResponse the caller
    must close + release_conn. length=0 reads to the end from offset."""
    return _client.get_object(settings.minio_bucket, key, offset=offset, length=length)


def delete_audio(key: str) -> None:
    _client.remove_object(settings.minio_bucket, key)
