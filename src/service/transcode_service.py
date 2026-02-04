#!/usr/bin/env python3
"""Transcode Service - Reduces video file sizes using HEVC encoding.

Transcodes video files to H.265/HEVC to reduce disk space while maintaining
reasonable quality. Supports batch processing via command line args or input file.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from ..config import VIDEO_EXT, get_logger

LOGGER = get_logger("transcode")


@dataclass
class TranscodeResult:
    """Result of a transcode operation."""
    source: Path
    success: bool
    original_size: int = 0
    new_size: int = 0
    error: str | None = None
    
    @property
    def savings(self) -> int:
        """Bytes saved."""
        return self.original_size - self.new_size if self.success else 0
    
    @property
    def reduction_pct(self) -> float:
        """Percentage reduction."""
        if not self.success or self.original_size == 0:
            return 0.0
        return (self.savings / self.original_size) * 100


# Preset configurations: (crf, preset, max_height)
PRESETS = {
    "fast": (23, "fast", None),           # Fast encode, good quality, decent compression
    "balanced": (22, "medium", None),      # Balance of speed and compression
    "quality": (20, "slow", None),         # Better quality, slower, less compression
    "compact": (24, "medium", 1080),       # Force 1080p max, good compression
    "tiny": (26, "fast", 720),             # Force 720p, maximum compression
}


def check_ffmpeg() -> bool:
    """Check if ffmpeg is available."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_video_info(path: Path) -> dict | None:
    """Get video file information using ffprobe.
    
    Returns:
        Dict with codec, width, height, bitrate or None on error.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height,bit_rate",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        import json
        data = json.loads(result.stdout)
        if data.get("streams"):
            stream = data["streams"][0]
            return {
                "codec": stream.get("codec_name", "unknown"),
                "width": stream.get("width", 0),
                "height": stream.get("height", 0),
                "bitrate": stream.get("bit_rate"),
            }
    except Exception:
        pass
    return None


def should_transcode(path: Path, info: dict | None, min_size_gb: float = 1.0) -> tuple[bool, str]:
    """Determine if a file should be transcoded.
    
    Args:
        path: Video file path.
        info: Video info from get_video_info().
        min_size_gb: Minimum file size to consider.
        
    Returns:
        Tuple of (should_transcode, reason).
    """
    size_gb = path.stat().st_size / (1024 * 1024 * 1024)
    
    if size_gb < min_size_gb:
        return False, f"too small ({size_gb:.2f} GB < {min_size_gb} GB)"
    
    if info is None:
        return False, "could not read video info"
    
    codec = info.get("codec", "").lower()
    
    # Already HEVC - might still benefit if very large
    if codec in ("hevc", "h265"):
        if size_gb < 4.0:
            return False, f"already HEVC and under 4 GB"
        return True, f"HEVC but large ({size_gb:.2f} GB)"
    
    return True, f"{codec} @ {size_gb:.2f} GB"


class TranscodeService:
    """Service to transcode video files to HEVC."""
    
    def __init__(self, preset: str = "balanced") -> None:
        """Initialize the service.
        
        Args:
            preset: Quality preset name.
        """
        self._logger = LOGGER
        self._preset = preset
        self._results: list[TranscodeResult] = []
        
        if preset not in PRESETS:
            raise ValueError(f"Unknown preset: {preset}. Available: {list(PRESETS.keys())}")
    
    def transcode_file(
        self,
        source: Path,
        commit: bool = False,
        keep_original: bool = False,
    ) -> TranscodeResult:
        """Transcode a single video file.
        
        Args:
            source: Source video file.
            commit: If True, perform the transcode. If False, dry-run.
            keep_original: If True, keep original file with .original suffix.
            
        Returns:
            TranscodeResult with operation details.
        """
        if not source.exists():
            return TranscodeResult(source, False, error="file not found")
        
        if source.suffix.lower() not in VIDEO_EXT:
            return TranscodeResult(source, False, error="not a video file")
        
        original_size = source.stat().st_size
        info = get_video_info(source)
        
        should, reason = should_transcode(source, info)
        if not should:
            self._logger.info("SKIP: %s (%s)", source.name, reason)
            return TranscodeResult(source, False, original_size, original_size, error=f"skipped: {reason}")
        
        crf, preset, max_height = PRESETS[self._preset]
        
        # Build ffmpeg command
        output_suffix = ".transcoded.mkv"
        temp_output = source.with_suffix(output_suffix)
        
        cmd = [
            "ffmpeg",
            "-i", str(source),
            "-c:v", "libx265",
            "-crf", str(crf),
            "-preset", preset,
            "-c:a", "aac",
            "-b:a", "128k",
            "-c:s", "copy",  # Copy subtitles
            "-map", "0",      # Map all streams
            "-y",             # Overwrite output
        ]
        
        # Add scale filter if max_height specified
        if max_height and info and info.get("height", 0) > max_height:
            cmd.extend(["-vf", f"scale=-2:{max_height}"])
        
        cmd.append(str(temp_output))
        
        size_gb = original_size / (1024 * 1024 * 1024)
        self._logger.info(
            "TRANSCODE: %s (%.2f GB, %s) -> HEVC crf=%d preset=%s",
            source.name, size_gb, info.get("codec", "?") if info else "?", crf, preset,
        )
        
        if not commit:
            self._logger.info("  [DRY-RUN] Would transcode to %s", temp_output.name)
            return TranscodeResult(source, True, original_size, int(original_size * 0.5))
        
        # Run ffmpeg
        try:
            self._logger.info("  Running ffmpeg (this may take a while)...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )
            
            if result.returncode != 0:
                self._logger.error("  FAILED: ffmpeg error")
                self._logger.error("  stderr: %s", result.stderr[-500:] if result.stderr else "none")
                if temp_output.exists():
                    temp_output.unlink()
                return TranscodeResult(source, False, original_size, error="ffmpeg failed")
            
            if not temp_output.exists():
                return TranscodeResult(source, False, original_size, error="output file not created")
            
            new_size = temp_output.stat().st_size
            
            # Verify output is valid
            verify_info = get_video_info(temp_output)
            if verify_info is None:
                self._logger.error("  FAILED: output file appears invalid")
                temp_output.unlink()
                return TranscodeResult(source, False, original_size, error="output verification failed")
            
            # Check if we actually saved space
            if new_size >= original_size:
                self._logger.warning("  NO SAVINGS: output is same size or larger, keeping original")
                temp_output.unlink()
                return TranscodeResult(source, False, original_size, new_size, error="no size reduction")
            
            # Replace original
            if keep_original:
                backup = source.with_suffix(source.suffix + ".original")
                source.rename(backup)
                self._logger.info("  Original backed up to: %s", backup.name)
            else:
                source.unlink()
            
            # Rename transcoded file to original name (but .mkv)
            final_output = source.with_suffix(".mkv")
            temp_output.rename(final_output)
            
            savings_gb = (original_size - new_size) / (1024 * 1024 * 1024)
            reduction = ((original_size - new_size) / original_size) * 100
            
            self._logger.info(
                "  SUCCESS: %.2f GB -> %.2f GB (saved %.2f GB, %.1f%% reduction)",
                original_size / (1024**3),
                new_size / (1024**3),
                savings_gb,
                reduction,
            )
            
            return TranscodeResult(source, True, original_size, new_size)
            
        except Exception as e:
            self._logger.error("  FAILED: %s", e)
            if temp_output.exists():
                temp_output.unlink()
            return TranscodeResult(source, False, original_size, error=str(e))
    
    def transcode_files(
        self,
        files: list[Path],
        commit: bool = False,
        keep_original: bool = False,
    ) -> list[TranscodeResult]:
        """Transcode multiple files.
        
        Args:
            files: List of video file paths.
            commit: If True, perform transcodes.
            keep_original: If True, keep original files.
            
        Returns:
            List of TranscodeResult objects.
        """
        self._results = []
        
        self._logger.info("=== TRANSCODE SERVICE ===")
        self._logger.info("Preset: %s", self._preset)
        self._logger.info("Files: %d", len(files))
        self._logger.info("Commit: %s", commit)
        self._logger.info("")
        
        for i, path in enumerate(files, 1):
            self._logger.info("[%d/%d] Processing: %s", i, len(files), path.name)
            result = self.transcode_file(path, commit, keep_original)
            self._results.append(result)
        
        self._report_summary()
        return self._results
    
    def transcode_from_file(
        self,
        input_file: Path,
        commit: bool = False,
        keep_original: bool = False,
    ) -> list[TranscodeResult]:
        """Transcode files listed in an input file.
        
        Args:
            input_file: Text file with one file path per line.
            commit: If True, perform transcodes.
            keep_original: If True, keep original files.
            
        Returns:
            List of TranscodeResult objects.
        """
        files: list[Path] = []
        
        with input_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                path = Path(line)
                if path.exists():
                    files.append(path)
                else:
                    self._logger.warning("File not found, skipping: %s", line)
        
        return self.transcode_files(files, commit, keep_original)
    
    def _report_summary(self) -> None:
        """Report summary of transcode operations."""
        if not self._results:
            return
        
        successful = [r for r in self._results if r.success]
        failed = [r for r in self._results if not r.success and r.error and "skipped" not in r.error]
        skipped = [r for r in self._results if r.error and "skipped" in r.error]
        
        total_original = sum(r.original_size for r in successful)
        total_new = sum(r.new_size for r in successful)
        total_savings = total_original - total_new
        
        self._logger.info("")
        self._logger.info("=== TRANSCODE SUMMARY ===")
        self._logger.info("Processed: %d", len(self._results))
        self._logger.info("Successful: %d", len(successful))
        self._logger.info("Skipped: %d", len(skipped))
        self._logger.info("Failed: %d", len(failed))
        
        if successful:
            self._logger.info("")
            self._logger.info("Space saved: %.2f GB", total_savings / (1024**3))
            self._logger.info("Original total: %.2f GB", total_original / (1024**3))
            self._logger.info("New total: %.2f GB", total_new / (1024**3))
            if total_original > 0:
                self._logger.info("Overall reduction: %.1f%%", (total_savings / total_original) * 100)
        
        if failed:
            self._logger.warning("")
            self._logger.warning("Failed files:")
            for r in failed:
                self._logger.warning("  %s: %s", r.source.name, r.error)
        
        self._logger.info("=========================")
