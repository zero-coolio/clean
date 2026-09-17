"""Shared pytest fixtures for CleanMedia tests."""
import pytest


# Every on-disk lookup cache the code persists, as
# (module attribute holding the path, module attribute holding the dict, temp
# filename). All four default to a path INSIDE the repo or the real user
# library, and all four are both read and written during a run, so a test
# inherits whatever a real clean run happened to cache and writes its own
# answers back. Listed rather than duplicated so a fifth cache is one line.
_PERSISTENT_CACHES = (
    ("src.tvmaze._CACHE_PATH", "src.tvmaze._cache", "tvmaze-name.json"),
    ("src.tvmaze._ID_CACHE_PATH", "src.tvmaze._id_cache", "tvmaze-id.json"),
    ("src.imdb._CACHE_PATH", "src.imdb._cache", "imdb.json"),
    (
        "src.service.clean_movie_service._TMDB_CACHE_PATH",
        "src.service.clean_movie_service._tmdb_cache",
        "tmdb.json",
    ),
)


@pytest.fixture(autouse=True)
def _isolate_lookup_caches(tmp_path, monkeypatch):
    """Give every persisted lookup cache a throwaway path and an empty dict.

    Two of these live at real user paths (the shared TVMaze episode cache is
    co-owned with the lime app); the rest sit next to their module inside the
    repo. Tests must neither read nor write any of them.

    Reading mattered as much as writing. src/.tvmaze_cache.json held 658 real
    entries including "letterkenny", so lookup_show returned a canonical name
    from a cache file rather than from anything the test set up, and four
    integration tests asserted a layout the service had stopped producing. See
    _offline_tvmaze below for the other half of that failure.

    Module-level paths are resolved at import time, so patch the attribute
    rather than an env var. The dicts are module state too: clearing them stops
    one test seeing an entry another test's run cached.
    """
    for path_attr, dict_attr, filename in _PERSISTENT_CACHES:
        monkeypatch.setattr(path_attr, tmp_path / filename, raising=False)
        monkeypatch.setattr(dict_attr, {}, raising=False)

    # The shared episode cache, normally at
    # ~/Library/Application Support/nulleffect/tvmaze-cache.json.
    monkeypatch.setattr(
        "src.tvmaze._SHARED_CACHE_PATH", tmp_path / "tvmaze-shared.json", raising=False
    )
    # Memoized in memory; reset so each test loads fresh from its own temp path.
    monkeypatch.setattr("src.tvmaze._episodes_cache", None, raising=False)
    # The once-per-process refresh guard is module state too; a key another test
    # already "refreshed" would silently suppress this test's re-fetch.
    monkeypatch.setattr("src.tvmaze._refreshed_keys", set(), raising=False)


@pytest.fixture(autouse=True)
def _offline_tvmaze(monkeypatch):
    """Keep tests hermetic: never reach the live TVMaze API.

    The fixture above isolates the caches; this one closes the socket. Without
    it, CleanService.run() canonicalized show names and backfilled episode
    titles from the real api.tvmaze.com on every integration test, so four of
    them asserted one layout while the service produced another:

        expected  Letterkenny/Season 05/Letterkenny.S05E01.mkv
        actual    Letterkenny (2016)/Season 05/
                      Letterkenny.(2016).S05E01.We.Don't.Fight.at.Weddings.mkv

    They had been red on main long enough to stop being read, and they would
    also have failed on a plane, or the day TVMaze reworded an episode title.

    Patched at the socket rather than at lookup_show/get_show_episodes on
    purpose: both call sites already catch Exception and degrade to empty, so
    this reproduces being offline exactly, and it cannot disturb the
    test_tvmaze_* modules, which stub the layer above and never reach urlopen.

    A test that WANTS show data stubs the call it needs, as
    test_tvmaze_collapse_renumber and test_tvmaze_titles already do.
    """
    def _no_network(*args, **kwargs):
        raise AssertionError(
            "test tried to reach the network via urllib; stub the lookup it "
            "needs instead (see tests/conftest.py::_offline_tvmaze)"
        )

    monkeypatch.setattr("urllib.request.urlopen", _no_network)


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
