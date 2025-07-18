import os
import re
import shutil
import argparse
import logging

# Setup logger
logger = logging.getLogger("movie_processor")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

def parse_movie_filename(filename):
    # Regex to extract title and year
    pattern = r'^(?P<title>.+?)[\.\s\-_\(\[]+(?P<year>19\d{2}|20\d{2})'
    match = re.search(pattern, filename)
    if not match:
        return None, None

    raw_title = match.group('title')
    year = match.group('year')

    # Clean up title
    title = re.sub(r'[\.\-_]', ' ', raw_title).strip()
    title = re.sub(r'\s+', ' ', title)

    return title, year

def process_file(file_path, intake_root, dry_run):
    filename = os.path.basename(file_path)

    # Delete files starting with "Sample"
    if filename.lower().startswith("sample"):
        logger.info(f"DELETE SAMPLE FILE: {file_path}")
        if not dry_run:
            os.remove(file_path)
        return

    title, year = parse_movie_filename(filename)

    if not title or not year:
        logger.warning(f"SKIPPED: Could not parse movie file: {file_path}")
        return

    ext = os.path.splitext(filename)[1]
    new_filename = f"{title} ({year}){ext}"
    dest_dir = os.path.join(intake_root, f"{title} ({year})")
    dest_path = os.path.join(dest_dir, new_filename)

    if os.path.abspath(file_path) == os.path.abspath(dest_path):
        logger.info(f"SKIPPED: File already correctly named and placed: {file_path}")
        return

    if os.path.exists(dest_path):
        logger.warning(f"SKIPPED: Destination file already exists: {dest_path}")
        return

    logger.info(f"MOVE: '{file_path}' -> '{dest_path}'")
    if not dry_run:
        os.makedirs(dest_dir, exist_ok=True)
        shutil.move(file_path, dest_path)

def process_non_media_file(file_path, intake_root, dry_run):
    filename = os.path.basename(file_path)

    # Delete hidden files
    if filename.startswith("."):
        logger.info(f"DELETE HIDDEN FILE: {file_path}")
        if not dry_run:
            os.remove(file_path)
        return

    dirpath = os.path.dirname(file_path)
    # Attempt to find matching movie folder
    pattern = r'^(?P<title>.+?)[\.\s\-_\(\[]+(?P<year>19\d{2}|20\d{2})'
    match = re.search(pattern, dirpath)
    if match:
        title = re.sub(r'[\.\-_]', ' ', match.group('title')).strip()
        title = re.sub(r'\s+', ' ', title)
        year = match.group('year')
        dest_dir = os.path.join(intake_root, f"{title} ({year})")
        dest_path = os.path.join(dest_dir, filename)
        logger.info(f"MOVE: '{file_path}' -> '{dest_path}'")
        if not dry_run:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.move(file_path, dest_path)
    else:
        logger.info(f"SKIPPED: Non-media file without matching movie folder: {file_path}")

def cleanup_empty_dirs(root_path, dry_run):
    for dirpath, dirnames, filenames in os.walk(root_path, topdown=False):
        visible_files = [f for f in filenames if not f.startswith('.')]
        visible_dirs = [d for d in dirnames if not d.startswith('.')]
        if not visible_dirs and not visible_files:
            logger.info(f"DELETE EMPTY OR HIDDEN-ONLY DIR: {dirpath}")
            if not dry_run:
                os.rmdir(dirpath)

def main():
    parser = argparse.ArgumentParser(description="Movie File Processor")
    parser.add_argument('--directory', required=True, help='Root directory to process')
    parser.add_argument('--dry-run', action='store_true', help='Simulate actions without making changes')
    args = parser.parse_args()

    intake_root = os.path.abspath(args.directory)
    logger.info(f"START PROCESSING: {intake_root}")

    for dirpath, dirnames, filenames in os.walk(intake_root):
        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            if filename.lower().endswith(('.mkv', '.mp4', '.avi', '.mov')):
                process_file(file_path, intake_root, args.dry_run)
            else:
                process_non_media_file(file_path, intake_root, args.dry_run)

    cleanup_empty_dirs(intake_root, args.dry_run)
    logger.info("END TRANS")

if __name__ == '__main__':
    main()
