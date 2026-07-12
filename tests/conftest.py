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
    # The episode cache is memoized in memory; reset it so each test loads fresh
    # from its own temp path instead of reusing a prior test's in-memory copy.
    monkeypatch.setattr("src.tvmaze._episodes_cache", None, raising=False)


@pytest.fixture(autouse=True)
def _disable_qbittorrent(monkeypatch):
    """Keep tests hermetic: never reach the live qBittorrent Web API.

    BaseCleanService.run() now builds a qBittorrent reaper; without this it
    would try to connect to localhost:8080 on every test that calls run().
    _make_qbit_reaper reads src.config.QBIT_ENABLED at call time, so disabling
    the flag is enough. Tests for the policy itself use QbitReaper directly
    with a fake client (see test_qbittorrent.py).
    """
    monkeypatch.setattr("src.config.QBIT_ENABLED", False, raising=False)
