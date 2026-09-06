"""
Prueba de conexión avanzada con Portal CNMV para IPP / Semestrales / Trimestrales 2025/2026.
"""

import sys, requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br'
}

session = requests.Session()
session.headers.update(headers)

def test_cnmv():
    try:
        r_home = session.get('https://www.cnmv.es/portal/home.aspx', timeout=15)
        print(f"1. Home CNMV: Status {r_home.status_code}")
    except Exception as e:
        print(f"Error home: {e}")
        
    try:
        # Consulta de IPP para Banco Santander (NIF: A39000013)
        url_ipp = 'https://www.cnmv.es/Portal/Consultas/IPP/ResultadoBusquedaIPP.aspx?nif=A39000013'
        r_ipp = session.get(url_ipp, timeout=15)
        print(f"2. IPP Santander: Status {r_ipp.status_code} (Longitud: {len(r_ipp.content)} bytes)")
        if r_ipp.status_code == 200:
            soup = BeautifulSoup(r_ipp.text, 'html.parser')
            table = soup.find('table')
            if table:
                rows = table.find_all('tr')
                print(f"   Filas encontradas en tabla: {len(rows)}")
                for r in rows[:6]:
                    print("   -", " | ".join(c.get_text(strip=True) for c in r.find_all(['td', 'th'])))
    except Exception as e:
        print(f"Error IPP: {e}")

if __name__ == "__main__":
    test_cnmv()
