"""Keep only the last few days of clean's undo journals.

Every committed run writes `.<service>-journal-YYYYMMDD-HHMMSS.jsonl` into the
root it cleaned, and nothing ever removed them: by 2026-10-28 the intake root
held 4,800+ (most of them empty), and lime's library scans had to list them on
every pass. Steve's rule (2026-10-28): keep 3 days of undos.

Expired journals go to the Trash (send2trash), never a hard delete, so an
older undo can still be recovered from there. Their history is not lost
either: BackfillDownloaded already folded every journal's moves into the
shared cache's downloadedAt marks.

One small module on purpose: `expired_journals` is pure (names + clock in,
names out) and is what the tests pin; `prune_journals` is the thin I/O step
around it.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

_RE_STAMP = re.compile(r"^\.(?P<service>clean-[a-z]+)-journal-(?P<stamp>\d{8}-\d{6})\.jsonl$")


def journal_stamp(name: str, services: Iterable[str]) -> datetime | None:
    """The local time a journal was written, from its NAME (not mtime, which a
    copy or restore can change). None if `name` is not one of `services`' journals."""
    m = _RE_STAMP.match(name)
    if not m or m.group("service") not in set(services):
        return None
    try:
        return datetime.strptime(m.group("stamp"), "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def expired_journals(names: Iterable[str], services: Iterable[str],
                     now: datetime, keep_days: float) -> list[str]:
    """Names of `services`' journals written more than `keep_days` before `now`.

    Anything that is not a recognisable journal (other files, a malformed
    stamp, another service's journal) is never returned. `keep_days <= 0`
    means retention is off and nothing expires.
    """
    if keep_days <= 0:
        return []
    services = tuple(services)
    cutoff = now - timedelta(days=keep_days)
    out = []
    for name in names:
        stamp = journal_stamp(name, services)
        if stamp is not None and stamp < cutoff:
            out.append(name)
    return sorted(out)


def prune_journals(root: Path, services: Iterable[str], keep_days: float, commit: bool,
                   logger: logging.Logger, now: datetime | None = None) -> list[Path]:
    """Trash `services`' journals in `root` (top level only) older than `keep_days`.

    Dry run unless `commit`. Returns the journals it trashed (or would have).
    Never raises: retention is housekeeping and must not fail a clean run.
    """
    services = tuple(services)
    now = now or datetime.now()
    try:
        names = [p.name for p in root.iterdir() if p.is_file()]
    except OSError as e:
        logger.warning("Journal retention: cannot list %s: %s", root, e)
        return []
    total = sum(1 for n in names if journal_stamp(n, services) is not None)
    expired = [root / n for n in expired_journals(names, services, now, keep_days)]
    if not expired:
        logger.info("Journal retention: %d %s journal(s) in %s, none older than %g day(s)",
                    total, "/".join(services), root, keep_days)
        return []
    if not commit:
        logger.info("Journal retention (dry run): would trash %d of %d %s journal(s) older than %g day(s) in %s",
                    len(expired), total, "/".join(services), keep_days, root)
        for p in expired:
            logger.debug("Journal retention (dry run): would trash %s", p.name)
        return expired

    try:
        from send2trash import send2trash
    except ImportError:
        # No hard-delete fallback: an undo journal is not worth an
        # unrecoverable delete. Leave them and say so.
        logger.warning("Journal retention: send2trash not installed; keeping %d expired journal(s)", len(expired))
        return []
    trashed: list[Path] = []
    for p in expired:
        try:
            send2trash(str(p))
            trashed.append(p)
            logger.debug("Journal retention: trashed %s", p.name)
        except Exception as e:  # one bad file must not stop the rest
            logger.warning("Journal retention: could not trash %s: %s", p, e)
    logger.info("Journal retention: trashed %d of %d %s journal(s) older than %g day(s) in %s (%d failed)",
                len(trashed), total, "/".join(services), keep_days, root, len(expired) - len(trashed))
    return trashed
