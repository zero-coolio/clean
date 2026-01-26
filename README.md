# Clean Media Organizer

Safety-critical media organizers for TV shows and Movies. Normalizes filenames, organizes into clean folder structures, handles duplicates, and keeps an undo journal.

## Features

- **Dry-run by default** — Preview changes before committing
- **Cross-device safe** — Uses copy+delete if rename fails
- **Duplicate detection** — Same content = delete source; different = create `(alt)` suffix
- **Undo support** — Journal files enable reverting changes
- **Quarantine mode** — Move samples/trailers instead of deleting
- **English subtitle preservation** — Keeps English subs, deletes non-English in release folders
- **TMDB lookup** — Optional API integration for movie year lookups

## Installation

```bash
# Basic install
pip install -e .

# With TMDB API support
pip install -e ".[tmdb]"

# With development dependencies
pip install -e ".[dev]"
```

## Quick Start

### TV Shows

```bash
# Dry-run (preview changes)
python -m src.Main -d "/Volumes/Seagate/seagate-qBittorrent"

# Apply changes
python -m src.Main -d "/Volumes/Seagate/seagate-qBittorrent" --commit

# With quarantine for samples
python -m src.Main -d "/Volumes/Seagate/seagate-qBittorrent" --commit --quarantine "/tmp/quarantine"

# Undo from journal
python -m src.Main --undo "/path/to/.clean-tv-journal-20240101-120000.jsonl"
```

### Movies

```bash
# Dry-run (preview changes)
python -m src.MovieMain -d "/Volumes/Seagate/seagate-movie"

# Apply changes
python -m src.MovieMain -d "/Volumes/Seagate/seagate-movie" --commit

# With TMDB lookup for missing years (requires TMDB_API_KEY env var)
export TMDB_API_KEY="your_api_key_here"
python -m src.MovieMain -d "/Volumes/Seagate/seagate-movie" --commit --lookup

# Undo from journal
python -m src.MovieMain --undo "/path/to/.clean-movie-journal-20240101-120000.jsonl"
```

## Command Line Options

| Option | Description |
|--------|-------------|
| `--directory`, `-d` | Root directory to process (required) |
| `--commit` | Apply changes (omit for dry-run) |
| `--plan` | Write journal without making changes |
| `--quarantine DIR` | Move samples/trailers to DIR instead of deleting |
| `--undo FILE` | Undo operations from journal file |
| `--lookup` | (Movie only) Use TMDB API for year lookups |

## Directory Structure

### TV Shows

Input:
```
/intake/Letterkenny.S05.1080p.HULU.WEBRip[rartv]/
├── Letterkenny.S05E01.1080p.HULU.WEBRip.mkv
├── Letterkenny.S05E01.en.srt
└── Letterkenny.S05E01.fr.srt  # Deleted (non-English)
```

Output:
```
/intake/Letterkenny/
└── Season 05/
    ├── Letterkenny.S05E01.mkv
    └── Letterkenny.S05E01.srt
```

### Movies

Input:
```
/movies/The.Matrix.1999.1080p.BluRay.x264/
├── The.Matrix.1999.1080p.BluRay.x264.mkv
├── movie.eng.srt
├── movie.spa.srt  # Deleted (non-English)
├── sample.mkv     # Deleted (sample)
└── movie.nfo      # Deleted (junk)
```

Output:
```
/movies/The Matrix (1999)/
├── The Matrix (1999).mkv
└── The Matrix (1999).eng.srt
```

## Runner Scripts

Double-click the `.command` files in Finder:

- `scripts/clean-tv.command` — Process TV directory
- `scripts/clean-movie.command` — Process movie directory

Make executable first:
```bash
chmod +x scripts/*.command
```

### Configuration via Environment Variables

```bash
# TV
export CLEAN_TV_DIR="/path/to/tv/directory"
export CLEAN_TV_QUARANTINE="/path/to/quarantine"

# Movies
export CLEAN_MOVIE_DIR="/path/to/movie/directory"
export CLEAN_MOVIE_QUARANTINE="/path/to/quarantine"
export TMDB_API_KEY="your_api_key"
```

## Project Structure

```
clean/
├── pyproject.toml          # Package configuration
├── README.md
├── src/
│   ├── __init__.py
│   ├── config.py           # Shared constants and logging
│   ├── utils.py            # Shared utilities
│   ├── Main.py             # TV entrypoint
│   ├── MovieMain.py        # Movie entrypoint
│   └── service/
│       ├── __init__.py
│       ├── base.py         # Base service class
│       ├── clean_service.py        # TV service
│       └── clean_movie_service.py  # Movie service
├── scripts/
│   ├── clean-tv.command
│   └── clean-movie.command
└── tests/
    ├── __init__.py
    ├── test_main.py
    ├── test_clean_service.py
    └── test_clean_movie_service.py
```

## Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=term-missing

# Run specific test file
pytest tests/test_clean_service.py -v
```

## What Gets Deleted

### Both Services
- Sample files (`sample-*.mkv`, `proof-*.mkv`, `trailer-*.mkv`)
- Files in `Sample/` folders
- Image files (`.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`)
- Archive files (`.rar`, `.r00`, `.sfv`, `.par2`)
- `.DS_Store` files
- `screens/` directories
- Empty directories

### TV Service
- Non-English subtitles in release folders

### Movie Service
- Non-English subtitles in release folders
- NFO and TXT files (usually release info)

## Safety Notes

- **Always preview first** — Run without `--commit` to see what would happen
- **Journals are your safety net** — Keep them until you verify results
- **Undo has limits** — Deleted files cannot be recovered
- **Cross-device moves** — Handled safely with copy+delete

## TMDB API

To use movie year lookups:

1. Get a free API key from [TMDB](https://www.themoviedb.org/settings/api)
2. Set the environment variable: `export TMDB_API_KEY="your_key"`
3. Use the `--lookup` flag

The service includes rate limiting (4 requests/second) to respect API limits.
