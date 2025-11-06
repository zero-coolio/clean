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

class CleanService:
    """Service that organizes TV media safely with undo journaling."""

    # ---------------- Parsing ----------------
    @staticmethod
    def parse_tv_filename(filename: str) -> Optional[Tuple[str, str, str]]:
        """
        Supports:
          - Show.Name.S01E02
          - Show Name S01 E02
          - Show Name 3x01 / 3X01
          - Show Name ... 102 / 1002 (fused)
        """
        name = Path(filename).stem

        m = re.search(r"^(?P<show>.*?)[\.\s\-_]*S(?P<season>\d{1,2})[\.\s\-_]*E(?P<episode>\d{1,2})", name, re.IGNORECASE)
        if m:
            raw_show = m.group("show")
            season, episode = m.group("season"), m.group("episode")
        else:
            m = re.search(r"^(?P<show>.*?)[\.\s\-_]*(?P<season>\d{1,2})[xX](?P<episode>\d{1,2})", name, re.IGNORECASE)
            if m:
                raw_show = m.group("show")
                season, episode = m.group("season"), m.group("episode")
            else:
                m = re.search(r"^(?P<show>.*?)[\.\s\-_]*(?P<seasode>\d{3,4})(?!\d)", name, re.IGNORECASE)
                if not m:
                    return None
                raw_show = m.group("show")
                val = m.group("seasode")
                if len(val) == 3:
                    season, episode = val[0], val[1:]
                elif len(val) == 4:
                    season, episode = val[:2], val[2:]
                else:
                    return None

        show = re.sub(r"[\._\-]+", " ", raw_show).strip()
        show = re.sub(r"\s+", " ", show)
        return show, season.zfill(2), episode.zfill(2)

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
            elif op == "delete":
                LOGGER.warning(f"UNDO DELETE not supported automatically: {entry['path']}")

    # ---------------- Core ----------------
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

    def cleanup_empty_dirs(self, root: Path, commit: bool):
        for dirpath, _, _ in os.walk(root, topdown=False):
            p = Path(dirpath)
            if not any(p.iterdir()):
                LOGGER.info(f"DELETE EMPTY DIR: {p}")
                if commit:
                    try:
                        p.rmdir()
                    except OSError:
                        pass

    def run(self, root: Path, commit: bool = False, plan: bool = False, quarantine: Optional[Path] = None):
        journal_path = root / f".clean-tv-journal-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
        journal: List[dict] = []

        LOGGER.info(f"START: {root} (commit={commit}, plan={plan})")

        files: List[Path] = []
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                files.append(Path(dirpath) / fn)

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

        self.cleanup_empty_dirs(root, commit)

        if plan or commit:
            with journal_path.open("w", encoding="utf-8") as f:
                for entry in journal:
                    f.write(json.dumps(entry) + "\n")
            LOGGER.info(f"JOURNAL: {journal_path.resolve()}")

        LOGGER.info("END TRANS")
