"""Cross-process file locking utility for safe concurrent JSON/CSV I/O.

Uses fcntl.flock() for Unix file locking with separate .lock files.
Supports both shared (read) and exclusive (write) locks.
Write helpers use atomic write (tempfile + os.replace) inside the lock.
"""

import csv
import fcntl
import json
import os
import tempfile
import time
from pathlib import Path


class FileLock:
    """Context manager for cross-process file locking using fcntl.flock().

    Acquires a lock on a separate .lock file (not the data file itself).
    Supports shared (read) and exclusive (write) locks with a timeout.

    Usage:
        with FileLock(Path("data.json"), exclusive=True, timeout=5):
            # safe to write data.json
            ...

        with FileLock(Path("data.json"), exclusive=False):
            # safe to read data.json (shared lock)
            ...
    """

    def __init__(self, path: Path | str, exclusive: bool = True, timeout: float = 5.0):
        self.path = Path(path)
        self.lock_path = self.path.parent / (self.path.name + ".lock")
        self.exclusive = exclusive
        self.timeout = timeout
        self._lock_fd = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_fd = open(self.lock_path, "w")

        lock_type = fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH
        deadline = time.monotonic() + self.timeout

        while True:
            try:
                fcntl.flock(self._lock_fd, lock_type | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    self._lock_fd.close()
                    self._lock_fd = None
                    raise TimeoutError(
                        f"Could not acquire {'exclusive' if self.exclusive else 'shared'} "
                        f"lock on {self.lock_path} within {self.timeout}s"
                    )
                time.sleep(0.05)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            finally:
                self._lock_fd.close()
                self._lock_fd = None
        return False


# ── Helper Functions ─────────────────────────────────────────────


def locked_read_json(path: Path | str, default=None):
    """Read a JSON file with a shared (read) lock.

    Returns the parsed JSON data, or `default` if the file does not exist
    or cannot be parsed.
    """
    path = Path(path)
    if not path.exists():
        return default

    with FileLock(path, exclusive=False):
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return default


def locked_write_json(path: Path | str, data, *, default=str):
    """Write JSON data atomically with an exclusive (write) lock.

    Uses tempfile + os.replace inside the lock to prevent corruption.
    The `default` parameter is passed to json.dump for serialization.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with FileLock(path, exclusive=True):
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2, default=default)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def locked_read_csv(path: Path | str) -> list[dict]:
    """Read a CSV file with a shared (read) lock.

    Returns a list of dicts (one per row via csv.DictReader),
    or an empty list if the file does not exist.
    """
    path = Path(path)
    if not path.exists():
        return []

    with FileLock(path, exclusive=False):
        with open(path) as f:
            return list(csv.DictReader(f))


def locked_append_csv(path: Path | str, row: dict, fieldnames: list[str]):
    """Append a single row to a CSV file with an exclusive (write) lock.

    If the file does not exist, a header row is written first.
    Uses atomic write: reads existing content, appends the row,
    and writes back via tempfile + os.replace.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with FileLock(path, exclusive=True):
        file_exists = path.exists()
        with open(path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
