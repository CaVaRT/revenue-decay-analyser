from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class SimilarwebConfig:
    api_key: str
    base_url: str
    output_dir: Path


def load_env_file(path: Path | None = None) -> None:
    """Load key/value pairs from a .env file into process env if missing."""
    env_path = path or (ROOT_DIR / ".env")
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def get_similarweb_config() -> SimilarwebConfig:
    load_env_file()

    api_key = os.getenv("SIMILARWEB_API_KEY", "").strip()
    if not api_key:
        raise ValueError("SIMILARWEB_API_KEY is required in environment or .env")

    base_url = os.getenv("SIMILARWEB_BASE_URL", "https://api.similarweb.com/v4").strip()
    output_dir = Path(os.getenv("OUTPUT_DIR", "reports/exports/SW")).resolve()
    return SimilarwebConfig(api_key=api_key, base_url=base_url, output_dir=output_dir)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
