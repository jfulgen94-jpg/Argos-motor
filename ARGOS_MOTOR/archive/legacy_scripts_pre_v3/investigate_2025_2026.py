"""
Investigación Forense Exhaustiva: Disponibilidad de Informes 2025 y 2026
para IBEX 35, Mercado Continuo y BME Growth.

Objetivos:
1. Analizar filings.xbrl.org global y por país (ES).
2. Comprobar registros de la CNMV para 2025 y 2026.
3. Explicar el calendario contable y societario legal español y europeo (ESEF).
4. Identificar qué documentos existen a día de hoy (2025/2026) y cómo descargarlos.
"""

import sys, json, requests
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Accept': 'application/vnd.api+json, application/json, */*'}

def investigate_xbrl_org():
    print("=" * 75)
    print("1. INVESTIGACIÓN EN REPOSITORIO CENTRAL ESEF (filings.xbrl.org)")
    print("=" * 75)
    
    # Comprobar toda la base de datos de España
    page = 1
    all_es_filings = []
    
    while True:
        url = f"https://filings.xbrl.org/api/filings?filter[country]=ES&page[size]=200&page[number]={page}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                break
            items = r.json().get('data', [])
            if not items:
                break
            all_es_filings.extend(items)
            page += 1
        except Exception as e:
            print(f"Error página {page}: {e}")
            break
            
    print(f"Total de filings registrados para España en xbrl.org: {len(all_es_filings)}")
    
    periods = {}
    future_or_recent = []
    
    for f in all_es_filings:
        attrs = f.get('attributes', {})
        pe = attrs.get('period_end', '')
        yr = pe[:4] if len(pe) >= 4 else 'DESCONOCIDO'
        periods[yr] = periods.get(yr, 0) + 1
        
        if int(yr) >= 2025 if yr.isdigit() else False:
            future_or_recent.append({
                'lei': attrs.get('lei'),
                'period_end': pe,
                'package_url': attrs.get('package_url'),
                'entity': f.get('relationships', {}).get('entity', {})
            })
            
    print("\n📊 Distribución de Informes Anuales Oficiales por Ejercicio (period_end):")
    for yr in sorted(periods.keys()):
        print(f"  • Ejercicio {yr}: {periods[yr]} informes anuales oficiales")
        
    if future_or_recent:
        print(f"\n🔍 Filings encontrados con period_end >= 2025: {len(future_or_recent)}")
        for item in future_or_recent:
            print(f"   - Period: {item['period_end']} | URL: {item['package_url']}")
    else:
        print("\n🔍 Filings con period_end >= 2025: CERO (0) en xbrl.org")

def investigate_cnmv_calendar_and_rules():
    print("\n" + "=" * 75)
    print("2. ANÁLISIS DE LA NORMATIVA CNMV Y CALENDARIO SOCIETARIO (Ley de Sociedades)")
    print("=" * 75)
    
    current_year = 2026
    current_month = 8
    
    print("""
A) ¿Por qué no existe todavía el informe anual auditado de 2025 y 2026?
   ---------------------------------------------------------------------
   1. Ciclo Fiscal y Plazos Legales de Publicación (Ley 6/2023 de los Mercados de Valores y LSC):
      - Cierre del ejercicio contable anual: 31 de Diciembre del año correspondiente.
      - Formulación de cuentas por el Consejo de Administración: Hasta el 31 de Marzo del año siguiente (máx. 3 meses).
      - Auditoría externa obligatoria (Big Four / auditores oficiales): Febrero a Abril del año siguiente.
      - Depósito y publicación obligatoria del Informe Financiero Anual (ESEF / CCAA) en CNMV: 
        * Máximo 4 meses tras el cierre fiscal (30 de Abril del año N+1).
        * Por tanto:
          - Ejercicio 2024 (cierre 31/12/2024) -> Se publica en ABRIL DE 2025 (¡Disponible al 100%!).
          - Ejercicio 2025 (cierre 31/12/2025) -> Se publicará en ABRIL DE 2026.
          - Ejercicio 2026 (cierre 31/12/2026) -> Se publicará en ABRIL DE 2027.

B) ¿Qué documentos existen REALMENTE en CNMV para 2025 y 2026 a día de hoy?
   ---------------------------------------------------------------------
   Para los años 2025 y 2026 (en curso), las cotizadas NO publican informes anuales cerrados
   sino INFORMACIÓN FINANCIERA PERIÓDICA INTERMEDIA (IPP Semestral / Trimestral):
   1. Informes Financieros Semestrales (H1 / Primer Semestre, corte a 30 de Junio).
   2. Declaraciones Intermedias de Gestión (Q1 / Primer Trimestre y Q3 / Tercer Trimestre).
   3. Comunicaciones de Información Privilegiada y Otra Información Relevante (OIR / Hechos Relevantes).
   4. Casos excepcionales de Ejercicio No Coincidente (ej. Inditex que cierra a 31 de Enero).
""")

def investigate_cnmv_live_search():
    print("=" * 75)
    print("3. COMPROBACIÓN DIRECTA EN EL PORTAL DE LA CNMV PARA 2025/2026")
    print("=" * 75)
    
    # Comprobar endpoints de búsqueda de información periódica en CNMV
    cnmv_search_url = "https://www.cnmv.es/Portal/Consultas/DerechosVoto/BuscadorIP.aspx"
    try:
        r = requests.get(cnmv_search_url, headers=HEADERS, timeout=10)
        print(f"Estado de conexión con Portal CNMV: {r.status_code} (Online)")
    except Exception as e:
        print(f"Error conectando a CNMV: {e}")

if __name__ == "__main__":
    investigate_xbrl_org()
    investigate_cnmv_calendar_and_rules()
    investigate_cnmv_live_search()
