#!/usr/bin/env python3
"""
Runtime entrypoint for Clean-TV.

Usage:
  python -m src.Main --directory "/path/to/intake" [--commit] [--plan] [--undo JOURNAL] [--quarantine DIR]
"""
from __future__ import annotations
import argparse
from pathlib import Path
from src.service.clean_service import CleanService

def parse_args():
    ap = argparse.ArgumentParser(description="Safely organize TV media (Clean-TV)")
    ap.add_argument("--directory", "-d", required=True, help="Root directory to process")
    ap.add_argument("--commit", action="store_true", help="Apply changes (omit for dry-run)")
    ap.add_argument("--plan", action="store_true", help="Write journal only (no changes)")
    ap.add_argument("--undo", metavar="JOURNAL", help="Undo from journal file")
    ap.add_argument("--quarantine", help="Quarantine directory for sample files")
    return ap.parse_args()

def main():
    args = parse_args()
    service = CleanService()
    if args.undo:
        service.undo_from_journal(Path(args.undo).expanduser().resolve())
        return
    root = Path(args.directory).expanduser().resolve()
    quarantine = Path(args.quarantine).expanduser().resolve() if args.quarantine else None
    service.run(root=root, commit=args.commit, plan=args.plan, quarantine=quarantine)

if __name__ == "__main__":
    main()
