"""Snapshot versioning manager creating immutable daily data lake releases."""
from datetime import datetime, timezone
from pathlib import Path
import duckdb


class SnapshotManager:
    def __init__(self, lake_manager):
        self.lake = lake_manager

    def create_daily_snapshot(self, output_dir: Path) -> str:
        version_id = datetime.now(timezone.utc).strftime("v%Y%m%d")
        snapshot_path = output_dir / f"snapshot_{version_id}.parquet"
        self.lake.export_table_to_parquet("financial_panel", snapshot_path)
        return version_id
