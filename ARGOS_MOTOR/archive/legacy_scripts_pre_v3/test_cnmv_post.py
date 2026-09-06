"""
Extractor de IPP Semestrales / Trimestrales CNMV con gestión de ViewState y Sesión.
"""

import sys, requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

session = requests.Session()
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    'Origin': 'https://www.cnmv.es',
    'Referer': 'https://www.cnmv.es/Portal/Consultas/DerechosVoto/BuscadorIP.aspx'
}
session.headers.update(headers)

def test_form_post():
    form_url = 'https://www.cnmv.es/Portal/Consultas/DerechosVoto/BuscadorIP.aspx'
    try:
        r_form = session.get(form_url, timeout=15)
        print(f"1. Form Page: Status {r_form.status_code}")
        
        soup = BeautifulSoup(r_form.text, 'html.parser')
        viewstate = soup.find('input', {'id': '__VIEWSTATE'})
        eventvalidation = soup.find('input', {'id': '__EVENTVALIDATION'})
        
        vs_val = viewstate['value'] if viewstate else ''
        ev_val = eventvalidation['value'] if eventvalidation else ''
        
        print(f"   ViewState encontrado: {len(vs_val)} caracteres")
        
        # Realizar POST de búsqueda para Santander
        post_data = {
            '__VIEWSTATE': vs_val,
            '__EVENTVALIDATION': ev_val,
            'ctl00$ContentPlaceHolder1$txtNIF': 'A39000013',
            'ctl00$ContentPlaceHolder1$btnBuscar': 'Buscar'
        }
        
        r_post = session.post(form_url, data=post_data, timeout=15)
        print(f"2. Búsqueda POST Status: {r_post.status_code} (Longitud: {len(r_post.content)} bytes)")
        
        if r_post.status_code == 200:
            soup_res = BeautifulSoup(r_post.text, 'html.parser')
            # Buscar enlaces a documentos o filas
            links = soup_res.find_all('a', href=True)
            doc_links = [l for l in links if 'verDocumento' in l['href'] or 'IPP' in l['href']]
            print(f"   Enlaces a documentos encontrados: {len(doc_links)}")
            for dl in doc_links[:10]:
                print(f"   • {dl.get_text(strip=True)} -> {dl['href']}")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_form_post()
