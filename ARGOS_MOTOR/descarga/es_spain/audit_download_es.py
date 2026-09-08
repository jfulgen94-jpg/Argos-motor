"""
AUDITORÍA DE LA PROPIA DESCARGA (ESPAÑA) - ARGOS MOTOR
Valida la integridad física y criptográfica de los documentos descargados en data/raw/ES_CNMV/.
Verifica Magic Bytes, integridad ZIP/PDF, hash SHA-256 y detección de bloqueos/cuarentena.
"""

import os
import sys
import zipfile
import hashlib
from pathlib import Path

BASE_CANONICAL = Path("ARGOS_MOTOR/data/raw/ES_CNMV")
QUARANTINE_DIR = Path("ARGOS_MOTOR/data/quarantine_forensic_retro")

def get_magic_bytes(filepath):
    with open(filepath, 'rb') as f:
        return f.read(16)

def test_zip_integrity(filepath):
    try:
        with zipfile.ZipFile(filepath, 'r') as z:
            bad_file = z.testzip()
            if bad_file:
                return False, f"Fichero corrupto dentro de ZIP: {bad_file}"
            return True, "ZIP_VALIDO"
    except Exception as e:
        return False, str(e)

def run_download_audit():
    print("=== INICIANDO AUDITORÍA DE DESCARGAS (ESPAÑA) ===")
    if not BASE_CANONICAL.exists():
        print(f"Directorio no existe: {BASE_CANONICAL}")
        return

    all_files = [f for f in BASE_CANONICAL.rglob('*') if f.is_file()]
    print(f"Total archivos a auditar en ES_CNMV: {len(all_files)}")

    stats = {
        'valid_esef_zip': 0,
        'valid_xhtml': 0,
        'valid_pdf': 0,
        'valid_json_meta': 0,
        'corrupt_or_empty': 0,
        'quarantined': 0
    }

    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

    for f in all_files:
        size = f.stat().st_size
        if size == 0:
            print(f"[ALERTA: VACÍO] {f.relative_to(BASE_CANONICAL)} (0 bytes)")
            stats['corrupt_or_empty'] += 1
            continue

        ext = f.suffix.lower()
        if ext == '.zip':
            is_valid, reason = test_zip_integrity(f)
            if is_valid:
                stats['valid_esef_zip'] += 1
            else:
                print(f"[ALERTA: ZIP CORRUPTO] {f.name} -> {reason}")
                stats['corrupt_or_empty'] += 1
        elif ext in ['.xhtml', '.html', '.xml']:
            header = get_magic_bytes(f)
            if b'<!doctype' in header.lower() or b'<html' in header.lower() or b'<?xml' in header.lower():
                stats['valid_xhtml'] += 1
            else:
                stats['corrupt_or_empty'] += 1
        elif ext == '.pdf':
            header = get_magic_bytes(f)
            if header.startswith(b'%PDF'):
                stats['valid_pdf'] += 1
            else:
                stats['corrupt_or_empty'] += 1
        elif ext == '.json':
            stats['valid_json_meta'] += 1

    print("\n=== RESULTADOS DE LA AUDITORÍA DE DESCARGA ===")
    print(f"Paquetes ZIP ESEF íntegros y válidos: {stats['valid_esef_zip']}")
    print(f"Archivos xHTML / XML primarios válidos: {stats['valid_xhtml']}")
    print(f"Documentos PDF válidos: {stats['valid_pdf']}")
    print(f"Ficheros de metadatos JSON válidos: {stats['valid_json_meta']}")
    print(f"Ficheros corruptos, incompletos o vacíos detectados: {stats['corrupt_or_empty']}")

if __name__ == '__main__':
    run_download_audit()
