"""
MOTOR DE DESCARGA DIRECTA A DISCO D: - ARGOS / STATER (ESPAÑA)
Descarga los 120 filings ESEF oficiales identificados y los sella en:
D:/ARGOS_DATA/raw/ES_CNMV/INFORMES_ANUALES_COMPLETOS/
"""

import os
import sys
import time
import json
import hashlib
import requests
from pathlib import Path
from datetime import datetime

DEST_BASE = Path("D:/ARGOS_DATA/raw/ES_CNMV/INFORMES_ANUALES_COMPLETOS")
UNIVERSE_PATH = Path("ARGOS_MOTOR/config/master_universe_es.json")
MANIFEST_OUT = Path("D:/ARGOS_DATA/raw/ES_CNMV/MANIFEST_DOWNLOAD_D_DRIVE.json")

def calculate_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def check_magic_bytes(filepath):
    with open(filepath, 'rb') as f:
        header = f.read(16)
    if header.startswith(b'PK\x03\x04'):
        return 'ZIP_ESEF'
    if header.startswith(b'%PDF'):
        return 'PDF'
    return 'UNKNOWN'

def run():
    print("=================================================================")
    print("=== INICIANDO DESCARGA REAL DE FILINGS ESEF HACIA DISCO D: ===")
    print("=================================================================")
    print(f"Destino: {DEST_BASE}")

    # 1. Cargar universo y construir mapeo de LEI
    data = json.loads(UNIVERSE_PATH.read_text(encoding='utf-8'))
    companies = data.get('companies', {})
    lei_to_comp = {c.get('lei', '').upper(): (t, c) for t, c in companies.items() if c.get('lei')}
    
    # Aliases y casos de LEI no estándar
    lei_to_comp['549300TTCXZOGZM2EY83'] = ('ITX', {'cif_nif': 'A15075062', 'name_legal': 'Industria de Diseno Textil SA'})

    # 2. Descubrir filings disponibles en ESEF España
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; ARGOS_MOTOR/3.0; Data-Collector)'})

    url = 'https://filings.xbrl.org/api/filings?filter[country]=ES&page[size]=200'
    to_download = []
    page = 1

    print("Sincronizando índice maestro de filings ESEF España...")
    while True:
        try:
            r = session.get(f'{url}&page[number]={page}', timeout=15).json()
            items = r.get('data', [])
            if not items: break
            for item in items:
                attrs = item['attributes']
                pkg = attrs.get('package_url')
                if pkg:
                    lei = pkg.strip('/').split('/')[0].upper()
                    period = attrs.get('period_end', '')
                    year = period[:4]
                    if lei in lei_to_comp:
                        t, c_info = lei_to_comp[lei]
                        cif = c_info.get('cif_nif', 'UNKNOWN')
                        target_dir = DEST_BASE / year / f'{t}-{cif}'
                        target_file = target_dir / f'{t}_{year}_esef.zip'
                        # Comprobar si ya existe en D:
                        if not target_file.exists():
                            to_download.append({
                                'ticker': t,
                                'cif': cif,
                                'name': c_info.get('name_legal', t),
                                'year': year,
                                'lei': lei,
                                'url': f'https://filings.xbrl.org{pkg}',
                                'target_file': target_file
                            })
            if len(items) < 200: break
            page += 1
        except Exception as e:
            print(f"Aviso en sincronización pág {page}: {e}")
            break

    print(f"Total filings listos para descarga a D: : {len(to_download)}")
    manifest = []
    success = 0
    failed = 0

    for idx, item in enumerate(to_download, 1):
        t = item['ticker']
        y = item['year']
        pkg_url = item['url']
        target_f = item['target_file']

        print(f"[{idx}/{len(to_download)}] Descargando {t} ({y}) -> {target_f.name}...")
        try:
            target_f.parent.mkdir(parents=True, exist_ok=True)
            tmp_f = target_f.with_suffix('.tmp')

            with session.get(pkg_url, stream=True, timeout=45) as resp:
                if resp.status_code == 200:
                    with open(tmp_f, 'wb') as f:
                        for chunk in resp.iter_content(chunk_size=131072):
                            if chunk:
                                f.write(chunk)

                    magic = check_magic_bytes(tmp_f)
                    if magic == 'ZIP_ESEF':
                        tmp_f.replace(target_f)
                        sha = calculate_sha256(target_f)
                        size_mb = target_f.stat().st_size / (1024 * 1024)
                        print(f"   [OK -> D:] {size_mb:.2f} MB | SHA256: {sha[:12]}...")
                        success += 1
                        manifest.append({
                            'ticker': t,
                            'lei': item['lei'],
                            'year': y,
                            'sha256': sha,
                            'size_bytes': target_f.stat().st_size,
                            'path': str(target_f),
                            'status': 'VALID_ORIGINAL_SEALED',
                            'timestamp': datetime.now().isoformat()
                        })
                    else:
                        print(f"   [CUARENTENA] Fichero no es ZIP ESEF: {magic}")
                        if tmp_f.exists(): tmp_f.unlink()
                        failed += 1
                else:
                    print(f"   [HTTP {resp.status_code}] Fallo en servidor remoto.")
                    if tmp_f.exists(): tmp_f.unlink()
                    failed += 1
        except Exception as e:
            print(f"   [ERROR] Excepción: {e}")
            failed += 1

        time.sleep(0.5)

    # Guardar manifiesto sellado en D:
    MANIFEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding='utf-8')

    print("\n=================================================================")
    print("=== DESCARGA A DISCO D: COMPLETADA ===")
    print(f"Exitosos descargados y sellados en D: : {success}")
    print(f"Fallidos: {failed}")
    print(f"Manifiesto guardado en: {MANIFEST_OUT}")

if __name__ == '__main__':
    run()
