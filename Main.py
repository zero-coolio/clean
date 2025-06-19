import os
import re
import argparse
import datetime
import shutil
import json

def sanitize_show_name(name):
    name = re.sub(r'[._-]+', ' ', name).strip()
    name = re.sub(r'\s+', ' ', name)
    for junk in ['PrimeWire', 'Panda', 'MeGusta']:
        name = name.replace(junk, '').strip()
    return name

def delete_empty_dirs(directory, dry_run, log_print):
    removed = True
    while removed:
        removed = False
        for root, dirs, files in os.walk(directory, topdown=False):
            for d in dirs:
                dir_path = os.path.join(root, d)
                # Ignore hidden files (those starting with .)
                contents = [f for f in os.listdir(dir_path) if not f.startswith('.')]
                if not contents:
                    if dry_run:
                        log_print('DRY RUN REMOVE DIR', dir_path)
                    else:
                        log_print('REMOVE DIR', dir_path)
                        os.rmdir(dir_path)
                    removed = True

def main():
    parser = argparse.ArgumentParser(description="TV show file renamer and cleaner with deletion, subtitle move, undo and strict conflict handling")
    parser.add_argument('--directory', type=str, required=True, help='Root directory to process')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode (no changes made)')
    parser.add_argument('--log', type=str, default='rename_log.txt', help='Log file path')
    parser.add_argument('--undo', action='store_true', help='Undo previous rename using backup file')
    parser.add_argument('--backup', type=str, default='rename_backup.json', help='Backup JSON file path')
    parser.add_argument('--print-skipped-only', action='store_true', help='Only print skipped file names (excluding .srt)')
    args = parser.parse_args()

    print_skipped_only = args.print_skipped_only

    def log_print(action, msg):
        full_msg = f"[{action}] {msg}"
        if not print_skipped_only or action == 'SKIP':
            print(full_msg)
        with open(args.log, 'a', encoding='utf-8') as log_file:
            log_file.write(full_msg + '\n')

    if args.undo:
        if not os.path.exists(args.backup):
            log_print('ERROR', f"Backup file not found: {args.backup}")
            return
        with open(args.backup, 'r', encoding='utf-8') as f:
            backups = json.load(f)
        for dst, src in backups.items():
            if os.path.exists(dst):
                log_print('UNDO', f"Restoring: {dst} -> {src}")
                if not args.dry_run:
                    os.makedirs(os.path.dirname(src), exist_ok=True)
                    shutil.move(dst, src)
            else:
                log_print('UNDO', f"File not found to restore: {dst}")
        log_print('UNDO', "Undo operation completed.")
        print("end trans")
        return

    directory = args.directory
    dry_run = args.dry_run
    backup_file = args.backup

    patterns = [
        re.compile(r'^(.*?)\s+Season\s+(\d+)\s+Episode\s+(\d+)', re.IGNORECASE),
        re.compile(r'^(.*?)\s+-\s+[Ss](\d+)[Ee](\d+)', re.IGNORECASE),
        re.compile(r'^(.*?)[ ._-]*[Ss](\d+)[Ee](\d+)', re.IGNORECASE),
        re.compile(r'^(.*?)[ ._-]*(\d+)x(\d+)', re.IGNORECASE),
    ]

    backup_data = {}
    episode_dirs = {}

    log_print('INFO', f"Run started: {datetime.datetime.now()}")

    rename_count = 0
    skip_count = 0
    conflict_count = 0
    delete_txt_count = 0
    delete_jpg_count = 0
    delete_png_count = 0
    delete_nfo_count = 0
    delete_dsstore_count = 0
    delete_duplicate_count = 0
    subtitle_move_count = 0

    for root, dirs, files in os.walk(directory):
        for filename in files:
            full_path = os.path.join(root, filename)
            lower_filename = filename.lower()

            # Deletion block
            if lower_filename.endswith(('.txt', '.jpg', '.png', '.nfo')) or filename in ['.DS_Store', '.DS_INFO'] or '(2)' in filename:
                if dry_run:
                    log_print('DRY RUN DELETE', full_path)
                else:
                    log_print('DELETE', full_path)
                    os.remove(full_path)
                if lower_filename.endswith('.txt'):
                    delete_txt_count += 1
                if lower_filename.endswith('.jpg'):
                    delete_jpg_count += 1
                if lower_filename.endswith('.png'):
                    delete_png_count += 1
                if lower_filename.endswith('.nfo'):
                    delete_nfo_count += 1
                if filename == '.DS_Store' or filename == '.DS_INFO':
                    delete_dsstore_count += 1
                if '(2)' in filename:
                    delete_duplicate_count += 1
                continue

            # Rename / Move main media files
            if not lower_filename.endswith('.srt'):
                matched = False
                for pattern in patterns:
                    match = pattern.search(filename)
                    if match:
                        matched = True
                        show_name_raw = match.group(1).strip()
                        season = int(match.group(2))
                        episode = int(match.group(3))

                        show_name = sanitize_show_name(show_name_raw)

                        _, ext = os.path.splitext(filename)
                        new_filename = f"{show_name} S{season:02d}E{episode:02d}{ext}"

                        target_dir = os.path.join(directory, show_name)
                        if not dry_run:
                            os.makedirs(target_dir, exist_ok=True)

                        dst_path = os.path.join(target_dir, new_filename)

                        if os.path.exists(dst_path):
                            log_print('SKIP CONFLICT', f"{full_path} -> {dst_path} (destination exists)")
                            conflict_count += 1
                            continue

                        if os.path.abspath(full_path) == os.path.abspath(dst_path):
                            log_print('SKIP', f"{full_path} (already correct)")
                            skip_count += 1
                            continue

                        if dry_run:
                            log_print('DRY RUN MOVE', f"{full_path} -> {dst_path}")
                        else:
                            log_print('MOVE', f"{full_path} -> {dst_path}")
                            shutil.move(full_path, dst_path)
                            backup_data[dst_path] = full_path

                        rename_count += 1
                        episode_dirs[(show_name, season, episode)] = os.path.dirname(dst_path)
                        break

                if not matched:
                    if print_skipped_only:
                        if not full_path.lower().endswith('.srt'):
                            print(full_path)
                    else:
                        log_print('SKIP', f"{full_path} (no matching pattern)")
                    skip_count += 1

    # Process subtitles (.srt)
    for root, dirs, files in os.walk(directory):
        for filename in files:
            if not filename.lower().endswith('.srt'):
                continue
            full_path = os.path.join(root, filename)

            matched = False
            for pattern in patterns:
                match = pattern.search(filename)
                if match:
                    matched = True
                    show_name_raw = match.group(1).strip()
                    season = int(match.group(2))
                    episode = int(match.group(3))
                    show_name = sanitize_show_name(show_name_raw)

                    target_dir = episode_dirs.get((show_name, season, episode))
                    if target_dir:
                        dst_path = os.path.join(target_dir, filename)

                        if os.path.exists(dst_path):
                            log_print('SKIP CONFLICT SUB', f"{full_path} -> {dst_path} (destination exists)")
                            conflict_count += 1
                            continue

                        if dry_run:
                            log_print('DRY RUN MOVE SUB', f"{full_path} -> {dst_path}")
                        else:
                            log_print('MOVE SUB', f"{full_path} -> {dst_path}")
                            shutil.move(full_path, dst_path)
                            backup_data[dst_path] = full_path
                        subtitle_move_count += 1
                    else:
                        log_print('SKIP SUB', f"{full_path} (no matching video folder)")
                    break
            if not matched:
                if print_skipped_only:
                    if not full_path.lower().endswith('.srt'):
                        print(full_path)
                else:
                    log_print('SKIP SUB', f"{full_path} (no matching pattern)")

    # Delete empty directories (initial pass)
    delete_empty_dirs(directory, dry_run, log_print)

    # Write backup file for undo
    if not dry_run:
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2)

    if not print_skipped_only:
        log_print('INFO', '=== Summary ===')
        log_print('INFO', f"Files renamed/moved: {rename_count}")
        log_print('INFO', f"Files skipped: {skip_count}")
        log_print('INFO', f"Filename conflicts (skipped): {conflict_count}")
        log_print('INFO', f".txt files deleted: {delete_txt_count}")
        log_print('INFO', f".jpg files deleted: {delete_jpg_count}")
        log_print('INFO', f".png files deleted: {delete_png_count}")
        log_print('INFO', f".nfo files deleted: {delete_nfo_count}")
        log_print('INFO', f".DS_Store/.DS_INFO files deleted: {delete_dsstore_count}")
        log_print('INFO', f"Duplicate (2) files deleted: {delete_duplicate_count}")
        log_print('INFO', f"Subtitles moved: {subtitle_move_count}")
        log_print('INFO', f"Log saved to: {os.path.abspath(args.log)}")
        if not dry_run:
            log_print('INFO', f"Backup saved to: {os.path.abspath(backup_file)} (use --undo to revert)")
        log_print('INFO', '='*20)

    # FINAL recursive empty folder cleanup
    delete_empty_dirs(directory, dry_run, log_print)

    print("end trans")

if __name__ == '__main__':
    main()
