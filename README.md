# TV File Processor

A Python utility for automatically organizing TV show files into a clean, structured directory hierarchy. The tool parses TV show filenames, extracts season and episode information, and moves files to properly organized folders while cleaning up unwanted auxiliary files.

## Features

- **Automatic File Organization**: Parses TV show filenames and organizes them into `Show Name/Season XX/` structure
- **Flexible Filename Parsing**: Handles various naming conventions (dots, underscores, dashes as separators)
- **Smart File Cleanup**: Removes sample files and auxiliary files (.nfo, .txt, .jpg, .png, .DS_Store)
- **Subtitle Management**: Automatically moves .srt files to match their corresponding video files
- **Empty Directory Cleanup**: Removes empty directories after file organization
- **Dry Run Mode**: Preview changes without actually moving files
- **Comprehensive Logging**: Detailed logging of all operations performed

## Installation

1. Clone or download the script
2. Ensure Python 3.6+ is installed
3. No additional dependencies required (uses only standard library)

```bash
git clone <repository-url>
cd tv-file-processor
```

## Usage

### Basic Usage

```bash
python Main.py --directory /path/to/your/tv/files
```

### Dry Run (Preview Mode)

```bash
python Main.py --directory /path/to/your/tv/files --dry-run
```

### Command Line Options

- `--directory` (required): Root directory containing TV files to process
- `--dry-run` (optional): Simulate actions without making actual changes

## Supported File Formats

### Video Files
- `.mkv`
- `.mp4` 
- `.avi`
- `.mov`

### Subtitle Files
- `.srt`

### Files Automatically Removed
- Sample files (any file starting with "sample")
- `.nfo` files
- `.txt` files
- `.jpg` files
- `.png` files
- `.DS_Store` files

## Filename Format Recognition

The tool recognizes TV show files in the following formats:

```
Show.Name.S01E01.mkv
Show Name S01E01.mkv
Show_Name_S01E01.mkv
Show-Name-S01E01.mkv
Show.Name.S1E1.mkv
Show Name S01E01 1080p BluRay.mkv
```

### Supported Patterns
- Season format: `S##` or `S#` (case insensitive)
- Episode format: `E##` or `E#` (case insensitive)  
- Show name separators: dots (.), underscores (_), dashes (-), or spaces
- Additional info after episode number is preserved

## Directory Structure

### Before Processing
```
/TV Files/
├── The.Office.S01E01.mkv
├── The.Office.S01E02.avi  
├── Friends.S02E15.1080p.mkv
├── sample_friends.mkv
├── random_folder/
│   └── Breaking.Bad.S01E01.srt
└── thumbs.jpg
```

### After Processing
```
/TV Files/
├── The Office/
│   └── Season 01/
│       ├── The Office S01E01.mkv
│       └── The Office S01E02.avi
├── Friends/
│   └── Season 02/
│       └── Friends S02E15.1080p.mkv
└── Breaking Bad/
    └── Season 01/
        └── Breaking Bad S01E01.srt
```

## Processing Logic

1. **File Analysis**: Scans all files in the directory tree
2. **Sample File Removal**: Deletes any files starting with "sample"
3. **Auxiliary File Cleanup**: Removes .nfo, .txt, .jpg, .png, and .DS_Store files
4. **TV File Processing**: 
   - Parses filename to extract show name, season, and episode
   - Creates destination directory structure
   - Moves and renames file with standardized format
5. **Subtitle Processing**: Moves .srt files to match their video counterparts
6. **Directory Cleanup**: Removes empty directories

## Skip Conditions

Files are skipped in the following scenarios:
- Already in the correct location with correct filename
- Destination file already exists (prevents overwrites)
- Filename cannot be parsed as a TV show episode
- File format not supported

## Logging

The tool provides detailed logging for all operations:

- `INFO`: Successful operations (moves, deletions)
- `WARNING`: Skipped files with reasons
- Timestamps included for all log entries
- Console output for real-time monitoring

### Example Log Output
```
2024-01-15 10:30:15 - INFO - START PROCESSING: /Users/john/TV Files
2024-01-15 10:30:15 - INFO - DELETE SAMPLE FILE: /Users/john/TV Files/sample.mkv
2024-01-15 10:30:15 - INFO - MOVE: '/Users/john/TV Files/The.Office.S01E01.mkv' -> '/Users/john/TV Files/The Office/Season 01/The Office S01E01.mkv'
2024-01-15 10:30:15 - WARNING - SKIPPED: Could not parse TV file: /Users/john/TV Files/random_movie.mkv
2024-01-15 10:30:15 - INFO - DELETE EMPTY DIR: /Users/john/TV Files/empty_folder
2024-01-15 10:30:15 - INFO - END TRANS
```

## Safety Features

- **Dry Run Mode**: Preview all changes before execution
- **No Overwrites**: Existing files are never overwritten
- **Skip Logic**: Files already in correct locations are left alone
- **Comprehensive Logging**: Full audit trail of all operations

## Testing

The project includes comprehensive unit tests covering all functionality:

```bash
# Run all tests
python test_main.py

# Run with pytest (if installed)
pytest test_main.py -v
```

### Test Coverage
- Filename parsing edge cases
- File operations (move, delete, skip)
- Dry run functionality
- Error handling
- Directory cleanup
- Logging verification

## Examples

### Example 1: Basic Organization
```bash
# Organize files in current directory
python Main.py --directory .

# Output:
# 2024-01-15 10:30:15 - INFO - START PROCESSING: /current/directory
# 2024-01-15 10:30:15 - INFO - MOVE: './The.Office.S01E01.mkv' -> './The Office/Season 01/The Office S01E01.mkv'
# 2024-01-15 10:30:15 - INFO - END TRANS
```

### Example 2: Dry Run Preview
```bash
# Preview changes without making them
python Main.py --directory /media/tv-shows --dry-run

# Shows what would happen without actually moving files
```

### Example 3: Complex Directory Structure
```bash
# Process a complex directory with multiple shows
python Main.py --directory /media/unsorted-tv

# Automatically organizes:
# - Multiple TV shows
# - Mixed seasons and episodes  
# - Subtitle files
# - Removes sample/auxiliary files
# - Cleans up empty directories
```

## Troubleshooting

### Common Issues

**Files not being processed:**
- Check that filenames contain season/episode info (S##E##)
- Verify file extensions are supported
- Check log output for specific skip reasons

**Permission errors:**
- Ensure write permissions to target directories
- Run with appropriate user privileges

**Unexpected file moves:**
- Use `--dry-run` first to preview changes
- Check log output to understand parsing logic

### Getting Help

1. Run with `--dry-run` to preview changes
2. Check log output for detailed information
3. Verify filename formats match supported patterns
4. Ensure file permissions allow read/write operations

## License

This project is released under the MIT License. See LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues for bugs and feature requests.

### Development Setup
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## Changelog

### v1.0.0
- Initial release
- Basic TV file organization
- Dry run mode
- Comprehensive logging
- Unit test suite