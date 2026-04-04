"""
CacheManager — stores DataFrames as parquet and dicts as JSON with
staleness tracking based on metadata timestamps.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


class CacheManager:
    """Disk-backed cache for DataFrames (parquet) and dicts (JSON)."""

    def __init__(self, cache_dir: str, max_age_hours: float = 20):
        self.cache_dir = Path(cache_dir)
        self.max_age_hours = max_age_hours
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ── DataFrame (parquet) ──────────────────────────────────────────

    def save(self, key: str, df: pd.DataFrame) -> None:
        """Write *df* to ``{key}.parquet`` and create a companion meta file."""
        path = self.cache_dir / f"{key}.parquet"
        df.to_parquet(path)
        self._write_meta(key)

    def load(self, key: str) -> pd.DataFrame | None:
        """Read parquet back into a DataFrame, or return *None* if missing."""
        path = self.cache_dir / f"{key}.parquet"
        if not path.exists():
            return None
        return pd.read_parquet(path)

    # ── JSON ─────────────────────────────────────────────────────────

    def save_json(self, key: str, data: dict) -> None:
        """Write *data* to ``{key}.json`` and create a companion meta file."""
        path = self.cache_dir / f"{key}.json"
        with open(path, "w") as f:
            json.dump(data, f)
        self._write_meta(key)

    def load_json(self, key: str) -> dict | None:
        """Read JSON back into a dict, or return *None* if missing."""
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)

    # ── Staleness ────────────────────────────────────────────────────

    def is_stale(self, key: str) -> bool:
        """Return True if meta is missing or the cached entry is older than *max_age_hours*."""
        meta_path = self.cache_dir / f"{key}.meta.json"
        if not meta_path.exists():
            return True
        with open(meta_path) as f:
            meta = json.load(f)
        saved_at = datetime.fromisoformat(meta["saved_at"])
        age_hours = (datetime.now(timezone.utc) - saved_at).total_seconds() / 3600
        return age_hours > self.max_age_hours

    # ── Internal ─────────────────────────────────────────────────────

    def _write_meta(self, key: str) -> None:
        meta_path = self.cache_dir / f"{key}.meta.json"
        meta = {"saved_at": datetime.now(timezone.utc).isoformat()}
        with open(meta_path, "w") as f:
            json.dump(meta, f)
