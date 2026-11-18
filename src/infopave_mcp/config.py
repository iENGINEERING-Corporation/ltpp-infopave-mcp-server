"""Runtime settings, read from environment variables (all prefixed INFOPAVE_)."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_PAGE = 25  # rows per page when the caller does not say
MAX_PAGE = 50  # largest page; longer lists are paged with offset / next_offset

# Where the data pack is looked for when INFOPAVE_DATA_DIR is not set.
DEFAULT_DATA_DIRS = ("data", "data_pack")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    backend: str  # "duckdb" (Parquet data pack) or "sqlserver"
    transport: str  # "stdio" or "http"
    host: str
    port: int
    sqlserver_connection: str | None


def _default_data_dir() -> Path:
    for name in DEFAULT_DATA_DIRS:
        candidate = PROJECT_ROOT / name
        if candidate.is_dir() and any(candidate.glob("*.parquet")):
            return candidate
    return PROJECT_ROOT / DEFAULT_DATA_DIRS[0]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env_dir = os.environ.get("INFOPAVE_DATA_DIR")
    return Settings(
        data_dir=Path(env_dir).expanduser().resolve() if env_dir else _default_data_dir(),
        backend=os.environ.get("INFOPAVE_BACKEND", "duckdb").lower(),
        transport=os.environ.get("INFOPAVE_TRANSPORT", "stdio").lower(),
        host=os.environ.get("INFOPAVE_HOST", "127.0.0.1"),
        port=int(os.environ.get("INFOPAVE_PORT", "8000")),
        sqlserver_connection=os.environ.get("INFOPAVE_SQLSERVER_CONNECTION"),
    )
