import os
from pathlib import Path


def _discover_project_root() -> Path:
    configured = os.environ.get("TESTING_PLATFORM_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    source_root = Path(__file__).resolve().parents[2]
    return source_root if (source_root / "configs").is_dir() else Path.cwd().resolve()


PROJECT_ROOT = _discover_project_root()
CONFIG_DIR = PROJECT_ROOT / "configs"
VAR_DIR = PROJECT_ROOT / "var"
