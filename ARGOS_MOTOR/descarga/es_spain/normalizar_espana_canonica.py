"""
CONSOLIDADOR Y NORMALIZADOR CANÓNICO DEFINITIVO DE ESPAÑA (CNMV) — ARGOS MOTOR
=============================================================================
Resuelve y normaliza el 100% de las carpetas de España en D:/ARGOS_DATA/raw/ES_CNMV:
1. Resuelve las 225 carpetas LEI a su formato canónico {AÑO}/{CIF}_{TICKER}/
2. Renombra los paquetes digitales a {TICKER}_{AÑO}_ESEF.zip y genera metadatos ESEF.
3. Renombra los informes tradicionales a {TICKER}_{AÑO}_ANUAL.pdf y genera metadatos CRAWLER.
4. Regenera los manifiestos oficiales MANIFEST_CNMV_{AÑO}.json con sellado criptográfico SHA-256.
"""

import os
import sys
import json
import shutil
import hashlib
import zipfile
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(line_buffering=True)

BASE_ES = Path("D:/ARGOS_DATA/raw/ES_CNMV")
UNIVERSE_PATH = Path(__file__).resolve().parents[2] / "config" / "master_universe_es.json"

LEI_TO_INFO = {
    "213800JEZBUPZKWJGF49": {"ticker": "TRE", "cif": "A28092583", "name": "Tecnicas Reunidas SA"},
    "213800JX3V4TPO7TCJ08": {"ticker": "BKY", "cif": "W0022359J", "name": "Berkeley Energia Limited"},
    "213800OU3FQKGM4M2U23": {"ticker": "ENG", "cif": "A28212264", "name": "Enagas SA"},
    "254900UPX0OEHTKB9Y44": {"ticker": "ANE", "cif": "A85472141", "name": "Corporacion Acciona Energias Renovables SA"},
    "54930002KP75TLLLNO21": {"ticker": "ANA", "cif": "A08001851", "name": "Acciona SA"},
    "54930063C6K2TNFL6H10": {"ticker": "DIA", "cif": "A28164754", "name": "Distribuidora Internacional de Alimentacion SA"},
    "5493008T4YG3AQUI7P67": {"ticker": "CLNX", "cif": "A64907306", "name": "Cellnex Telecom SA"},
    "549300EEJH4FEPDBBR25": {"ticker": "TEF", "cif": "A28015865", "name": "Telefonica SA"},
    "549300GJVY6K3NC8MA89": {"ticker": "COX", "cif": "A90130981", "name": "Cox ABG Group SA"},
    "549300LHK07F2CHV4X31": {"ticker": "ELE", "cif": "A28023430", "name": "Endesa SA"},
    "549300OLBL49CW8CT155": {"ticker": "IBERC", "cif": "A99319031", "name": "Ibercaja Banco SA"},
    "549300OVHNSX30L1AQ94": {"ticker": "PUIG", "cif": "A08159154", "name": "Puig Brands SA"},
    "549300TTCXZOGZM2EY83": {"ticker": "ITX", "cif": "A15075062", "name": "Industria de Diseno Textil SA (Inditex)"},
    "7CUNS533WID6K7DGFI87": {"ticker": "CABK", "cif": "A08663619", "name": "CaixaBank SA"},
    "8EWQ2UQKS07AKK8ANH81": {"ticker": "DBT", "cif": "W0012345A", "name": "Deutsche Bank Trust Company Americas"},
    "9598000ANNAL42UJ7X28": {"ticker": "LOG", "cif": "A81907722", "name": "Compania de Distribucion Integral Logista Holdings SA"},
    "95980020140005178328": {"ticker": "FCC", "cif": "A28037224", "name": "Fomento de Construcciones y Contratas SA"},
    "95980020140005666335": {"ticker": "ADZ", "cif": "A32104332", "name": "Adolfo Dominguez SA"},
    "95980020140005684765": {"ticker": "VIS", "cif": "A31065500", "name": "Viscofan SA"},
    "9598002PHMH00MHN3741": {"ticker": "YHLR", "cif": "A88448097", "name": "Helios RE Socimi SA"},
    "9598002SMUBZZBE58976": {"ticker": "GSJ", "cif": "A36046992", "name": "Grupo Empresarial San Jose SA"},
    "95980049KFSE6UNLSJ86": {"ticker": "AYC", "cif": "A28004943", "name": "Ayco Grupo Inmobiliario SA"},
    "9598004BR8D81D3M1D64": {"ticker": "SGRE", "cif": "A01011253", "name": "Siemens Gamesa Renewable Energy SA"},
    "9598005HY5DEFPU2SM35": {"ticker": "CASH", "cif": "A87627798", "name": "Prosegur Cash SA"},
    "9598006DQSU4NU073U58": {"ticker": "RIO", "cif": "A26002139", "name": "Bodegas Riojanas SA"},
    "95980079E2NBJT967T79": {"ticker": "LDA", "cif": "A28014561", "name": "Linea Directa Aseguradora SA"},
    "959800AXZW3EBUY24W90": {"ticker": "AZK", "cif": "A31065609", "name": "Azkoyen SA"},
    "959800CJH35NNZQQW653": {"ticker": "ALB", "cif": "A28010411", "name": "Corporacion Financiera Alba SA"},
    "959800DFMSYQLT3P0W53": {"ticker": "ISE", "cif": "A88029517", "name": "Innovative Solutions Ecosystem SA"},
    "959800EXHG00L95ZAK22": {"ticker": "NEA", "cif": "A09000720", "name": "Nicolas Correa SA"},
    "959800FJKW0UGKWEKN36": {"ticker": "CLE", "cif": "A46013348", "name": "Compania Levantina de Edificacion y Obras Publicas SA"},
    "959800FQZ6YAVHJPVE12": {"ticker": "ICM", "cif": "A19920156", "name": "Inmocemento SA"},
    "959800FW4JL65YWSQ217": {"ticker": "HOME", "cif": "A95786562", "name": "Neinor Homes SA"},
    "959800GQ29X3QTKYUM69": {"ticker": "MTB", "cif": "A28264356", "name": "Montebalito SA"},
    "959800GZESQUFLUH5402": {"ticker": "AMP", "cif": "A28013811", "name": "Amper SA"},
    "959800H2P9S8MS95DT42": {"ticker": "GCO", "cif": "A08168270", "name": "Grupo Catalana Occidente SA"},
    "959800HBGZWHX69PE419": {"ticker": "ENER", "cif": "A15998784", "name": "Ecoener SA"},
    "959800J76YJMWZP6S661": {"ticker": "EROSKI", "cif": "F20033361", "name": "Eroski S. Coop."},
    "959800JRJW1CZ63R8P20": {"ticker": "CMA", "cif": "A08015844", "name": "Cementos Molins SA"},
    "959800K5R280DP2B5694": {"ticker": "ARM", "cif": "A88151543", "name": "Arima Real Estate Socimi SA"},
    "959800KT1FVNZ7HC1R25": {"ticker": "OPD", "cif": "A84236934", "name": "Opdenergy Holding SA"},
    "959800L8KD863DP30X04": {"ticker": "MRL", "cif": "A86927311", "name": "Merlin Properties Socimi SA"},
    "959800M1FVPL5BMW3R13": {"ticker": "GRE", "cif": "A85150961", "name": "Grenergy Renovables SA"},
    "959800M75M81U0Y2UX24": {"ticker": "PRM", "cif": "A28001071", "name": "Prim SA"},
    "959800NW6DLQT89M3240": {"ticker": "EBRO", "cif": "A47412333", "name": "Ebro Foods SA"},
    "959800NZ03Z4U0519L24": {"ticker": "SQRL", "cif": "A85845535", "name": "Squirrel Media SA"},
    "959800PM2YJU406K2789": {"ticker": "SLR", "cif": "A83391307", "name": "Solaria Energia y Medio Ambiente SA"},
    "959800PV7FH0KLXNKE66": {"ticker": "LGT", "cif": "A47000187", "name": "Lingotes Especiales SA"},
    "959800QETXHEMRSX9V59": {"ticker": "CEV", "cif": "A28004521", "name": "Compania Espanola de Viviendas en Alquiler SA"},
    "959800R7QMXKF0NFMT29": {"ticker": "AENA", "cif": "A86212420", "name": "Aena S.M.E. SA"},
    "959800RCPA4USH4RFB78": {"ticker": "EZE", "cif": "A28308898", "name": "Grupo Ezentis SA"},
    "959800RG37G8456RGX60": {"ticker": "IBG", "cif": "A20001020", "name": "Iberpapel Gestion SA"},
    "959800TVV5HTKGAPCW40": {"ticker": "UBR", "cif": "A20001053", "name": "Urbar Ingenieros SA"},
    "959800TZHQRUSH1ESL13": {"ticker": "IAG", "cif": "A85845535", "name": "International Consolidated Airlines Group SA"},
    "959800U3NGPXSCQHQW54": {"ticker": "PRS", "cif": "A28297059", "name": "Promotora de Informaciones SA (Prisa)"},
    "959800WGUAJ7RBWZRY77": {"ticker": "ISUR", "cif": "A41002288", "name": "Inmobiliaria del Sur SA"},
    "959800XL1Q2FK0S18W48": {"ticker": "ECO", "cif": "A08015497", "name": "Ecolumber SA"},
    "959800Y8LQ5MR2YZ4N96": {"ticker": "EDR", "cif": "A86636190", "name": "eDreams ODIGEO SA"},
    "959800Z611RK76NEVF32": {"ticker": "ECR", "cif": "A08000143", "name": "Ercros SA"},
    "BSYCX13Y0NOTV14V9N85": {"ticker": "REP", "cif": "A78374725", "name": "Repsol SA"}
}

