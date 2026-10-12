"""
FASE 4 / DEFECT-08 — Telemetría estructurada JSONL con run_id / job_id / document_id.
Un único esquema (03_TELEMETRY_SCHEMA.json) para todas las autoridades.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from typing import Any, Dict, List, Optional

from mod_01_ingestion.src.unified.models import SCHEMA_VERSION, JobContext, RunContext, utc_now

REQUIRED_FIELDS = ("schema_version", "ts", "event", "run_id", "job_id", "document_id", "authority", "component")


def _redact_url(value: str) -> str:
    """U5A: en telemetría las URLs viajan sin query, fragmento ni credenciales (pueden llevar tokens o firmas)."""
    try:
        p = urlsplit(value)
    except ValueError:
        return value
    if p.scheme not in ("http", "https") or not p.hostname:
        return value
    return urlunsplit((p.scheme, p.hostname + (f":{p.port}" if p.port else ""), p.path, "", ""))


class TelemetryLogger:
    def __init__(self, directory: Path, run: RunContext):
        self.run = run
        self.path = Path(directory) / f"{run.run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def emit(self, event: str, job: Optional[JobContext], component: str, **fields: Any) -> Dict[str, Any]:
        record: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "ts": utc_now(),
            "event": event,
            "run_id": self.run.run_id,
            "job_id": job.job_id if job else None,
            "document_id": job.document_id if job else None,
            "authority": job.authority if job else None,
            "component": component,
        }
        record.update({k: (_redact_url(v) if k.endswith("url") and isinstance(v, str) else v) for k, v in fields.items()})
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
        return record

    def read_all(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
