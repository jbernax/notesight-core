import io
import logging
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from app.config import settings

logger = logging.getLogger(__name__)


class StorageService(Protocol):
    """Protocol defining the uniform storage contract across local filesystem and S3/R2."""

    def save_file(self, key: str, file_obj: BinaryIO) -> str:
        """Stream a file-like object to storage and return its canonical storage key."""
        ...

    def save_bytes(self, key: str, data: bytes) -> str:
        """Persist raw bytes to storage and return its canonical storage key."""
        ...

    def read_bytes(self, key: str) -> bytes:
        """Read and return full byte content from storage."""
        ...

    def open_stream(self, key: str) -> Any:
        """Open a readable binary stream for the given storage key."""
        ...

    def delete_file(self, key: str) -> bool:
        """Remove a file from storage. Returns True if deleted, False if not found."""
        ...

    def exists(self, key: str) -> bool:
        """Check whether a storage key exists."""
        ...

    def get_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate a public or presigned download URL."""
        ...

    def get_local_path(self, key: str) -> Path:
        """Resolve or cache the file onto local disk for local tools requiring file paths."""
        ...


class ChunkedStream:
    """Wraps a chunk iterator, binary stream, or file object providing context-managed chunk streaming and read()."""

    def __init__(self, raw_stream: Any, close_func: Any = None, chunk_size: int = 65536) -> None:
        self.raw_stream = raw_stream
        self.close_func = close_func
        self.chunk_size = chunk_size

    def __iter__(self):
        try:
            if hasattr(self.raw_stream, "iter_chunks"):
                yield from self.raw_stream.iter_chunks(self.chunk_size)
            elif hasattr(self.raw_stream, "read"):
                while True:
                    chunk = self.raw_stream.read(self.chunk_size)
                    if not chunk:
                        break
                    yield chunk
            else:
                yield from self.raw_stream
        finally:
            self.close()

    def read(self, size: int = -1) -> bytes:
        if hasattr(self.raw_stream, "read"):
            return self.raw_stream.read(size)  # type: ignore[no-any-return]
        return b"".join(list(self))

    def close(self) -> None:
        if self.close_func:
            try:
                self.close_func()
            except Exception:
                pass
        elif hasattr(self.raw_stream, "close"):
            try:
                self.raw_stream.close()
            except Exception:
                pass

    def __enter__(self) -> "ChunkedStream":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


class LocalStorageService:
    """Storage service backed by the host filesystem."""

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = (root_dir or settings.STORAGE_DIR).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, key: str) -> Path:
        p = Path(key)
        if p.is_absolute():
            resolved = p.resolve()
            import tempfile
            temp_dir = Path(tempfile.gettempdir()).resolve()
            is_allowed = resolved.is_relative_to(self.root_dir) or resolved.is_relative_to(temp_dir)
            if not is_allowed:
                from app.services.audit_logger import log_security_event
                log_security_event("security.path_traversal_blocked", status="BLOCKED", details={"key": key})
                raise ValueError(f"Invalid path traversal attempt: {key}")
            return resolved

        clean_key = key.lstrip("/")
        target = (self.root_dir / clean_key).resolve()
        # Ensure relative path stays strictly within root_dir bounds (prevent directory traversal)
        try:
            if not target.is_relative_to(self.root_dir):
                from app.services.audit_logger import log_security_event
                log_security_event("security.path_traversal_blocked", status="BLOCKED", details={"key": key})
                raise ValueError(f"Invalid path traversal attempt: {key}")
        except AttributeError:
            import os
            if not str(target).startswith(str(self.root_dir) + os.sep) and target != self.root_dir:
                from app.services.audit_logger import log_security_event
                log_security_event("security.path_traversal_blocked", status="BLOCKED", details={"key": key})
                raise ValueError(f"Invalid path traversal attempt: {key}")
        return target

    def save_file(self, key: str, file_obj: BinaryIO) -> str:
        target_path = self._resolve_path(key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        chunk_size = 1024 * 1024
        with open(target_path, "wb") as buffer:
            while True:
                chunk = file_obj.read(chunk_size)
                if not chunk:
                    break
                buffer.write(chunk)
        return key

    def save_bytes(self, key: str, data: bytes) -> str:
        target_path = self._resolve_path(key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
        return key

    def read_bytes(self, key: str) -> bytes:
        target_path = self._resolve_path(key)
        if not target_path.is_file():
            raise FileNotFoundError(f"Storage file not found: {key}")
        return target_path.read_bytes()

    def open_stream(self, key: str) -> ChunkedStream:
        target_path = self._resolve_path(key)
        if not target_path.is_file():
            raise FileNotFoundError(f"Storage file not found: {key}")
        f = open(target_path, "rb")
        return ChunkedStream(f)

    def delete_file(self, key: str) -> bool:
        target_path = self._resolve_path(key)
        if target_path.is_file():
            target_path.unlink()
            return True
        return False

    def exists(self, key: str) -> bool:
        return self._resolve_path(key).is_file()

    def get_url(self, key: str, expires_in: int = 3600) -> str:
        clean_key = key.lstrip("/")
        return f"/api/storage/{clean_key}"

    def get_local_path(self, key: str) -> Path:
        return self._resolve_path(key)


class S3StorageService:
    """Storage service backed by Cloudflare R2, AWS S3, or MinIO via boto3."""

    def __init__(
        self,
        bucket_name: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        region_name: str = "auto",
        s3_client: Any = None,
    ) -> None:
        self.bucket_name = bucket_name
        self.endpoint_url = endpoint_url
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.region_name = region_name
        self._s3_client = s3_client

    @property
    def client(self) -> Any:
        if self._s3_client is None:
            import boto3
            self._s3_client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name=self.region_name,
            )
        return self._s3_client

    def _normalize_key(self, key: str) -> str:
        p = Path(key)
        if p.is_absolute():
            try:
                return str(p.relative_to(settings.STORAGE_DIR))
            except ValueError:
                return p.name
        return key.lstrip("/")

    def _cache_path(self, clean_key: str) -> Path:
        cache_dir = settings.STORAGE_DIR / "_s3_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / clean_key.replace("/", "_")

    def save_file(self, key: str, file_obj: BinaryIO) -> str:
        clean_key = self._normalize_key(key)
        self.client.upload_fileobj(file_obj, self.bucket_name, clean_key)
        cache_file = self._cache_path(clean_key)
        if cache_file.exists():
            try:
                cache_file.unlink()
            except Exception:
                pass
        return clean_key

    def save_bytes(self, key: str, data: bytes) -> str:
        clean_key = self._normalize_key(key)
        self.client.put_object(Bucket=self.bucket_name, Key=clean_key, Body=data)
        cache_file = self._cache_path(clean_key)
        try:
            cache_file.write_bytes(data)
        except Exception:
            pass
        return clean_key

    def read_bytes(self, key: str) -> bytes:
        clean_key = self._normalize_key(key)
        response = self.client.get_object(Bucket=self.bucket_name, Key=clean_key)
        return response["Body"].read()  # type: ignore[no-any-return]

    def open_stream(self, key: str) -> ChunkedStream:
        clean_key = self._normalize_key(key)
        response = self.client.get_object(Bucket=self.bucket_name, Key=clean_key)
        return ChunkedStream(response["Body"], chunk_size=65536)

    def delete_file(self, key: str) -> bool:
        clean_key = self._normalize_key(key)
        cache_file = self._cache_path(clean_key)
        if cache_file.exists():
            try:
                cache_file.unlink()
            except Exception:
                pass
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=clean_key)
            return True
        except Exception as exc:
            logger.warning("Failed to delete S3 object %s: %s", clean_key, exc)
            return False

    def exists(self, key: str) -> bool:
        clean_key = self._normalize_key(key)
        from botocore.exceptions import ClientError
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=clean_key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", 404):
                return False
            return False
        except Exception:
            return False

    def get_url(self, key: str, expires_in: int = 3600) -> str:
        clean_key = self._normalize_key(key)
        return self.client.generate_presigned_url(  # type: ignore[no-any-return]
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": clean_key},
            ExpiresIn=expires_in,
        )

    def get_local_path(self, key: str) -> Path:
        p = Path(key)
        if p.is_absolute() and p.is_file():
            return p
        clean_key = self._normalize_key(key)
        local_target = self._cache_path(clean_key)
        if not local_target.exists():
            data = self.read_bytes(clean_key)
            local_target.write_bytes(data)
        return local_target


class GCSStorageService:
    """Storage service backed by Google Cloud Storage (GCS)."""

    def __init__(
        self,
        bucket_name: str,
        project_id: str | None = None,
        credentials_file: str | None = None,
        gcs_client: Any = None,
    ) -> None:
        self.bucket_name = bucket_name
        self.project_id = project_id
        self.credentials_file = credentials_file
        self._client = gcs_client

    @property
    def client(self) -> Any:
        if self._client is None:
            from google.cloud import storage
            if self.credentials_file:
                self._client = storage.Client.from_service_account_json(
                    self.credentials_file,
                    project=self.project_id,
                )
            else:
                self._client = storage.Client(project=self.project_id)
        return self._client

    @property
    def bucket(self) -> Any:
        return self.client.bucket(self.bucket_name)

    def _normalize_key(self, key: str) -> str:
        p = Path(key)
        if p.is_absolute():
            try:
                return str(p.relative_to(settings.STORAGE_DIR))
            except ValueError:
                return p.name
        return key.lstrip("/")

    def _cache_path(self, clean_key: str) -> Path:
        cache_dir = settings.STORAGE_DIR / "_gcs_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / clean_key.replace("/", "_")

    def save_file(self, key: str, file_obj: BinaryIO) -> str:
        clean_key = self._normalize_key(key)
        blob = self.bucket.blob(clean_key)
        blob.upload_from_file(file_obj)
        cache_file = self._cache_path(clean_key)
        if cache_file.exists():
            try:
                cache_file.unlink()
            except Exception:
                pass
        return clean_key

    def save_bytes(self, key: str, data: bytes) -> str:
        clean_key = self._normalize_key(key)
        blob = self.bucket.blob(clean_key)
        blob.upload_from_string(data)
        cache_file = self._cache_path(clean_key)
        try:
            cache_file.write_bytes(data)
        except Exception:
            pass
        return clean_key

    def read_bytes(self, key: str) -> bytes:
        clean_key = self._normalize_key(key)
        blob = self.bucket.blob(clean_key)
        return blob.download_as_bytes()  # type: ignore[no-any-return]

    def open_stream(self, key: str) -> ChunkedStream:
        clean_key = self._normalize_key(key)
        blob = self.bucket.blob(clean_key)
        raw_stream = blob.open("rb")
        return ChunkedStream(raw_stream, chunk_size=65536)

    def delete_file(self, key: str) -> bool:
        clean_key = self._normalize_key(key)
        cache_file = self._cache_path(clean_key)
        if cache_file.exists():
            try:
                cache_file.unlink()
            except Exception:
                pass
        try:
            blob = self.bucket.blob(clean_key)
            blob.delete()
            return True
        except Exception as exc:
            logger.warning("Failed to delete GCS object %s: %s", clean_key, exc)
            return False

    def exists(self, key: str) -> bool:
        clean_key = self._normalize_key(key)
        try:
            blob = self.bucket.blob(clean_key)
            return bool(blob.exists())
        except Exception:
            return False

    def get_url(self, key: str, expires_in: int = 3600) -> str:
        import datetime
        clean_key = self._normalize_key(key)
        blob = self.bucket.blob(clean_key)
        try:
            return blob.generate_signed_url(  # type: ignore[no-any-return]
                version="v4",
                expiration=datetime.timedelta(seconds=expires_in),
                method="GET",
            )
        except Exception as exc:
            logger.warning("Could not generate signed URL for %s: %s", clean_key, exc)
            return f"https://storage.googleapis.com/{self.bucket_name}/{clean_key}"

    def get_local_path(self, key: str) -> Path:
        p = Path(key)
        if p.is_absolute() and p.is_file():
            return p
        clean_key = self._normalize_key(key)
        local_target = self._cache_path(clean_key)
        if not local_target.exists():
            data = self.read_bytes(clean_key)
            local_target.write_bytes(data)
        return local_target


_storage_instance: StorageService | None = None


def get_storage_service(force_refresh: bool = False) -> StorageService:
    """Factory returning the active StorageService instance configured for the application."""
    global _storage_instance
    backend = settings.STORAGE_BACKEND
    needs_refresh = (
        force_refresh
        or _storage_instance is None
        or (backend == "s3" and not isinstance(_storage_instance, S3StorageService))
        or (backend == "gcs" and not isinstance(_storage_instance, GCSStorageService))
        or (backend == "local" and not isinstance(_storage_instance, LocalStorageService))
    )
    if needs_refresh:
        if backend == "s3":
            _storage_instance = S3StorageService(
                bucket_name=settings.S3_BUCKET_NAME,
                endpoint_url=settings.S3_ENDPOINT_URL,
                access_key_id=settings.S3_ACCESS_KEY_ID,
                secret_access_key=settings.S3_SECRET_ACCESS_KEY,
                region_name=settings.S3_REGION_NAME,
            )
        elif backend == "gcs":
            _storage_instance = GCSStorageService(
                bucket_name=settings.GCS_BUCKET_NAME,
                project_id=settings.GCS_PROJECT_ID,
                credentials_file=settings.GOOGLE_APPLICATION_CREDENTIALS,
            )
        else:
            _storage_instance = LocalStorageService()
    assert _storage_instance is not None
    return _storage_instance
