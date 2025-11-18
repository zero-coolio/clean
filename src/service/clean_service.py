#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

LOGGER = logging.getLogger("clean-tv")
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
if not LOGGER.handlers:
    LOGGER.addHandler(_handler)
else:
    LOGGER.handlers.clear()
    LOGGER.addHandler(_handler)
LOGGER.setLevel(logging.INFO)


VIDEO_EXT = {".mkv", ".mp4", ".avi", ".mov"}
SIDECAR_EXT = {".srt", ".sub", ".idx", ".nfo", ".txt"}
IMAGE_EXT = {".jpg", ".jpeg", ".png"}
AUX_DELETE = {".ds_store", ".rar"}

SAMPLE_PREFIXES = ("sample", "proof", "trailer")

NOISE_PREFIX_PATTERNS = [
    r"^www\.UIndex\.org\s*-\s*",
    r"^\[?(?:tgx|rartv|rarbg|eztv|yts|eztv\.re)\]?\s*",
    r"^www\.",
]


def normalize_unicode_separators(s: str) -> str:
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    s = s.replace("\u00A0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def strip_noise_prefix(name: str) -> str:
    s = normalize_unicode_separators(name)
    for pat in NOISE_PREFIX_PATTERNS:
        s = re.sub(pat, "", s, flags=re.IGNORECASE)
    return s.lstrip()

def is_english_subtitle(name: str) -> bool:
    """Return True if a subtitle filename looks like English.

    We only use filename heuristics here, not content inspection.
    Examples considered English (case-insensitive):
        *.en.srt, *.eng.srt, *.english.srt, *english*.srt, *_en.*, *_eng.*
    """
    lower = name.lower()

    # We only care about typical subtitle extensions
    if not any(lower.endswith(ext) for ext in (".srt", ".vtt", ".ass", ".ssa", ".sub", ".idx")):
        return False

    markers = [
        ".en.", ".eng.", ".english.",
        "_en.", "_eng.", "-en.", "-eng.",
        "(en)", "[en]", "(eng)", "[eng]",
        " english",
    ]

    for m in markers:
        if m in lower:
            return True

    # Also handle pure suffix patterns like "episode.en.srt"
    if lower.endswith(".en.srt") or lower.endswith(".eng.srt") or lower.endswith(".english.srt"):
        return True

    return False


RE_SXXEYY = re.compile(
    r"^(?P<show>.*?)[.\s\-_]*S(?P<season>\d{1,2})[.\s\-_]*E(?P<episode>\d{1,2})",
    re.IGNORECASE,
)
RE_X = re.compile(
    r"^(?P<show>.*?)[.\s\-_]*(?P<season>\d{1,2})[xX](?P<episode>\d{1,2})",
    re.IGNORECASE,
)


def parse_episode_from_string(s: str) -> Optional[Tuple[str, str, str]]:
    name = normalize_unicode_separators(strip_noise_prefix(s))
    match = RE_SXXEYY.search(name) or RE_X.search(name)
    if not match:
        return None
    raw_show = match.group("show")
    season = match.group("season")
    episode = match.group("episode")
    show = re.sub(r"[._\-]+", " ", raw_show).strip()
    show = re.sub(r"\s+", " ", show)
    return show, season.zfill(2), episode.zfill(2)


class CleanService:
    def __init__(self) -> None:
        self._logger = LOGGER
        # Track any non-clean or suspicious folders we encounter
        self._source_folders: set[Path] = set()

    # ------------------- Helpers -------------------
    @staticmethod
    def sha1sum(path: Path, limit_bytes: int = 1024 * 1024) -> str:
        h = hashlib.sha1()
        with path.open("rb") as f:
            h.update(f.read(limit_bytes))
        return h.hexdigest()

    def same_content(self, a: Path, b: Path) -> bool:
        try:
            return a.stat().st_size == b.stat().st_size and self.sha1sum(a) == self.sha1sum(b)
        except Exception:
            return False

    @staticmethod
    def same_path(a: Path, b: Path) -> bool:
        try:
            return a.resolve() == b.resolve()
        except Exception:
            return str(a.absolute()) == str(b.absolute())

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
        base = p.stem
        ext = p.suffix
        i = 1
        while True:
            alt = p.with_name(f"{base} (alt{'' if i == 1 else f' {i}'}){ext}")
            if not alt.exists():
                return alt
            i += 1

    @staticmethod
    def safe_move(src: Path, dst: Path, commit: bool, journal: List[dict]) -> None:
        if dst.exists():
            raise FileExistsError(f"Destination exists: {dst}")
        if not commit:
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(src, dst)
        except OSError:
            with src.open("rb") as rf, dst.open("wb") as wf:
                shutil.copyfileobj(rf, wf)
            src.unlink(missing_ok=True)
        journal.append({"op": "move", "src": str(src), "dst": str(dst)})

    @staticmethod
    def safe_delete(path: Path, commit: bool, journal: List[dict]) -> None:
        if not commit:
            return
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        journal.append({"op": "delete", "path": str(path)})


    @staticmethod
    def build_dest(root: Path, show: str, season: str, episode: str, ext: str) -> Path:
        """Build the canonical destination path for a video file.

        Episodes are placed under:

            <root>/<Show Name>/Season <SS>/<Show Name> - S<SS>E<EE><ext>

        Example:
            /media/TV/Letterkenny/Season 05/Letterkenny - S05E01.mkv
        """
        from pathlib import Path as _P

        show_folder = show.strip()
        if not show_folder:
            show_folder = "Unknown Show"

        season_folder = root / show_folder / f"Season {season}"

        base_show = re.sub(r"\s+", ".", show_folder)
        filename = f"{base_show}.S{season}E{episode}{ext.lower()}"

        return _P(season_folder / filename)

    @staticmethod
    def build_sidecar_target(root: Path, show: str, season: str, episode: str, name: str) -> Path:
        """Build the destination path for a sidecar (subtitles, NFO, etc.).

        Sidecars are stored alongside the episode file, sharing the same
        base naming pattern but with their own extension.
        """
        from pathlib import Path as _P

        show_folder = show.strip()
        if not show_folder:
            show_folder = "Unknown Show"

        season_folder = root / show_folder / f"Season {season}"

        base_show = re.sub(r"\s+", ".", show_folder)
        ext = _P(name).suffix
        filename = f"{base_show}.S{season}E{episode}{ext.lower()}"

        return _P(season_folder / filename)

    # ------------------- Folder Name Rules -------------------
    @staticmethod
    def _is_clean_folder_name(folder_name: str) -> bool:
        """Folder must be 'Season XX'."""
        return bool(re.match(r"^Season\s+\d{2}$", folder_name, re.IGNORECASE))

    @staticmethod
    def _is_bad_show_folder_name(folder_name: str) -> bool:
        """
        Detect wrapper-style release folders:
        - Quality tags, WEBRip/WEB-DL, codecs, [rartv], release groups, etc.
        """
        bad_patterns = [
            r"\d{3,4}p",
            r"(WEB-?DL|WEBRip|BluRay|BDRip|HDRip)",
            r"(x264|x265|h264|h265|HEVC)",
            r"\[.*\]$",
            r"-[A-Z0-9]+$",
        ]
        for pat in bad_patterns:
            if re.search(pat, folder_name, re.IGNORECASE):
                return True
        return False

    # ------------- Track show folders lacking media -------------
    def _track_show_folders_without_media(self, root: Path) -> None:
        """
        Track ANY top-level show folder that:
        - Still exists
        - Has nested folders
        - Has ZERO media files under it
        """
        for entry in root.iterdir():
            if not entry.is_dir():
                continue

            show_dir = entry
            has_nested = False
            has_media = False

            for dirpath, dirnames, filenames in os.walk(show_dir):
                if dirnames:
                    has_nested = True
                for fn in filenames:
                    if Path(fn).suffix.lower() in VIDEO_EXT:
                        has_media = True
                        break
                if has_media:
                    break

            if show_dir.exists() and has_nested and not has_media:
                self._source_folders.add(show_dir)

    # ------------------- Cleanup -------------------
    def cleanup_empty_dirs(self, root: Path, commit: bool) -> None:
        for dirpath, _, _ in os.walk(root, topdown=False):
            p = Path(dirpath)

            if "screens" in p.name.lower():
                self._logger.info("DELETE SCREENS DIR: %s", p)
                if commit:
                    shutil.rmtree(p, ignore_errors=True)
                continue

            try:
                visible = [f for f in p.iterdir() if not f.name.startswith(".")]
            except FileNotFoundError:
                continue

            if not visible:
                self._logger.info("DELETE EMPTY DIR: %s", p)
                if commit:
                    shutil.rmtree(p, ignore_errors=True)

    # ------------------- Main -------------------
    def run(
        self,
        root: Path,
        commit: bool = False,
        plan: bool = False,
        quarantine: Optional[Path] = None,
    ) -> None:
        journal_path = root / f".clean-tv-journal-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
        journal: List[dict] = []
        unexpected: List[str] = []

        self._logger.info(
            "START: %s (commit=%s, plan=%s, quarantine=%s)",
            root,
            commit,
            plan,
            quarantine,
        )

        files: List[Path] = []
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                files.append(Path(dirpath) / fn)

        for path in files:
            if not path.is_file():
                continue

            name = path.name
            ext = path.suffix.lower()

            if name.startswith(".clean-tv-journal"):
                continue

            # Track non-clean wrapper / show folders and non-clean season folders,
            # regardless of whether any files were moved.
            try:
                rel_parts = path.parent.relative_to(root).parts if path.parent != root else ()
            except ValueError:
                rel_parts = ()
            parent_depth = len(rel_parts)

            if parent_depth >= 1:
                # Top-level show/wrapper folder
                top_level = root / rel_parts[0]
                if self._is_bad_show_folder_name(top_level.name):
                    self._source_folders.add(top_level)

            if parent_depth >= 2:
                # Season-level or deeper folder that isn't "Season XX"
                if not self._is_clean_folder_name(path.parent.name):
                    self._source_folders.add(path.parent)

            # Screens directory content
            if "screens" in str(path.parent).lower():
                self._logger.info("DELETE SCREENS FILE: %s", path)
                self.safe_delete(path, commit, journal)
                unexpected.append(f"{path} (screens-folder content)")
                continue

            lowered = name.lower()
            if lowered.startswith(SAMPLE_PREFIXES):
                # Samples / proofs / trailers
                if quarantine is not None:
                    quarantine.mkdir(parents=True, exist_ok=True)
                    dst = quarantine / name
                    self._logger.info("QUARANTINE SAMPLE: %s -> %s", path, dst)
                    try:
                        self.safe_move(path, dst, commit, journal)
                    except FileExistsError:
                        self._logger.warning(
                            "SAMPLE DEST EXISTS, DELETING SOURCE: %s",
                            path,
                        )
                        self.safe_delete(path, commit, journal)
                else:
                    self._logger.info("DELETE SAMPLE: %s", path)
                    self.safe_delete(path, commit, journal)
                unexpected.append(f"{path} (sample)")
                continue

            if ext in AUX_DELETE:
                self._logger.info("DELETE AUX: %s", path)
                self.safe_delete(path, commit, journal)
                continue

            if ext in IMAGE_EXT:
                self._logger.info("DELETE IMAGE FILE: %s", path)
                self.safe_delete(path, commit, journal)
                unexpected.append(f"{path} (image)")
                continue

            parsed_file = parse_episode_from_string(name)
            parsed_parent = parse_episode_from_string(path.parent.name)
            parsed = parsed_file or parsed_parent

            # Media and sidecars
            if ext in VIDEO_EXT or ext in SIDECAR_EXT:
                # In aggressive mode, keep only English subtitles from wrapper folders.
                # We treat files as being in a wrapper when the parent folder parses as a show/season.
                if ext in SIDECAR_EXT and self._is_bad_show_folder_name(path.parent.name) and not is_english_subtitle(name):
                    self._logger.info(
                        "DELETE NON-ENGLISH SUBTITLE IN WRAPPER: %s (wrapper: %s)",
                        path,
                        path.parent.name,
                    )
                    self.safe_delete(path, commit, journal)
                    unexpected.append(f"{path} (non-English subtitle in wrapper)")
                    continue
                if not parsed:
                    self._logger.warning("SKIP (unparsed media): %s", path)
                    unexpected.append(f"{path} (unparsed media)")
                    continue

                show, season, episode = parsed

                if ext in VIDEO_EXT:
                    dest = self.build_dest(root, show, season, episode, ext)
                else:
                    dest = self.build_sidecar_target(root, show, season, episode, name)

                dest.parent.mkdir(parents=True, exist_ok=True)

                if self.same_path(path, dest):
                    self._logger.info("OK (already placed): %s", path)
                    continue

                if dest.exists() and self.same_content(path, dest):
                    self._logger.info(
                        "DUPLICATE: %s matches %s — deleting source",
                        path,
                        dest,
                    )
                    self.safe_delete(path, commit, journal)
                    continue

                if dest.exists():
                    alt = self.unique_path(dest)
                    self._logger.warning("DEST EXISTS, USING ALT: %s", alt)
                    dest = alt

                self._logger.info("MOVE: %s -> %s", path, dest)
                # Track the source folder for media moves as well (legacy behavior)
                if not self._is_clean_folder_name(path.parent.name):
                    self._source_folders.add(path.parent)
                self.safe_move(path, dest, commit, journal)
                continue

            # Unknown extension or no extension
            if parsed_parent is not None:
                show, season, episode = parsed_parent
                self._logger.info(
                    "DELETE WRAPPER JUNK FILE: %s (parent parsed as %s S%sE%s)",
                    path,
                    show,
                    season,
                    episode,
                )
                self.safe_delete(path, commit, journal)
                unexpected.append(f"{path} (wrapper junk)")
                continue

            self._logger.info("SKIP (unknown ext, not in wrapper): %s", path)
            unexpected.append(f"{path} (unknown, not in wrapper)")

        # Cleanup and reporting
        self.cleanup_empty_dirs(root, commit)
        # After directory cleanup, track show folders that have nested structure
        # but contain no media files at all.
        self._track_show_folders_without_media(root)
        # Report on folders that still exist after cleanup and tracking
        self._report_remaining_folders()

        if plan or commit:
            with journal_path.open("w", encoding="utf-8") as f:
                for entry in journal:
                    f.write(json.dumps(entry) + "\n")
            self._logger.info("JOURNAL: %s", journal_path.resolve())

        if unexpected:
            self._logger.warning("UNEXPECTED FILES ENCOUNTERED (%d):", len(unexpected))
            for item in unexpected:
                self._logger.warning("UNEXPECTED: %s", item)

        self._logger.info("END TRANS")

    def _report_remaining_folders(self) -> None:
        """Report which non-clean-format or suspicious folders still exist after cleanup."""
        if not self._source_folders:
            self._logger.info("No non-clean folders were tracked.")
            return

        still_exist = [folder for folder in self._source_folders if folder.exists()]

        if still_exist:
            self._logger.warning("\n=== NON-CLEAN FOLDERS STILL EXIST ===")
            self._logger.warning("The following %d folder(s) still exist:", len(still_exist))
            for folder in sorted(still_exist):
                self._logger.warning("  - %s", folder)
            self._logger.warning("====================================\n")
        else:
            self._logger.info("All non-clean folders were successfully deleted.")
