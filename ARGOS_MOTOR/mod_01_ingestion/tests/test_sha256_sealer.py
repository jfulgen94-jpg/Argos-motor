"""Tests for SHA-256 sealer — must achieve 100% coverage."""
import hashlib
import tempfile
from pathlib import Path
from mod_01_ingestion.src.sha256_sealer import seal_file


def test_sha256_seal_is_deterministic():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"STATER test content")
        tmp = Path(f.name)
    hash1 = seal_file(tmp)
    hash2 = seal_file(tmp)
    assert hash1 == hash2
    assert len(hash1) == 64
