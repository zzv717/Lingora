"""File storage abstraction: local disk (default) or Supabase Storage (env-configured).

Uploaded books are PRIVATE — access always goes through authenticated, ownership-checked
API endpoints. Books are never served publicly.
"""
import logging
import os
import re
from abc import ABC, abstractmethod

from app.core.config import settings
from app.core.errors import ApiError

log = logging.getLogger("lingora.storage")


class StorageBackend(ABC):
    @abstractmethod
    def save(self, user_id: str, book_id: str, filename: str, content: bytes) -> str:
        """Persist the object and return a storage path/uri."""

    @abstractmethod
    def read(self, storage_path: str) -> bytes:
        """Read the object (only called after ownership checks)."""

    @abstractmethod
    def delete(self, storage_path: str) -> None:
        """Delete the object if it exists. Must raise if deletion failed so callers do not assume success."""


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class LocalStorage(StorageBackend):
    def _path(self, storage_path: str) -> str:
        base = os.path.abspath(settings.storage_dir)
        full = os.path.abspath(os.path.join(base, storage_path))
        if not full.startswith(base + os.sep):  # anti path-traversal
            raise ApiError("STORAGE_ERROR", "Fayl yo'li noto'g'ri.", 400)
        return full

    def save(self, user_id: str, book_id: str, filename: str, content: bytes) -> str:
        safe_name = _SAFE_NAME.sub("_", os.path.basename(filename))[:120] or "book.pdf"
        rel = os.path.join("books", user_id, book_id, safe_name)
        full = self._path(rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(content)
        return rel

    def read(self, storage_path: str) -> bytes:
        full = self._path(storage_path)
        if not os.path.exists(full):
            raise ApiError("FILE_NOT_FOUND", "Fayl topilmadi.", 404)
        with open(full, "rb") as f:
            return f.read()

    def delete(self, storage_path: str) -> None:
        full = self._path(storage_path)
        if os.path.exists(full):
            try:
                os.remove(full)
            except Exception as e:
                log.error("Failed to delete local storage file: %s", type(e).__name__)
                raise ApiError("STORAGE_DELETE_FAILED", "Faylni xotiradan o'chirishda xatolik yuz berdi.", 500)
        # clean up empty dirs up to storage root
        d = os.path.dirname(full)
        base = os.path.abspath(settings.storage_dir)
        while d.startswith(base + os.sep) and d != base:
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)


class SupabaseStorage(StorageBackend):
    """Private-bucket object storage via Supabase Storage REST API (service key on server only)."""

    def __init__(self):
        if not (settings.supabase_url and settings.supabase_service_key):
            raise ApiError(
                "STORAGE_MISCONFIGURED",
                "Supabase Storage tanlangan, lekin SUPABASE_URL / SUPABASE_SERVICE_KEY sozlanmagan.",
                500,
            )
        self.base = f"{settings.supabase_url.rstrip('/')}/storage/v1"
        self.bucket = settings.supabase_storage_bucket
        self.headers = {
            "Authorization": f"Bearer {settings.supabase_service_key}",
            "apikey": settings.supabase_service_key,
        }

    def _object_path(self, storage_path: str) -> str:
        return f"{self.base}/object/{self.bucket}/{storage_path}"

    def save(self, user_id: str, book_id: str, filename: str, content: bytes) -> str:
        import httpx

        safe_name = _SAFE_NAME.sub("_", os.path.basename(filename))[:120] or "book.pdf"
        rel = f"books/{user_id}/{book_id}/{safe_name}"
        resp = httpx.post(
            f"{self.base}/object/{self.bucket}/{rel}",
            headers={**self.headers, "content-type": "application/pdf", "x-upsert": "true"},
            content=content,
            timeout=120,
        )
        if resp.status_code not in (200, 201):
            log.error("Supabase storage save failed with status %d", resp.status_code)
            raise ApiError("STORAGE_ERROR", f"Fayl saqlanmadi (Supabase {resp.status_code}).", 500)
        return rel

    def read(self, storage_path: str) -> bytes:
        import httpx

        resp = httpx.get(self._object_path(storage_path), headers=self.headers, timeout=120)
        if resp.status_code != 200:
            raise ApiError("FILE_NOT_FOUND", "Fayl topilmadi.", 404)
        return resp.content

    def delete(self, storage_path: str) -> None:
        import httpx

        try:
            resp = httpx.delete(
                f"{self.base}/object/{self.bucket}",
                headers=self.headers,
                json={"prefixes": [storage_path]},
                timeout=60,
            )
            if resp.status_code not in (200, 204):
                log.error("Supabase storage delete failed with status %d", resp.status_code)
                raise ApiError("STORAGE_DELETE_FAILED", "Bulutli xotiradan faylni o'chirish muvaffaqiyatsiz bo'ldi.", 500)
        except ApiError:
            raise
        except Exception as e:
            log.error("Supabase storage delete network error: %s", type(e).__name__)
            raise ApiError("STORAGE_DELETE_FAILED", "Faylni o'chirishda xatolik yuz berdi.", 500)


def get_storage() -> StorageBackend:
    if settings.storage_backend == "supabase":
        return SupabaseStorage()
    return LocalStorage()
