"""
LOCALIZADOR / DIAGNÓSTICO ESPAÑA (CNMV / ESEF / XBRL.org) - ARGOS MOTOR
========================================================================
Consulta filings.xbrl.org para país ES y cruza con el master_universe_es.json.
Muestra desde cuándo hay informes, qué tipo de extracción requiere cada empresa
(ESEF directo vs. Crawler CNMV) y el número total por año.

Uso:
    python ARGOS_MOTOR/descarga/es_spain/localizador_es_diagnostico.py
    python ARGOS_MOTOR/descarga/es_spain/localizador_es_diagnostico.py --desde 2018
"""

import json
import time
import argparse
import urllib.request
from pathlib import Path
from collections import defaultdict

XBRL_API = "https://filings.xbrl.org/api/filings"
CONFIG_PATH = Path(__file__).parent / 'config_es.json'
UNIVERSE_REL = Path(__file__).resolve().parents[3] / 'ARGOS_MOTOR/config/master_universe_es.json'

def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    return {"user_agent": "ARGOS-Compliance/1.0"}

def load_universe():
    """Carga el universo de empresas ES y construye el mapa LEI -> ticker."""
    if UNIVERSE_REL.exists():
        data = json.loads(UNIVERSE_REL.read_text(encoding='utf-8'))
        companies = data.get('companies', {})
        lei_map = {}
        for ticker, info in companies.items():
            lei = info.get('lei', '').upper().strip()
            if lei:
                lei_map[lei] = ticker
        return data, lei_map
    print(f"[AVISO] No se encontró el universo en {UNIVERSE_REL}")
    return {}, {}

def fetch_all_es_filings(desde_year: int = 2017):
    """Paginación completa de filings ES en XBRL.org."""
    config = load_config()
    ua = config.get('user_agent', 'ARGOS-Compliance/1.0')
    headers = {'User-Agent': ua, 'Accept': 'application/json'}

    all_filings = []
    page = 1
    page_size = 200

    print(f"=== LOCALIZADOR / DIAGNÓSTICO ESPAÑA (XBRL.org API) ===")
    print(f"Consultando filings con country=ES desde {desde_year}...")
    print(f"Endpoint: {XBRL_API}?filter[country]=ES")
    print()

    while True:
        url = f"{XBRL_API}?filter[country]=ES&page[size]={page_size}&page[number]={page}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status != 200:
                    print(f"[STOP] HTTP {resp.status} en página {page}")
                    break
                data = json.loads(resp.read().decode('utf-8'))
                items = data.get('data', [])

                if not items:
                    print(f"[FIN] Página {page} vacía.")
                    break

                for item in items:
                    attrs = item.get('attributes', {})
                    period_end = attrs.get('period_end', '') or ''
                    year_str = period_end[:4] if period_end else ''
                    if not year_str.isdigit():
                        continue
                    year = int(year_str)
                    if year < desde_year:
                        continue

                    pkg_url = attrs.get('package_url', '') or ''
                    lei = pkg_url.strip('/').split('/')[0].upper() if pkg_url else 'UNKNOWN'
                    entity_name = attrs.get('entity', {}).get('name', '') if isinstance(attrs.get('entity'), dict) else ''

                    all_filings.append({
                        'lei': lei,
                        'entity_name': entity_name,
                        'year': year,
                        'period_end': period_end,
                        'package_url': pkg_url,
                        'has_package': bool(pkg_url),
                    })

                print(f"  Página {page:03d}: {len(items)} filings | Acumulados: {len(all_filings)}")

                if len(items) < page_size:
                    break
                page += 1
                time.sleep(0.5)

        except Exception as e:
            print(f"[ERROR] Excepción en página {page}: {e}")
            break

    return all_filings


