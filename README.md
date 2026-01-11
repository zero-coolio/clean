# Clean Media Organizer

Safety-critical media organizers for TV shows and Movies. Normalizes filenames, organizes into clean folder structures, handles duplicates, and keeps an undo journal.

## Services

### Clean-TV
Organizes TV episodes into `Show Name/Season XX/Show.Name.SxxExx.ext` structure.

### Clean-Movie
Organizes movies into `Movie Title (Year)/Movie Title (Year).ext` structure.

## Layout
```
clean/
├── src/
│   ├── __init__.py
│   ├── Main.py           # TV entrypoint
│   ├── MovieMain.py      # Movie entrypoint
│   └── service/
│       ├── __init__.py
│       ├── clean_service.py        # TV service
│       └── clean_movie_service.py  # Movie service
├── scripts/
│   ├── clean-tv.command
│   └── clean-movie.command
└── tests/
    ├── test_clean_service.py
    └── test_clean_movie_service.py
```

## Quick Start

### TV Shows
```bash
# Dry-run (no changes)
python -m src.Main -d "/Volumes/Seagate/seagate-qBittorrent"

# Apply changes
python -m src.Main -d "/Volumes/Seagate/seagate-qBittorrent" --commit

# With quarantine for samples
python -m src.Main -d "/Volumes/Seagate/seagate-qBittorrent" --commit --quarantine "/tmp/quarantine"
```

### Movies
```bash
# Dry-run (no changes)
python -m src.MovieMain -d "/Volumes/Seagate/seagate-movie"

# Apply changes
python -m src.MovieMain -d "/Volumes/Seagate/seagate-movie" --commit

# With quarantine for samples/trailers
python -m src.MovieMain -d "/Volumes/Seagate/seagate-movie" --commit --quarantine "/tmp/quarantine"
```

### Options
| Option | Description |
|--------|-------------|
| `--directory`, `-d` | Root directory to process (required) |
| `--commit` | Apply changes (omit for dry-run) |
| `--plan` | Write journal without making changes |
| `--quarantine DIR` | Move samples/trailers to DIR instead of deleting |
| `--undo FILE` | (TV only) Undo from journal file |

## What Each Service Does

### Clean-TV
- Parses episode patterns: `SxxExx`, `1x01`
- Creates structure: `Show Name/Season XX/Show.Name.SxxExx.ext`
- Moves video files (.mkv, .mp4, .avi, .mov)
- Moves English subtitles, deletes non-English in release folders
- Deletes: samples, proofs, trailers, images, RAR files, .DS_Store
- Cleans up empty directories and "screens" folders

### Clean-Movie
- Parses movie patterns: `Movie.Name.Year.Quality...` or `Movie Name (Year)`
- Creates structure: `Movie Title (Year)/Movie Title (Year).ext`
- Moves video files (.mkv, .mp4, .avi, .mov, .m4v, .wmv)
- Moves English subtitles with language tags preserved
- Deletes: samples, proofs, trailers, images, RAR/PAR files
- Cleans up empty directories and "screens" folders

## Running Scripts

Double-click the `.command` files in Finder:
- `scripts/clean-tv.command` - Process TV directory
- `scripts/clean-movie.command` - Process movie directory

Make executable first:
```bash
chmod +x scripts/*.command
```

## Running Tests

```bash
cd /path/to/clean
pytest tests/ -v
```

## Safety Notes
- **Dry-run by default** - Always preview with no `--commit` flag first
- **Cross-device safe** - Uses copy+delete if rename fails
- **Duplicate handling** - Same content = delete source; different = create `(alt)` suffix
- **Journals** - Written to root directory for tracking/undo
- **Sidecar renaming** - Subtitles renamed to match video, language tags preserved
