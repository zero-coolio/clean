import os
import re
import shutil
import argparse
import logging

# Setup logger
logger = logging.getLogger("tv_processor")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

def parse_tv_filename(filename):
    pattern = r'^(?P<show>.*?)(?:[\.\s\-_]*)(?:S(?P<season>\d{1,2})E(?P<episode>\d{1,2})).*'
    match = re.search(pattern, filename, re.IGNORECASE)
    if not match:
        return None, None, None

    raw_show = match.group('show')
    season = match.group('season').zfill(2)
    episode = match.group('episode').zfill(2)

    show = re.sub(r'[\._\-]', ' ', raw_show).strip()
    show = re.sub(r'\s+', ' ', show)

    return show, season, episode

def process_file(file_path, intake_root, dry_run):
    filename = os.path.basename(file_path)

    if filename.lower().startswith("sample"):
        logger.info(f"DELETE SAMPLE FILE: {file_path}")
        if not dry_run:
            os.remove(file_path)
        return

    if filename.lower().endswith(('.nfo', '.txt', '.jpg', '.png', '.ds_store')):
        logger.info(f"DELETE AUXILIARY FILE: {file_path}")
        if not dry_run:
            os.remove(file_path)
        return

    show, season, episode = parse_tv_filename(filename)

    if not show or not season or not episode:
        logger.warning(f"SKIPPED: Could not parse TV file: {file_path}")
        return

    ext = os.path.splitext(filename)[1]
    new_filename = f"{show} S{season}E{episode}{ext}"
    dest_dir = os.path.join(intake_root, show, f"Season {season}")
    dest_path = os.path.join(dest_dir, new_filename)

    if os.path.abspath(file_path) == os.path.abspath(dest_path):
        logger.info(f"SKIPPED: Already correctly placed: {file_path}")
        return

    if os.path.exists(dest_path):
        logger.warning(f"SKIPPED: Destination file already exists: {dest_path}")
        return

    logger.info(f"MOVE: '{file_path}' -> '{dest_path}'")
    if not dry_run:
        os.makedirs(dest_dir, exist_ok=True)
        shutil.move(file_path, dest_path)

def process_sidecar_files(intake_root, dry_run):
    for dirpath, dirnames, filenames in os.walk(intake_root):
        for filename in filenames:
            if filename.lower().endswith('.srt'):
                srt_path = os.path.join(dirpath, filename)
                show, season, episode = parse_tv_filename(filename)
                if show and season and episode:
                    dest_dir = os.path.join(intake_root, show, f"Season {season}")
                    dest_path = os.path.join(dest_dir, filename)
                    logger.info(f"MOVE SIDECAR: '{srt_path}' -> '{dest_path}'")
                    if not dry_run:
                        os.makedirs(dest_dir, exist_ok=True)
                        shutil.move(srt_path, dest_path)

def cleanup_empty_dirs(root_path, dry_run):
    for dirpath, dirnames, filenames in os.walk(root_path, topdown=False):
        visible_files = [f for f in filenames if not f.startswith('.')]
        visible_dirs = [d for d in dirnames if not d.startswith('.')]
        if not visible_dirs and not visible_files:
            logger.info(f"DELETE EMPTY DIR: {dirpath}")
            if not dry_run:
                os.rmdir(dirpath)

def main():
    parser = argparse.ArgumentParser(description="TV File Processor")
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

    process_sidecar_files(intake_root, args.dry_run)
    cleanup_empty_dirs(intake_root, args.dry_run)
    logger.info("END TRANS")

if __name__ == '__main__':
    main()