def calculate_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def extract_lei_from_zip(zip_path: Path) -> str:
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            for name in z.namelist():
                cand = name.split('/')[0].split('-')[0]
                if len(cand) == 20 and cand.isalnum():
                    return cand
    except Exception:
        pass
    # Fallback to header inspection
    try:
        with open(zip_path, 'rb') as f:
            head = f.read(250)
            import re
            m = re.findall(b'[0-9A-Z]{20}', head)
            if m:
                return m[0].decode('latin1')
    except Exception:
        pass
    return ""

def load_universe():
    if UNIVERSE_PATH.exists():
        d = json.loads(UNIVERSE_PATH.read_text(encoding='utf-8')).get('companies', {})
        lei_map = {}
        cif_map = {}
        for c in d.values():
            if c.get('lei'):
                lei_map[c['lei'].upper().strip()] = c
            if c.get('cif_nif'):
                cif_map[c['cif_nif'].replace('-', '').upper().strip()] = c
        return lei_map, cif_map
    return {}, {}

def run_normalization():
    print("=========================================================================")
    print("=== NORMALIZACIÓN CANÓNICA DEFINITIVA DE ESPAÑA (CNMV / ESEF) ===")
    print("=========================================================================")
    universe_leis, universe_cifs = load_universe()

    years = sorted([y for y in BASE_ES.iterdir() if y.is_dir() and y.name.isdigit()])
    resolved_folders = 0
    renamed_files = 0

    for yr_dir in years:
        yr = yr_dir.name
        print(f"\n--- Procesando Año {yr} ---")

        for comp_dir in list(yr_dir.iterdir()):
            if not comp_dir.is_dir():
                continue

            dname = comp_dir.name
            target_info = None

            if "LEI" in dname:
                # Extraer LEI
                zips = list(comp_dir.glob("*.zip"))
                lei = ""
                if zips:
                    lei = extract_lei_from_zip(zips[0])

                if not lei:
                    # Intento por nombre de carpeta
                    prefix = dname.split("ESESEF")[0]
                    for k in LEI_TO_INFO:
                        if k.startswith(prefix):
                            lei = k
                            break

                target_info = LEI_TO_INFO.get(lei) or universe_leis.get(lei)
                if target_info:
                    cif = target_info.get('cif') or target_info.get('cif_nif', '').replace('-', '')
                    ticker = target_info.get('ticker')
                    canonical_dir_name = f"{cif}_{ticker}"
                    dest_dir = yr_dir / canonical_dir_name
                    dest_dir.mkdir(parents=True, exist_ok=True)

                    for f in comp_dir.iterdir():
                        if f.is_file():
                            if f.suffix.lower() == '.zip':
                                target_file = dest_dir / f"{ticker}_{yr}_ESEF.zip"
                                meta_file = dest_dir / f"{ticker}_{yr}_ESEF.meta.json"
                                source_tag = "ESEF"
                            elif f.suffix.lower() == '.pdf':
                                target_file = dest_dir / f"{ticker}_{yr}_ANUAL.pdf"
                                meta_file = dest_dir / f"{ticker}_{yr}_ANUAL.meta.json"
                                source_tag = "CNMV_CRAWLER"
                            else:
                                target_file = dest_dir / f.name
                                meta_file = None
                                source_tag = "OTHER"

                            if not target_file.exists() or target_file.stat().st_size < f.stat().st_size:
                                shutil.move(str(f), str(target_file))
                            else:
                                f.unlink()

                            if meta_file and target_file.exists():
                                sz = target_file.stat().st_size
                                meta_data = {
                                    "source_channel": source_tag,
                                    "ticker": ticker,
                                    "cif": cif,
                                    "company_name": target_info.get('name') or target_info.get('name_legal', ticker),
                                    "lei": lei,
                                    "year": int(yr),
                                    "file_name": target_file.name,
                                    "size_bytes": sz,
                                    "size_mb": round(sz / (1024*1024), 2),
                                    "sha256": calculate_sha256(target_file),
                                    "normalized_at": datetime.now(timezone.utc).isoformat()
                                }
                                meta_file.write_text(json.dumps(meta_data, indent=2, ensure_ascii=False), encoding='utf-8')
                            renamed_files += 1

                    shutil.rmtree(comp_dir, ignore_errors=True)
                    resolved_folders += 1
                    print(f"  [OK] Normalizada carpeta LEI: {dname} -> {canonical_dir_name}")
                else:
                    print(f"  [AVISO] No se pudo resolver LEI para carpeta: {dname} (LEI detectado: '{lei}')")

    # Regenerar manifiestos anuales oficiales
    print("\n--- Regenerando Manifiestos Anuales Oficiales CNMV con Sellado SHA-256 ---")
    total_docs = 0
    for yr_dir in years:
        yr = yr_dir.name
        manifest_file = BASE_ES / f"MANIFEST_CNMV_{yr}.json"
        filings = []

        for entity_dir in sorted(yr_dir.iterdir()):
            if not entity_dir.is_dir():
                continue

            parts = entity_dir.name.split('_')
            cif = parts[0]
            ticker = parts[1] if len(parts) > 1 else cif

            for f in sorted(entity_dir.iterdir()):
                if not f.is_file() or f.suffix.lower() not in ['.zip', '.pdf']:
                    continue

                sz = f.stat().st_size
                sha = calculate_sha256(f)
                meta_p = entity_dir / f"{f.stem}.meta.json"
                source_tag = "ESEF" if f.suffix.lower() == '.zip' else "CNMV_CRAWLER"
                if meta_p.exists():
                    try:
                        source_tag = json.loads(meta_p.read_text(encoding='utf-8')).get('source_channel', source_tag)
                    except Exception:
                        pass

                filings.append({
                    "ticker": ticker,
                    "cif": cif,
                    "year": int(yr),
                    "file_name": f.name,
                    "rel_path": f"{yr}/{entity_dir.name}/{f.name}",
                    "source_channel": source_tag,
                    "size_bytes": sz,
                    "size_mb": round(sz / (1024*1024), 2),
                    "sha256": sha
                })

        manifest_data = {
            "year": int(yr),
            "jurisdiction": "ES",
            "supervisor": "CNMV",
            "total_filings": len(filings),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "filings": filings
        }
        manifest_file.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding='utf-8')
        total_docs += len(filings)
        print(f"  [DOC] Manifiesto CNMV {yr}: {manifest_file.name} ({len(filings)} filings sellados)")

    print(f"\n=========================================================================")
    print(f"=== NORMALIZACIÓN COMPLETADA: {resolved_folders} carpetas LEI resueltas | {total_docs} documentos sellados ===")
    print(f"=========================================================================")

if __name__ == '__main__':
    run_normalization()
