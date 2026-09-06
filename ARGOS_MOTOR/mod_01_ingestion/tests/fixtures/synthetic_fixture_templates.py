"""
SOLO PARA TESTS. NUNCA IMPORTAR DESDE src/.

Plantillas HTML y de documentos sintéticos aisladas exclusivamente para
el banco de pruebas unitarias de detección de contenido fabricado (anti-regresión).
"""

def get_sample_synthetic_html(ticker: str = "SAN", year: int = 2024) -> str:
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>Informe Institucional {ticker} {year}</title></head>
    <body>
        <h1>EXPEDIENTE REGULATORIO OFICIAL CNMV / ESEF iXBRL</h1>
        <p>DICTAMEN DE AUDITORIA FAVORABLE SIN SALVEDADES (SIMULADO)</p>
        <p>Fórmula de importes crecientes: base + (year-2019)*50000000</p>
        <p>Activo Total: 1850000000 EUR</p>
    </body>
    </html>
    """
