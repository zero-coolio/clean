"""Shared pytest fixtures for CleanMedia tests."""
import pytest


@pytest.fixture(autouse=True)
def _isolate_shared_tvmaze_cache(tmp_path, monkeypatch):
    """Redirect the shared TVMaze episode cache to a per-test temp file.

    The shared cache normally lives at a real user path
    (~/Library/Application Support/nulleffect/tvmaze-cache.json), co-owned with
    the lime app. Tests must never read or write that real file, so every test
    gets its own throwaway path. The module-level _SHARED_CACHE_PATH is resolved
    at import time, so we patch the attribute directly rather than the env var.
    """
    cache_file = tmp_path / "tvmaze-cache.json"
    monkeypatch.setattr("src.tvmaze._SHARED_CACHE_PATH", cache_file, raising=False)
