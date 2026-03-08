"""Tests for agent.file_lock — FileLock, locked_read_json, locked_write_json, locked_read_csv, locked_append_csv."""

import csv
import json
import os
import threading
import time
from pathlib import Path

import pytest

from agent.file_lock import (
    FileLock,
    locked_append_csv,
    locked_read_csv,
    locked_read_json,
    locked_write_json,
)


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory for test files."""
    return tmp_path


# ── FileLock basics ──────────────────────────────────────────────


class TestFileLock:
    def test_exclusive_lock_creates_lock_file(self, tmp_dir):
        data_file = tmp_dir / "data.json"
        data_file.write_text("{}")
        with FileLock(data_file, exclusive=True):
            lock_file = tmp_dir / "data.json.lock"
            assert lock_file.exists()

    def test_shared_lock_creates_lock_file(self, tmp_dir):
        data_file = tmp_dir / "data.json"
        data_file.write_text("{}")
        with FileLock(data_file, exclusive=False):
            lock_file = tmp_dir / "data.json.lock"
            assert lock_file.exists()

    def test_multiple_shared_locks_allowed(self, tmp_dir):
        data_file = tmp_dir / "data.json"
        data_file.write_text("{}")
        with FileLock(data_file, exclusive=False):
            # A second shared lock should succeed immediately
            with FileLock(data_file, exclusive=False, timeout=1.0):
                pass  # Both locks held simultaneously

    def test_exclusive_blocks_exclusive(self, tmp_dir):
        data_file = tmp_dir / "data.json"
        data_file.write_text("{}")
        results = []

        def hold_lock():
            with FileLock(data_file, exclusive=True):
                results.append("first_acquired")
                time.sleep(0.3)
                results.append("first_released")

        t = threading.Thread(target=hold_lock)
        t.start()
        time.sleep(0.05)  # Let the thread acquire the lock

        # This should block until the first lock is released
        with FileLock(data_file, exclusive=True, timeout=2.0):
            results.append("second_acquired")

        t.join()
        assert "first_acquired" in results
        assert "first_released" in results
        assert "second_acquired" in results
        # Second should acquire after first releases
        assert results.index("first_released") < results.index("second_acquired")

    def test_timeout_raises(self, tmp_dir):
        data_file = tmp_dir / "data.json"
        data_file.write_text("{}")

        def hold_lock():
            with FileLock(data_file, exclusive=True):
                time.sleep(1.0)

        t = threading.Thread(target=hold_lock)
        t.start()
        time.sleep(0.05)

        with pytest.raises(TimeoutError):
            with FileLock(data_file, exclusive=True, timeout=0.2):
                pass

        t.join()

    def test_lock_path_is_separate_file(self, tmp_dir):
        data_file = tmp_dir / "data.json"
        lock = FileLock(data_file, exclusive=True)
        assert lock.lock_path == tmp_dir / "data.json.lock"

    def test_creates_parent_dirs(self, tmp_dir):
        nested = tmp_dir / "a" / "b" / "data.json"
        with FileLock(nested, exclusive=True):
            assert nested.parent.exists()


# ── locked_read_json / locked_write_json ─────────────────────────


class TestLockedJson:
    def test_write_then_read(self, tmp_dir):
        path = tmp_dir / "test.json"
        data = {"key": "value", "number": 42}
        locked_write_json(path, data)
        result = locked_read_json(path)
        assert result == data

    def test_read_nonexistent_returns_default(self, tmp_dir):
        path = tmp_dir / "missing.json"
        assert locked_read_json(path) is None
        assert locked_read_json(path, default={}) == {}
        assert locked_read_json(path, default=[]) == []

    def test_read_invalid_json_returns_default(self, tmp_dir):
        path = tmp_dir / "bad.json"
        path.write_text("not valid json{{{")
        assert locked_read_json(path, default={"fallback": True}) == {"fallback": True}

    def test_write_creates_parent_dirs(self, tmp_dir):
        path = tmp_dir / "sub" / "dir" / "data.json"
        locked_write_json(path, {"created": True})
        assert path.exists()
        assert locked_read_json(path) == {"created": True}

    def test_write_is_atomic(self, tmp_dir):
        """Verify no .tmp files left behind after write."""
        path = tmp_dir / "atomic.json"
        locked_write_json(path, {"step": 1})
        tmp_files = list(tmp_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_concurrent_writes(self, tmp_dir):
        """Multiple threads writing should not corrupt the file."""
        path = tmp_dir / "concurrent.json"
        errors = []

        def writer(n):
            try:
                for i in range(10):
                    locked_write_json(path, {"writer": n, "iteration": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # File should be valid JSON
        result = locked_read_json(path)
        assert isinstance(result, dict)
        assert "writer" in result

    def test_write_with_default_serializer(self, tmp_dir):
        """Test that default=str handles non-serializable types."""
        from datetime import datetime

        path = tmp_dir / "datetime.json"
        locked_write_json(path, {"ts": datetime(2024, 1, 1)})
        result = locked_read_json(path)
        assert "2024" in result["ts"]


# ── locked_read_csv / locked_append_csv ──────────────────────────


class TestLockedCsv:
    def test_append_then_read(self, tmp_dir):
        path = tmp_dir / "trades.csv"
        fieldnames = ["id", "ticker", "pnl"]
        locked_append_csv(path, {"id": "1", "ticker": "AAPL", "pnl": "10.5"}, fieldnames)
        locked_append_csv(path, {"id": "2", "ticker": "MSFT", "pnl": "-3.2"}, fieldnames)

        rows = locked_read_csv(path)
        assert len(rows) == 2
        assert rows[0]["ticker"] == "AAPL"
        assert rows[1]["pnl"] == "-3.2"

    def test_read_nonexistent_returns_empty(self, tmp_dir):
        path = tmp_dir / "missing.csv"
        assert locked_read_csv(path) == []

    def test_append_creates_header(self, tmp_dir):
        path = tmp_dir / "new.csv"
        fieldnames = ["a", "b", "c"]
        locked_append_csv(path, {"a": "1", "b": "2", "c": "3"}, fieldnames)

        with open(path) as f:
            first_line = f.readline().strip()
        assert first_line == "a,b,c"

    def test_concurrent_appends(self, tmp_dir):
        """Multiple threads appending should not lose rows."""
        path = tmp_dir / "concurrent.csv"
        fieldnames = ["id", "value"]
        errors = []
        num_threads = 4
        rows_per_thread = 10

        def appender(thread_id):
            try:
                for i in range(rows_per_thread):
                    locked_append_csv(
                        path,
                        {"id": f"{thread_id}-{i}", "value": str(thread_id * 100 + i)},
                        fieldnames,
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=appender, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        rows = locked_read_csv(path)
        assert len(rows) == num_threads * rows_per_thread

    def test_append_creates_parent_dirs(self, tmp_dir):
        path = tmp_dir / "sub" / "dir" / "data.csv"
        locked_append_csv(path, {"x": "1"}, ["x"])
        assert path.exists()
