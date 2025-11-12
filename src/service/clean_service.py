#!/usr/bin/env python3
from __future__ import annotations
import os
import re
import sys
import json
import hashlib
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List

LOGGER = logging.getLogger("clean-tv")
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
if not LOGGER.handlers:
    LOGGER.addHandler(handler)
else:
    # replace existing handlers with our formatter
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)

VIDEO_EXT = {".mkv", ".mp4", ".avi", ".mov"}
SIDECAR_EXT = {".srt", ".sub", ".idx", ".nfo", ".jpg", ".jpeg", ".png", ".txt"}
AUX_DELETE = {".ds_store"}
SAMPLE_PREFIXES = ("sample", "proof", "trailer")

# ---------------------------------------------------------------------
# Prefix scrubbing for indexer/wrapper folders and tags
# ---------------------------------------------------------------------
NOISE_PREFIX_PATTERNS = [
    r"^www\.UIndex\.org\s*-\s*",                # matches "www.UIndex.org - " and "www.UIndex.org    -    "
    r"^\[?(?:tgx|rartv|rarbg|eztv|yts|eztv\.re)\]?\s*",  # [TGx], [RARBG], etc.
    r"^www\.",                                  # generic www.
]

def strip_noise_prefix(name: str) -> str:
    s = name.strip()
    s = re.sub(r"\s{2,}", " ", s)
    for pat in NOISE_PREFIX_PATTERNS:
        s = re.sub(pat, "", s, flags=re.IGNORECASE)
    return s.lstrip()

# Reusable episode patterns
RE_SxxEyy = re.compile(
    r"^(?P<show>.*?)[\.\s\-_]*S(?P<season>\d{1,2})[\.\s\-_]*E(?P<episode>\d{1,2})",
    re.IGNORECASE
)
RE_X = re.compile(
    r"^(?P<show>.*?)[\.\s\-_]*(?P<season>\d{1,2})[xX](?P<episode>\d{1,2})",
    re.IGNORECASE
)

def parse_episode_from_string(s: str) -> Optional[Tuple[str, str, str]]:
    name = strip_noise_prefix(s)
    m = RE_SxxEyy.search(name) or RE_X.search(name)
    if not m:
        return None
    raw_show = m.group("show")
    season, episode = m.group("season"), m.group("episode")
    show = re.sub(r"[\._\-]+", " ", raw_show).strip()
    show = re.sub(r"\s+", " ", show)
    return show, season.zfill(2), episode.zfill(2)