def analyze_and_report(filings: list, universe: dict, lei_map: dict):
    by_year = defaultdict(lambda: {
        'esef_paquete': set(),  # Tienen paquete ZIP -> extracción ESEF directa
        'solo_metadata': set()  # Sin paquete -> requieren Crawler CNMV
    })

    lei_to_name = {}
    for f in filings:
        year = f['year']
        lei = f['lei']
        name = f.get('entity_name') or lei_map.get(lei, f'LEI_{lei[:8]}')
        lei_to_name[lei] = name
        if f['has_package']:
            by_year[year]['esef_paquete'].add(lei)
        else:
            by_year[year]['solo_metadata'].add(lei)

    # ---- Universo en disco vs. en XBRL ----
    total_univ = universe.get('total_entities', 0)
    segs = universe.get('segments_breakdown', {})
    all_leis_xbrl = set(f['lei'] for f in filings)

    # Empresas del universo ES con ESEF en XBRL.org
    leis_in_universe = set(lei_map.keys())
    leis_con_esef = leis_in_universe & all_leis_xbrl
    leis_sin_esef = leis_in_universe - all_leis_xbrl

    print()
    print("=" * 80)
    print("  RESULTADO: DIAGNÓSTICO ESPAÑA — INFORMES POR AÑO Y TIPO DE EXTRACCIÓN")
    print("=" * 80)
    print(f"\n  UNIVERSO master_universe_es.json: {total_univ} entidades")
    for seg, cnt in segs.items():
        print(f"    - {seg}: {cnt}")
    print()
    print(f"  {'AÑO':<8} {'ESEF (ZIP directo)':<24} {'Solo metadato/Crawler':<26} {'TOTAL':<8} INICIO INFORMES")
    print(f"  {'-'*8} {'-'*24} {'-'*26} {'-'*8} {'-'*20}")

    primer_anyo = None
    for year in sorted(by_year.keys()):
        e = len(by_year[year]['esef_paquete'])
        m = len(by_year[year]['solo_metadata'])
        total = e + m
        if total > 0 and primer_anyo is None:
            primer_anyo = year
        tipo = "ESEF directo" if e >= m else "Crawler CNMV"
        print(f"  {year:<8} {e:<24} {m:<26} {total:<8} {tipo}")

    print(f"\n  Primer año con informes detectados: {primer_anyo or 'N/A'}")
    print(f"\n  Entidades únicas localizadas en XBRL.org (ES): {len(all_leis_xbrl)}")
    print(f"  Del universo ES ({len(leis_in_universe)} con LEI):")
    print(f"    - Con ESEF en XBRL.org:    {len(leis_con_esef)} empresas  -> ESEF directo")
    print(f"    - Sin ESEF en XBRL.org:    {len(leis_sin_esef)} empresas  -> Crawler CNMV obligatorio")
    print()

    if leis_sin_esef:
        print("  Empresas del universo ES que REQUIEREN Crawler CNMV (sin ESEF en XBRL.org):")
        for lei in sorted(leis_sin_esef)[:30]:
            ticker = lei_map.get(lei, '???')
            print(f"    [{ticker}] LEI: {lei}")
        if len(leis_sin_esef) > 30:
            print(f"    ... y {len(leis_sin_esef) - 30} más.")

    print("=" * 80)

    # Guardar resultado
    out_path = Path("ARGOS_MOTOR/data/catalogs/DIAGNOSTICO_ES.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "generado_en": __import__('datetime').datetime.now().isoformat(),
        "universo_total": total_univ,
        "segmentos": segs,
        "primer_anyo_con_informes": primer_anyo,
        "entidades_xbrl_org": len(all_leis_xbrl),
        "entidades_universo_con_esef": len(leis_con_esef),
        "entidades_universo_sin_esef_crawler_cnmv": len(leis_sin_esef),
        "por_año": {
            str(y): {
                "esef_paquete": len(by_year[y]['esef_paquete']),
                "crawler_cnmv": len(by_year[y]['solo_metadata']),
                "total": len(by_year[y]['esef_paquete']) + len(by_year[y]['solo_metadata']),
                "tipo_extraccion_predominante": "ESEF" if len(by_year[y]['esef_paquete']) >= len(by_year[y]['solo_metadata']) else "CRAWLER"
            }
            for y in sorted(by_year.keys())
        }
    }
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\n  Diagnóstico guardado en: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Diagnóstico de disponibilidad de filings España")
    parser.add_argument('--desde', type=int, default=2017, help="Año de inicio (default: 2017)")
    args = parser.parse_args()

    universe, lei_map = load_universe()
    filings = fetch_all_es_filings(desde_year=args.desde)
    if not filings:
        print("[ALERTA] No se obtuvieron filings ES.")
        return
    analyze_and_report(filings, universe, lei_map)


if __name__ == '__main__':
    main()
