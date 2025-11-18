from pathlib import Path
import sys

# Ensure project root is importable so 'src' is a package
THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.Main import main


def test_main_runs_with_empty_directory(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "intake"
    root.mkdir()

    # Simulate command-line invocation:
    # python -m src.Main --directory <root>
    monkeypatch.setattr(sys, "argv", ["clean-tv", "--directory", str(root)])

    # Should run without raising exceptions, even with no media present
    main()
