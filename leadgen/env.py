from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


def load_project_env() -> None:
    load_dotenv(ENV_PATH, override=True)


def get_project_env(key: str, default: str = "") -> str:
    load_project_env()
    return os.getenv(key, default)
