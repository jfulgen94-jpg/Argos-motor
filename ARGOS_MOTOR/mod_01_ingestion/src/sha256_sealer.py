"""SHA-256 Sealer — Cryptographic immutable sealing of raw files."""
import hashlib
from pathlib import Path


def seal_file(file_path: Path) -> str:
    """Return the SHA-256 hex digest of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()
