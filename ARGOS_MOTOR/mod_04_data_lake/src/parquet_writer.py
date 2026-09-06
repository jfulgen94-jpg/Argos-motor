"""Parquet file writer with zstandard compression and date partitioning."""
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import pandas as pd


class ParquetWriter:
    @staticmethod
    def write_dataframe(df: pd.DataFrame, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(df)
        pq.write_table(table, str(output_path), compression="zstd")
