"""
LOCALIZADOR MEJORADO FRANCIA (AMF / ESEF / XBRL.org) - ARGOS MOTOR
========================================================================
Consulta la API filings.xbrl.org con paginación completa para Francia.
Genera un mapa real de disponibilidad por año y tipo de extracción (ESEF vs crawler).

ANTES (master_universe_fr.json v1.0.0): 39 entidades locales
DESPUÉS (este script): Consulta real a API oficial sin hardcodear empresas.

Uso:
    python ARGOS_MOTOR/descarga/fr_france/localizador_fr_mejorado.py
    python ARGOS_MOTOR/descarga/fr_france/localizador_fr_mejorado.py --desde 2018
"""

import json
import time
import argparse
import urllib.request
from pathlib import Path
from collections import defaultdict

XBRL_API = "https://filings.xbrl.org/api/filings"
CONFIG_PATH = Path(__file__).parent / 'config_fr.json'

def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    return {"user_agent": "ARGOS-Compliance/1.0"}

def fetch_all_fr_filings_from_xbrl(desde_year: int = 2017):
    """
    Descarga la totalidad de filings FR disponibles en filings.xbrl.org
    usando paginación exhaustiva. SIN límite de empresas ni hardcoding.
    """
    config = load_config()
    ua = config.get('user_agent', 'ARGOS-Compliance/1.0')
    headers = {
        'User-Agent': ua,
        'Accept': 'application/json'
    }

    all_filings = []
    page = 1
    page_size = 200  # Máximo permitido por la API

    print(f"=== LOCALIZADOR MEJORADO FRANCIA (XBRL.org API) ===")
    print(f"Consultando filings con country=FR desde {desde_year} en adelante...")
    print(f"Endpoint: {XBRL_API}?filter[country]=FR")
    print()

    while True:
        url = f"{XBRL_API}?filter[country]=FR&page[size]={page_size}&page[number]={page}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status != 200:
                    print(f"[STOP] HTTP {resp.status} en página {page}")
                    break
                data = json.loads(resp.read().decode('utf-8'))
                items = data.get('data', [])

                if not items:
                    print(f"[FIN] Página {page} vacía. Paginación completada.")
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
                    lei = pkg_url.strip('/').split('/')[0].upper() if pkg_url else attrs.get('entity', {}).get('identifier', 'UNKNOWN')
                    entity_name = attrs.get('entity', {}).get('name', 'Unknown')
                    if not entity_name:
                        # Intentar desde relaciones
                        rels = item.get('relationships', {})
                        ent = rels.get('entity', {}).get('data', {})
                        entity_name = ent.get('attributes', {}).get('name', 'Unknown') if isinstance(ent, dict) else 'Unknown'

                    all_filings.append({
                        'lei': lei,
                        'entity_name': entity_name,
                        'year': year,
                        'period_end': period_end,
                        'package_url': pkg_url,
                        'has_package': bool(pkg_url),
                    })

                print(f"  Página {page:03d}: {len(items)} filings recibidos | Acumulados válidos: {len(all_filings)}")

                if len(items) < page_size:
                    print(f"[FIN] Última página ({page}) con {len(items)} items.")
                    break

                page += 1
                time.sleep(0.5)  # Pausa respetuosa

        except Exception as e:
            print(f"[ERROR] Excepción en página {page}: {e}")
            break

    return all_filings


def analyze_filings(filings: list):
    """Analiza y desglosa por año."""
    by_year = defaultdict(lambda: {'esef_paquete': set(), 'solo_metadata': set()})

    for f in filings:
        year = f['year']
        lei = f['lei']
        if f['has_package']:
            by_year[year]['esef_paquete'].add(lei)
        else:
            by_year[year]['solo_metadata'].add(lei)

    return by_year


def print_report(by_year: dict, filings: list):
    print()
    print("=" * 80)
    print("  RESULTADO: FILINGS ESEF OFICIALES LOCALIZADOS EN XBRL.ORG (PAÍS: FR)")
    print("=" * 80)
    print(f"  {'AÑO':<8} {'ESEF (paquete ZIP)':<24} {'Solo metadatos':<20} {'TOTAL':<10} TIPO EXTRACCIÓN")
    print(f"  {'-'*8} {'-'*24} {'-'*20} {'-'*10} {'-'*20}")

    total_esef = 0
    total_meta = 0
    for year in sorted(by_year.keys()):
        e = len(by_year[year]['esef_paquete'])
        m = len(by_year[year]['solo_metadata'])
        tipo = "ESEF (ZIP directo)" if e > 0 else "Crawler / Manual" if m > 0 else "Sin datos"
        print(f"  {year:<8} {e:<24} {m:<20} {e+m:<10} {tipo}")
        total_esef += e
        total_meta += m

    print(f"  {'-'*80}")
    print(f"  {'TOTAL':<8} {total_esef:<24} {total_meta:<20} {total_esef+total_meta:<10}")
    print()

    all_leis = set(f['lei'] for f in filings)
    print(f"  Entidades únicas con LEI localizadas en XBRL.org para FR: {len(all_leis)}")
    print()
    print("  COMPARATIVA CON UNIVERSO ACTUAL:")
    print(f"    master_universe_fr.json v1.0.0 = 39 entidades (CAC40: 34, SBF120: 5)")
    print(f"    Resultado real XBRL.org          = {len(all_leis)} entidades con filings activos")
    delta = len(all_leis) - 39
    signo = '+' if delta >= 0 else ''
    print(f"    Delta                            = {signo}{delta} entidades")
    print()
    print("  NOTA: 39 entidades es INSUFICIENTE.")
    print("  El CAC 40 tiene 40 componentes + el SBF 120 incluye 120 valores.")
    print("  Además se excluyeron 8 del PENDING_REVIEW (Airbus/NL, Stellantis/NL,")
    print("  STMicro/NL, ArcelorMittal/LU, Eurofins/LU, URW/SIIC, Gecina/SIIC, Covivio/SIIC).")
    print("  La consulta real revela el universo verdadero accesible via ESEF.")
    print("=" * 80)

    # Guardar resultado JSON
    out_path = Path("ARGOS_MOTOR/data/catalogs/LOCALIZADOR_FR_MEJORADO.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "generado_en": __import__('datetime').datetime.now().isoformat(),
        "total_entidades_unicas": len(all_leis),
        "universo_previo_master_json": 39,
        "delta": len(all_leis) - 39,
        "por_año": {
            str(y): {
                "esef_paquete": len(by_year[y]['esef_paquete']),
                "solo_metadata": len(by_year[y]['solo_metadata']),
                "total": len(by_year[y]['esef_paquete']) + len(by_year[y]['solo_metadata']),
                "tipo_extraccion": "ESEF" if len(by_year[y]['esef_paquete']) > 0 else "CRAWLER"
            }
            for y in sorted(by_year.keys())
        }
    }
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\n  Resumen guardado en: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Localizador mejorado de filings Francia via XBRL.org")
    parser.add_argument('--desde', type=int, default=2017, help="Año de inicio del análisis (default: 2017)")
    args = parser.parse_args()

    filings = fetch_all_fr_filings_from_xbrl(desde_year=args.desde)
    if not filings:
        print("[ALERTA] No se obtuvieron filings. Verificar conectividad o disponibilidad de la API.")
        return

    by_year = analyze_filings(filings)
    print_report(by_year, filings)


if __name__ == '__main__':
    main()
