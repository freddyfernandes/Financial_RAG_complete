from pathlib import Path
import os
import yaml

def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]

from typing import Optional, Dict, Any

def load_config(config_path: Optional[str] = None) -> dict:
    """
    Load configuration from a YAML file.
    """
    env_path = os.getenv("CONFIG_PATH")
    if config_path is None:
        # _project_root() already points to the package root (multi_doc_chat)
        config_path = env_path or str(_project_root() / "config" / "config.yaml")

    path = Path(config_path)
    if not path.is_absolute():
        path = _project_root() / path

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}