class CleanService:
    """Service that organizes TV media safely with undo journaling."""

    # ---------------- Parsing ----------------
    @staticmethod
    def parse_tv_filename(filename: str) -> Optional[Tuple[str, str, str]]:
        """
        Strict episode parsing (no fused digits):
          - Show.Name.S01E02
          - Show Name S01 E02  (space/dot/underscore/dash allowed between S and E)
          - Show Name 3x01 / 3X01
        """
        return parse_episode_from_string(Path(filename).stem)

    def parse_from_parent_dir(self, path: Path) -> Optional[Tuple[str, str, str]]:
        """Fallback: parse explicit episode from the immediate parent directory name."""
        return parse_episode_from_string(path.parent.name)

    # ---------------- Helpers ----------------
    @staticmethod
    def sha1sum(path: Path, limit_bytes: int = 1024 * 1024) -> str:
        h = hashlib.sha1()
        with path.open("rb") as f:
            chunk = f.read(limit_bytes)
            h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def ensure_dir(p: Path, commit: bool):
        if commit:
            p.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def case_insensitive_child(parent: Path, name: str) -> Path:
        try:
            for entry in parent.iterdir():
                if entry.name.lower() == name.lower():
                    return entry
        except FileNotFoundError:
            pass
        return parent / name

    @staticmethod
    def unique_path(p: Path) -> Path:
        if not p.exists():
            return p
        base, ext = p.stem, p.suffix
        i = 1
        while True:
            alt = p.with_name(f"{base} (alt{'' if i==1 else f' {i}'}){ext}")
            if not alt.exists():
                return alt
            i += 1

    @staticmethod
    def unique_dir_path(p: Path) -> Path:
        if not p.exists():
            return p
        i = 1
        while True:
            alt = p.parent / f"{p.name} (alt{'' if i==1 else f' {i}'})"
            if not alt.exists():
                return alt
            i += 1

    @staticmethod
    def same_path(a: Path, b: Path) -> bool:
        try:
            return a.resolve() == b.resolve()
        except Exception:
            return str(a.absolute()) == str(b.absolute())

    @staticmethod
    def safe_move(src: Path, dst: Path, commit: bool, journal: List[dict]):
        if dst.exists():
            raise FileExistsError(f"Destination exists: {dst}")
        if not commit:
            return
        try:
            os.rename(src, dst)
        except OSError:
            with src.open("rb") as rf, dst.open("wb") as wf:
                shutil.copyfileobj(rf, wf)
                wf.flush()
                os.fsync(wf.fileno())
            os.unlink(src)
        journal.append({"op": "move", "src": str(src), "dst": str(dst)})

    @staticmethod
    def safe_move_dir(src: Path, dst: Path, commit: bool, journal: List[dict]):
        """Move a directory tree; record as 'move_dir' in journal."""
        if dst.exists():
            raise FileExistsError(f"Destination directory exists: {dst}")
        if not commit:
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        journal.append({"op": "move_dir", "src": str(src), "dst": str(dst)})

    @staticmethod
    def safe_delete(path: Path, commit: bool, journal: List[dict]):
        if not commit:
            return
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink(missing_ok=True)
        journal.append({"op": "delete", "path": str(path)})

    def same_content(self, a: Path, b: Path) -> bool:
        try:
            return (a.stat().st_size == b.stat().st_size) and (self.sha1sum(a) == self.sha1sum(b))
        except Exception:
            return False

    # ---------------- Undo ----------------
    def undo_from_journal(self, journal_path: Path):
        entries = [
            json.loads(line)
            for line in journal_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for entry in reversed(entries):
            op = entry.get("op")
            if op == "move":
                src, dst = Path(entry["src"]), Path(entry["dst"])
                if dst.exists() and not src.exists():
                    os.rename(dst, src)
                    LOGGER.info(f"UNDO MOVE: {dst} -> {src}")
            elif op == "move_dir":
                src, dst = Path(entry["src"]), Path(entry["dst"])
                if dst.exists() and not src.exists():
                    shutil.move(str(dst), str(src))
                    LOGGER.info(f"UNDO MOVE_DIR: {dst} -> {src}")
            elif op == "delete":
                LOGGER.warning(f"UNDO DELETE not supported automatically: {entry['path']}")

    # ---------------- Core path builders ----------------
    def resolve_show_season_dirs(self, intake_root: Path, show: str, season: str) -> Path:
        show_dir = self.case_insensitive_child(intake_root, show)
        season_dir_name = f"Season {season}"
        season_dir = self.case_insensitive_child(show_dir, season_dir_name)
        return season_dir

    def build_dest(self, intake_root: Path, show: str, season: str, episode: str, ext: str) -> Path:
        dest_dir = self.resolve_show_season_dirs(intake_root, show, season)
        dest_name = f"{show} S{season}E{episode}{ext}"
        return dest_dir / dest_name

    def build_sidecar_target(self, intake_root: Path, show: str, season: str, episode: str, sidecar_name: str) -> Path:
        dest_dir = self.resolve_show_season_dirs(intake_root, show, season)
        src = Path(sidecar_name)
        base = src.stem
        extra = sidecar_name[len(base):]  # preserves multi-part suffix like .en.srt
        base_norm = f"{show} S{season}E{episode}"
        dest_name = base_norm + extra
        return dest_dir / dest_name

    # ---------- Season-pack folder normalization (Sxx without Eyy) ----------
    SEASON_PACK_DIR_RE = re.compile(
        r"^(?P<show>.*?)[\.\s\-_]*S(?P<season>\d{1,2})\b(?!.*E\d{1,2})",
        re.IGNORECASE
    )

    def normalize_season_pack_dirs(self, root: Path, commit: bool, journal: List[dict]):
        """
        Detect directories named like 'Show S03 (2025) 1080p ...' (no E##) and move the ENTIRE DIRECTORY
        to 'Show/Season 03/' before file processing (keeps contents together).
        Also strip known indexer prefixes from folder names while detecting.
        """
        candidates: List[Path] = []
        for dirpath, dirnames, _ in os.walk(root):
            base = Path(dirpath)
            for d in dirnames:
                cleaned = strip_noise_prefix(d)
                m = self.SEASON_PACK_DIR_RE.match(cleaned)
                if m and "Season " not in cleaned:
                    candidates.append(base / d)

        for pack_dir in candidates:
            cleaned = strip_noise_prefix(pack_dir.name)
            m = self.SEASON_PACK_DIR_RE.match(cleaned)
            if not m:
                continue
            raw_show = m.group("show")
            season = m.group("season").zfill(2)
            show = re.sub(r"[\._\-]+", " ", raw_show).strip()

            dest_dir = self.resolve_show_season_dirs(root, show, season)
            if dest_dir.exists() and not self.same_path(pack_dir, dest_dir):
                alt_dir = self.unique_dir_path(dest_dir)
                LOGGER.warning(f"SEASON DIR EXISTS, USING ALT: {alt_dir}")
                dest_dir = alt_dir

            if self.same_path(pack_dir, dest_dir):
                LOGGER.info(f"OK SEASON DIR (already normalized): {pack_dir}")
                continue

            LOGGER.info(f"NORMALIZE SEASON FOLDER: {pack_dir} -> {dest_dir}")
            self.safe_move_dir(pack_dir, dest_dir, commit, journal)

    # ---------- Episode-wrapper folder normalization (SxxEyy / 3x##) ----------
    EPISODE_DIR_RE = re.compile(
        r"^(?P<show>.*?)[\.\s\-_]*((S(?P<s>\d{1,2})[\.\s\-_]*E(?P<e>\d{1,2}))|((?P<s2>\d{1,2})[xX](?P<e2>\d{1,2})))",
        re.IGNORECASE
    )

    def normalize_episode_wrapper_dirs(self, root: Path, commit: bool, journal: List[dict]):
        """
        For directories whose names include an explicit episode (e.g., 'www.UIndex.org - Show.S01E05...'),
        move their VIDEO/SIDECAR files into the canonical 'Show/Season xx/Show SxxEyy.ext' locations,
        then delete the now-empty wrapper directory.
        """
        wrappers: List[Path] = []
        for dirpath, dirnames, _ in os.walk(root):
            base = Path(dirpath)
            for d in dirnames:
                cleaned = strip_noise_prefix(d)
                if self.EPISODE_DIR_RE.match(cleaned):
                    wrappers.append(base / d)

        for wdir in wrappers:
            cleaned = strip_noise_prefix(wdir.name)
            m = self.EPISODE_DIR_RE.match(cleaned)
            if not m:
                continue
            s = m.group("s") or m.group("s2")
            e = m.group("e") or m.group("e2")
            raw_show = m.group("show")
            show = re.sub(r"[\._\-]+", " ", raw_show).strip()
            show = re.sub(r"\s+", " ", show)
            season, episode = s.zfill(2), e.zfill(2)

            # Move files inside this wrapper directory
            for fn in wdir.iterdir():
                if not fn.is_file():
                    continue
                ext = fn.suffix.lower()
                if ext in VIDEO_EXT:
                    dest = self.build_dest(root, show, season, episode, ext)
                elif ext in SIDECAR_EXT:
                    dest = self.build_sidecar_target(root, show, season, episode, fn.name)
                else:
                    # non-media file inside wrapper; skip
                    continue

                self.ensure_dir(dest.parent, commit)

                if self.same_path(fn, dest):
                    LOGGER.info(f"OK (already placed): {fn}")
                    continue

                if dest.exists():
                    try:
                        if self.same_content(fn, dest):
                            LOGGER.info(f"DUPLICATE: {fn} matches {dest} — deleting source")
                            self.safe_delete(fn, commit, journal)
                            continue
                    except Exception:
                        pass
                    dest = self.unique_path(dest)
                    LOGGER.warning(f"DEST EXISTS, USING ALT: {dest}")

                LOGGER.info(f"WRAPPER MOVE: {fn} -> {dest}")
                self.safe_move(fn, dest, commit, journal)

            # Attempt to delete empty wrapper dir (force remove even with hidden files/attrs)
            try:
                # If only hidden items remain, force delete
                visible = [p for p in wdir.iterdir() if not p.name.startswith(".")]
                if not visible:
                    LOGGER.info(f"DELETE WRAPPER DIR: {wdir}")
                    if commit:
                        shutil.rmtree(wdir, ignore_errors=True)
                        # journal note (undo not supported for rmtree)
                        journal.append({"op": "rmtree", "path": str(wdir)})
            except FileNotFoundError:
                pass

    # ---------- Strong cleanup: remove empty or effectively-empty dirs ----------
    def cleanup_empty_dirs(self, root: Path, commit: bool):
        """
        Delete directories that are empty or contain only hidden artifacts (.DS_Store, etc.).
        Uses rmtree(ignore_errors=True) to avoid macOS extended-attribute hiccups.
        """
        for dirpath, dirnames, filenames in os.walk(root, topdown=False):
            p = Path(dirpath)
            try:
                visible_files = [f for f in p.iterdir() if not f.name.startswith(".")]
                if not visible_files:
                    LOGGER.info(f"FORCE DELETE EMPTY DIR: {p}")
                    if commit:
                        shutil.rmtree(p, ignore_errors=True)
                        # journal not recorded here; undo for deletes is not supported
            except Exception as e:
                LOGGER.warning(f"SKIP DELETE {p}: {e}")

    # ---------- Main runner ----------
    def run(self, root: Path, commit: bool = False, plan: bool = False, quarantine: Optional[Path] = None):
        journal_path = root / f".clean-tv-journal-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
        journal: List[dict] = []

        LOGGER.info(f"START: {root} (commit={commit}, plan={plan})")

        # 0) Normalize season-pack folders first (keeps contents together)
        self.normalize_season_pack_dirs(root, commit, journal)

        # 0.5) Normalize episode-wrapper folders (e.g., 'www.UIndex.org - Show.S01E05...') before file pass
        self.normalize_episode_wrapper_dirs(root, commit, journal)

        # 1) Snapshot files after any folder normalization
        files: List[Path] = []
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                files.append(Path(dirpath) / fn)

        # 2) Process files
        for path in files:
            if not path.is_file():
                continue
            name, ext = path.name, path.suffix.lower()

            if name.startswith(".clean-tv-journal"):
                continue

            # Samples/trailers
            if name.lower().startswith(SAMPLE_PREFIXES):
                if quarantine:
                    self.ensure_dir(quarantine, commit)
                    dst = quarantine / name
                    LOGGER.info(f"QUARANTINE: {path} -> {dst}")
                    self.safe_move(path, dst, commit, journal)
                else:
                    LOGGER.info(f"SKIP SAMPLE: {path}")
                continue

            # Delete tiny aux
            if ext in AUX_DELETE:
                LOGGER.info(f"DELETE AUX: {path}")
                self.safe_delete(path, commit, journal)
                continue

            parsed = self.parse_tv_filename(name)
            if not parsed:
                # Try folder-derived parsing (wrapper/clean parent names)
                parsed = self.parse_from_parent_dir(path)
                if parsed:
                    LOGGER.info(f"FOLDER-DERIVED PARSE: {path.parent.name} -> {parsed[0]} S{parsed[1]}E{parsed[2]}")
                else:
                    LOGGER.warning(f"SKIP (unparsed): {path}")
                    continue

            show, season, episode = parsed

            # ---------------- Videos ----------------
            if ext in VIDEO_EXT:
                dest = self.build_dest(root, show, season, episode, ext)
                self.ensure_dir(dest.parent, commit)

                if self.same_path(path, dest):
                    LOGGER.info(f"OK (already placed): {path}")
                    continue

                if dest.exists():
                    if self.same_content(path, dest):
                        LOGGER.info(f"DUPLICATE: {path} matches {dest} — deleting source")
                        self.safe_delete(path, commit, journal)
                        continue
                    dest = self.unique_path(dest)
                    LOGGER.warning(f"DEST EXISTS, USING ALT: {dest}")

                LOGGER.info(f"MOVE: {path} -> {dest}")
                self.safe_move(path, dest, commit, journal)
                continue

            # ---------------- Sidecars ----------------
            if ext in SIDECAR_EXT:
                dest = self.build_sidecar_target(root, show, season, episode, name)
                self.ensure_dir(dest.parent, commit)

                if self.same_path(path, dest):
                    LOGGER.info(f"OK SIDECAR (already placed): {path}")
                    continue

                if dest.exists():
                    if self.same_content(path, dest):
                        LOGGER.info(f"SIDECAR DUPLICATE: {path} == {dest} — deleting source")
                        self.safe_delete(path, commit, journal)
                        continue
                    alt = self.unique_path(dest)
                    LOGGER.warning(f"SIDECAR EXISTS, USING ALT: {alt}")
                    dest = alt

                LOGGER.info(f"MOVE SIDECAR: {path} -> {dest}")
                self.safe_move(path, dest, commit, journal)
                continue

        # 3) Cleanup empty dirs (force delete hidden-only stubs)
        self.cleanup_empty_dirs(root, commit)

        # 4) Journal
        if plan or commit:
            with (journal_path).open("w", encoding="utf-8") as f:
                for entry in journal:
                    f.write(json.dumps(entry) + "\n")
            LOGGER.info(f"JOURNAL: {journal_path.resolve()}")

        LOGGER.info("END TRANS")
