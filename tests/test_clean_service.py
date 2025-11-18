from pathlib import Path
import sys

# Ensure 'src' is importable
THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from service.clean_service import CleanService, parse_episode_from_string


def test_parse_episode_from_string_sxxeyy() -> None:
    s = "Letterkenny.S05E01.1080p.HULU.WEBRip.AAC2.0.x264-monkee"
    show, season, episode = parse_episode_from_string(s)
    assert show == "Letterkenny"
    assert season == "05"
    assert episode == "01"


def test_parse_episode_from_string_x_pattern() -> None:
    s = "Letterkenny - 5x2 - Super Soft Birthday"
    show, season, episode = parse_episode_from_string(s)
    assert show == "Letterkenny"
    assert season == "05"
    assert episode == "02"


def test_build_dest_and_sidecar(tmp_path: Path) -> None:
    root = tmp_path
    show = "Letterkenny"
    season = "05"
    episode = "01"

    dest = CleanService.build_dest(root, show, season, episode, ".mkv")
    expected_video = root / "Letterkenny" / "Season 05" / "Letterkenny.S05E01.mkv"
    assert dest == expected_video

    sidecar = CleanService.build_sidecar_target(root, show, season, episode, "subtitle.srt")
    expected_sidecar = root / "Letterkenny" / "Season 05" / "Letterkenny.S05E01.srt"
    assert sidecar == expected_sidecar


def test_run_moves_media_to_expected_dest(tmp_path: Path) -> None:
    root = tmp_path / "intake"
    root.mkdir()

    # Wrapper-style folder with a single episode file
    wrapper = root / "Letterkenny.S05.1080p.HULU.WEBRip.AAC2.0.x264-monkee[rartv]"
    wrapper.mkdir()

    src_file = wrapper / "Letterkenny.S05E01.1080p.HULU.WEBRip.AAC2.0.x264-monkee.mkv"
    src_file.write_text("FAKE_DATA", encoding="utf-8")

    service = CleanService()
    service.run(root=root, commit=True, plan=False, quarantine=None)

    expected_dest = CleanService.build_dest(root, "Letterkenny", "05", "01", ".mkv")

    # Source should have been moved
    assert not src_file.exists()
    assert expected_dest.exists()
    assert expected_dest.read_text(encoding="utf-8") == "FAKE_DATA"


def test_run_with_plan_does_not_modify_files(tmp_path: Path) -> None:
    root = tmp_path / "intake"
    root.mkdir()

    wrapper = root / "Letterkenny.S05.1080p.HULU.WEBRip.AAC2.0.x264-monkee[rartv]"
    wrapper.mkdir()

    src_file = wrapper / "Letterkenny.S05E01.1080p.HULU.WEBRip.AAC2.0.x264-monkee.mkv"
    src_file.write_text("FAKE_DATA", encoding="utf-8")

    service = CleanService()
    service.run(root=root, commit=False, plan=True, quarantine=None)

    expected_dest = CleanService.build_dest(root, "Letterkenny", "05", "01", ".mkv")

    # In plan mode with commit=False, nothing should be moved
    assert src_file.exists()
    assert not expected_dest.exists()

def test_non_english_subtitles_in_wrapper_are_deleted(tmp_path: Path) -> None:
    root = tmp_path / "intake"
    root.mkdir()

    wrapper = root / "Letterkenny.S05.1080p.HULU.WEBRip.AAC2.0.x264-monkee[rartv]"
    wrapper.mkdir()

    video = wrapper / "Letterkenny.S05E01.1080p.HULU.WEBRip.AAC2.0.x264-monkee.mkv"
    video.write_text("VIDEO", encoding="utf-8")

    eng_sub = wrapper / "Letterkenny.S05E01.en.srt"
    eng_sub.write_text("ENGLISH SUB", encoding="utf-8")

    fr_sub = wrapper / "Letterkenny.S05E01.fr.srt"
    fr_sub.write_text("FRENCH SUB", encoding="utf-8")

    # Also include a .rar file which should be deleted as AUX
    rar_file = wrapper / "SomeArchive.rar"
    rar_file.write_text("RAR DATA", encoding="utf-8")

    service = CleanService()
    service.run(root=root, commit=True, plan=False, quarantine=None)

    # Video should be moved
    dest_video = CleanService.build_dest(root, "Letterkenny", "05", "01", ".mkv")
    assert dest_video.exists()
    assert dest_video.read_text(encoding="utf-8") == "VIDEO"

    # English subtitle should be moved
    dest_eng = CleanService.build_sidecar_target(root, "Letterkenny", "05", "01", eng_sub.name)
    assert dest_eng.exists()
    assert dest_eng.read_text(encoding="utf-8") == "ENGLISH SUB"

    # Non-English subtitle source should be deleted from wrapper
    assert not fr_sub.exists()

    # Only one .srt file should exist in the destination season folder
    season_dir = root / "Letterkenny" / "Season 05"
    srt_files = sorted(p.name for p in season_dir.glob("*.srt"))
    assert srt_files == ["Letterkenny.S05E01.srt"]

    # .rar file should be deleted
    assert not rar_file.exists()
