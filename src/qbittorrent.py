#!/usr/bin/env python3
"""qBittorrent Web API integration for the remove-before-rename policy.

Before CleanMedia renames a downloaded file it consults qBittorrent:

  * if a COMPLETED torrent owns the file, the torrent is removed from the
    client (the data is kept, ``deleteFiles=false``) so the move doesn't pull a
    seeded file out from under qBittorrent;
  * if an INCOMPLETE torrent owns the file, the file is flagged as a
    "possible zombie" and left untouched — you never rename a file that is
    still downloading;
  * if no torrent owns the file, the move proceeds as normal.

Only :class:`QbitClient` touches the network. The matching/decision logic
(:func:`find_torrent_for_path`, :func:`torrent_is_complete`,
:meth:`QbitReaper.decide`) is pure and unit-tested without a live client.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import requests

# Decision outcomes (internal).
REMOVED = "removed"   # a completed torrent was (or would be) removed; proceed
ZOMBIE = "zombie"     # an incomplete torrent owns this file; do NOT move
NONE = "none"         # no torrent owns this file; proceed with move


def torrent_is_complete(torrent: dict) -> bool:
    """True if the torrent has fully downloaded (safe to remove + move).

    "Complete" means the download finished — the chosen gate — not a ratio or
    seed-time goal. ``amount_left == 0`` is the definitive signal; we fall back
    to ``progress >= 1.0`` only if amount_left is missing/unparseable.
    """
    amount_left = torrent.get("amount_left")
    if amount_left is not None:
        try:
            return int(amount_left) == 0
        except (TypeError, ValueError):
            pass
    try:
        return float(torrent.get("progress", 0)) >= 1.0
    except (TypeError, ValueError):
        return False


def _norm(p: str | Path) -> str:
    """Normalize a path for comparison: realpath, no trailing separator."""
    return os.path.realpath(str(p)).rstrip(os.sep)


def find_torrent_for_path(torrents: Iterable[dict], path: str | Path) -> dict | None:
    """Return the torrent whose data owns ``path``, or ``None``.

    Matches on qBittorrent's ``content_path`` — the actual on-disk location of a
    torrent's data (the file itself for single-file torrents, the root folder
    for multi-file torrents). ``path`` matches when it equals that path or lives
    underneath it.
    """
    target = _norm(path)
    for t in torrents:
        cp = t.get("content_path")
        if not cp:
            continue
        cpn = _norm(cp)
        if target == cpn or target.startswith(cpn + os.sep):
            return t
    return None


class QbitClient:
    """Thin qBittorrent Web API (v2) client — the only networked component.

    Defaults assume the Web UI on localhost with "Bypass authentication for
    clients on localhost" enabled. If credentials are supplied, :meth:`login`
    authenticates and the session carries the cookie.
    """

    def __init__(self, host: str = "localhost", port: int = 8080,
                 username: str | None = None, password: str | None = None,
                 timeout: float = 5.0, logger=None) -> None:
        self._base = f"http://{host}:{port}/api/v2"
        self._timeout = timeout
        self._logger = logger
        self._session = requests.Session()
        self._username = username
        self._password = password

    def _log(self, level: str, msg: str, *args) -> None:
        if self._logger:
            getattr(self._logger, level)(msg, *args)

    def login(self) -> bool:
        """Authenticate if credentials were given. Returns True on success, or
        when no credentials are configured (localhost bypass)."""
        if not self._username:
            return True
        try:
            r = self._session.post(
                f"{self._base}/auth/login",
                data={"username": self._username, "password": self._password},
                headers={"Referer": self._base},
                timeout=self._timeout,
            )
            ok = r.status_code == 200 and r.text.strip() == "Ok."
            if not ok:
                self._log("warning", "qBittorrent login failed (HTTP %s)", r.status_code)
            return ok
        except requests.RequestException as e:
            self._log("warning", "qBittorrent login error: %s", e)
            return False

    def is_available(self) -> bool:
        """True if the Web API answers (used to decide whether to engage)."""
        try:
            r = self._session.get(f"{self._base}/app/version", timeout=self._timeout)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def fetch_torrents(self) -> list[dict]:
        """Return all torrents (one ``torrents/info`` call). Raises on error."""
        r = self._session.get(f"{self._base}/torrents/info", timeout=self._timeout)
        r.raise_for_status()
        return r.json()

    def delete_torrent(self, torrent_hash: str, delete_files: bool = False) -> bool:
        """Remove a torrent from qBittorrent. ``delete_files=False`` keeps the
        data on disk so it can be renamed. Returns True on success."""
        try:
            r = self._session.post(
                f"{self._base}/torrents/delete",
                data={
                    "hashes": torrent_hash,
                    "deleteFiles": "true" if delete_files else "false",
                },
                timeout=self._timeout,
            )
            ok = r.status_code == 200
            if not ok:
                self._log("warning", "qBittorrent delete failed (HTTP %s) for %s",
                          r.status_code, torrent_hash)
            return ok
        except requests.RequestException as e:
            self._log("warning", "qBittorrent delete error for %s: %s", torrent_hash, e)
            return False


class QbitReaper:
    """Per-run remove-before-rename policy engine.

    Built once per clean run (one ``torrents/info`` fetch for the whole run, not
    one call per file — the same memoization discipline as the TVMaze cache).
    Tracks which torrent hashes were already removed this run so a multi-file
    torrent is removed only once and its remaining files then move normally.
    """

    def __init__(self, client: QbitClient, torrents: list[dict], logger=None) -> None:
        self._client = client
        self._torrents = torrents
        self._logger = logger
        self._removed: set[str] = set()

    @classmethod
    def create(cls, *, enabled: bool, host: str, port: int,
               username: str | None, password: str | None,
               timeout: float, logger) -> "QbitReaper | None":
        """Build a reaper, or return ``None`` if integration is disabled or
        qBittorrent is unreachable. When ``None`` the caller proceeds with
        normal renames (and logs that seeded files may be moved unguarded)."""
        if not enabled:
            if logger:
                logger.info("qBittorrent integration disabled (QBIT_ENABLED=0)")
            return None
        client = QbitClient(host, port, username, password, timeout, logger)
        if not client.login() or not client.is_available():
            if logger:
                logger.warning(
                    "qBittorrent not reachable at %s:%s — proceeding WITHOUT torrent "
                    "removal (a seeded file may be moved out from under it)", host, port)
            return None
        try:
            torrents = client.fetch_torrents()
        except requests.RequestException as e:
            if logger:
                logger.warning("qBittorrent torrents/info failed: %s — proceeding "
                               "without removal", e)
            return None
        if logger:
            logger.info("qBittorrent: %d torrent(s) loaded for remove-before-rename",
                        len(torrents))
        return cls(client, torrents, logger)

    def decide(self, path) -> tuple[str, dict | None]:
        """Pure decision for ``path``: returns ``(outcome, torrent)``.

        No side effects — outcome is one of REMOVED / ZOMBIE / NONE. A torrent
        already removed earlier this run reads as NONE so its other files move.
        """
        t = find_torrent_for_path(self._torrents, path)
        if t is None:
            return NONE, None
        if t.get("hash") in self._removed:
            return NONE, t
        if torrent_is_complete(t):
            return REMOVED, t
        return ZOMBIE, t

    def clear_to_move(self, path, commit: bool, journal: list[dict]) -> tuple[bool, str | None]:
        """Apply the policy to a file about to be renamed.

        Returns ``(should_move, skip_reason)``. When ``should_move`` is False,
        ``skip_reason`` is a short tag for the UNEXPECTED report. Removing a
        completed torrent is a side effect that happens only when ``commit`` is
        True (dry-run just logs what it would do).
        """
        outcome, t = self.decide(path)
        if outcome == NONE:
            return True, None

        name = t.get("name", "?")
        h = t.get("hash", "?")

        if outcome == ZOMBIE:
            try:
                pct = float(t.get("progress", 0)) * 100.0
            except (TypeError, ValueError):
                pct = 0.0
            self._log("warning",
                      "POSSIBLE ZOMBIE: %s — torrent %r incomplete "
                      "(state=%s, %.1f%%); NOT renaming",
                      path, name, t.get("state", "?"), pct)
            return False, "possible zombie — torrent incomplete"

        # outcome == REMOVED
        if not commit:
            self._log("info", "DRY-RUN would remove completed torrent %r (%s) "
                      "before renaming %s", name, h, path)
            return True, None
        if self._client.delete_torrent(h, delete_files=False):
            self._removed.add(h)
            journal.append({"op": "qbit_remove", "hash": h, "name": name,
                            "delete_files": False})
            self._log("info", "REMOVED completed torrent %r (%s) from qBittorrent "
                      "(kept data) before renaming %s", name, h, path)
            return True, None
        # Removal failed — do NOT rename, or we'd leave qBittorrent pointing at a
        # moved file. Retry on the next run.
        self._log("error", "qBittorrent removal FAILED for torrent %r (%s); "
                  "NOT renaming %s this run", name, h, path)
        return False, "qBittorrent removal failed — not renamed"

    def _log(self, level: str, msg: str, *args) -> None:
        if self._logger:
            getattr(self._logger, level)(msg, *args)
