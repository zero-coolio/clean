# Clean-TV (Runtime Package)

A safety-critical TV media organizer. It normalizes episode names, snaps to existing show/season folders case-insensitively, moves videos & sidecars, handles duplicates, and keeps an undo journal.

## Layout
```
clean-tv-runtime/
├── src/
│   ├── __init__.py
│   └── Main.py
├── service/
│   ├── __init__.py
│   └── clean_service.py
└── utils/
    ├── __init__.py
    └── snapshot.py
```

## Quick Start
```bash
# Dry-run (no changes)
python -m src.Main -d "/Volumes/Intake"

# Plan only (write journal, no changes)
python -m src.Main -d "/Volumes/Intake" --plan

# Apply changes
python -m src.Main -d "/Volumes/Intake" --commit

# Undo previously recorded moves
python -m src.Main --undo "/Volumes/Intake/.clean-tv-journal-YYYYMMDD-HHMMSS.jsonl"
```

### Options
- `--quarantine DIR` : move files starting with `sample/proof/trailer` into DIR
- `--commit`         : actually apply changes (omit for dry-run default)
- `--plan`           : write a journal without making changes
- `--undo FILE`      : undo moves recorded in a prior journal

## Snapshot Utility
Create a JSON or table snapshot for training/diagnosing filename patterns.

```bash
# JSON to stdout
python -m utils.snapshot -d "/Volumes/Intake"

# Table printout
python -m utils.snapshot -d "/Volumes/Intake" --print

# Save to a file
python -m utils.snapshot -d "/Volumes/Intake" --print -o ./snapshots/2025-11-06.txt
```

## Safety Notes
- Moves are cross-device safe. Duplicates (same content) delete the source.
- Sidecars are renamed to match normalized video stems and keep language tags.
- Existing destination files get an automatic `(alt)`, `(alt 2)`, ... suffix.
- Journals are written to the root you process for easy undo.
```

