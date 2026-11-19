"""Short-lived in-process handoff of just-finalized uploads.

Direct upload finalization already downloads the PDF from private storage to
verify its size and page count. With the default inline task backend the analysis
job starts in the same process moments later; handing those bytes straight to the
pipeline avoids downloading the same object twice. The cache is strictly a
performance optimization: Celery/serverless workers simply miss it and read from
storage as before. Entries are bounded and expire quickly, so a lost job cannot
pin large files in memory.
"""
import threading
import time
from typing import Optional

_TTL_SECONDS = 5 * 60
_MAX_ENTRIES = 2
_cache: dict[str, tuple[float, bytes]] = {}
_lock = threading.Lock()


def stash(book_id: str, content: bytes) -> None:
    with _lock:
        now = time.monotonic()
        expired = [key for key, (stored_at, _) in _cache.items() if now - stored_at > _TTL_SECONDS]
        for key in expired:
            _cache.pop(key, None)
        while len(_cache) >= _MAX_ENTRIES:
            _cache.pop(next(iter(_cache)))
        _cache[book_id] = (now, content)


def take(book_id: str) -> Optional[bytes]:
    with _lock:
        entry = _cache.pop(book_id, None)
        if not entry:
            return None
        stored_at, content = entry
        if time.monotonic() - stored_at > _TTL_SECONDS:
            return None
        return content
