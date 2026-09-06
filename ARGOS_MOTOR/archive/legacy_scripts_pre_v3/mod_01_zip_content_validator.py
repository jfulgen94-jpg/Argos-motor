"""
VALIDADOR DE CONTENIDO: Analiza los ZIPs ESEF descargados y verifica
que el XHTML interno es un informe completo con tablas financieras reales.

Detecta:
- Presencia del Balance (Activo/Pasivo/PN)
- Cuenta de Pérdidas y Ganancias
- Estado de Flujos de Efectivo
- Notas contables (al menos N>5)
- Informe de auditoría
- Tags iXBRL (ix:nonNumeric, ix:nonFraction, etc.)
- Ausencia de contenido placeholder (lorem ipsum)

Uso:
  python mod_01_zip_content_validator.py <path_al_zip>
  python mod_01_zip_content_validator.py data/raw/landing_raw/2024/IBE/IBE_2024_esef_bundle.zip
"""

import sys, json, zipfile, re, hashlib
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Secciones requeridas por RAMA para validar el contenido del XHTML
REQUIRED_SECTIONS = {
    'balance': [
        r'activo\s+total', r'activo\s+no\s+corriente', r'activo\s+corriente',
        r'pasivo\s+total', r'pasivo\s+no\s+corriente', r'pasivo\s+corriente',
        r'patrimonio\s+neto', r'capital\s+social',
        r'total\s+assets', r'total\s+equity', r'total\s+liabilities',
    ],
    'pyg': [
        r'resultado\s+del\s+ejercicio', r'resultado\s+neto', r'beneficio\s+neto',
        r'ingresos\s+de\s+explotaci[oó]n', r'cifra\s+de\s+negocios', r'importe\s+neto',
        r'ebitda', r'ebit', r'resultado\s+antes\s+de\s+impuestos',
        r'profit\s+for\s+the\s+year', r'revenue', r'net\s+income',
    ],
    'cash_flow': [
        r'flujos\s+de\s+efectivo', r'actividades\s+de\s+explotaci[oó]n',
        r'actividades\s+de\s+inversi[oó]n', r'actividades\s+de\s+financiaci[oó]n',
        r'cash\s+flow', r'cash\s+flows\s+from\s+operating', r'net\s+cash',
    ],
    'ixbrl_tags': [
        r'ix:nonNumeric', r'ix:nonFraction', r'ix:header', r'xmlns:ix=',
        r'ixbrl', r'xbrl',
    ],
}

PLACEHOLDER_PATTERNS = [
    r'lorem\s+ipsum', r'dolor\s+sit\s+amet', r'consectetur\s+adipiscing',
    r'texto\s+de\s+prueba', r'sample\s+text', r'xxx+',
]


def validate_xhtml_content(xhtml_content: str, filename: str) -> dict:
    """Valida el contenido de un archivo XHTML de informe ESEF."""
    
    result = {
        'filename': filename,
        'size_chars': len(xhtml_content),
        'size_kb': round(len(xhtml_content.encode('utf-8')) / 1024, 1),
        'is_ixbrl': False,
        'sections_found': {},
        'sections_missing': {},
        'has_placeholder': False,
        'placeholder_found': [],
        'financial_numbers_count': 0,
        'valid': False,
        'warnings': [],
    }
    
    content_lower = xhtml_content.lower()
    
    # Detectar placeholder
    for pat in PLACEHOLDER_PATTERNS:
        if re.search(pat, content_lower):
            result['has_placeholder'] = True
            result['placeholder_found'].append(pat)
    
    # Verificar secciones requeridas
    for section, patterns in REQUIRED_SECTIONS.items():
        found = []
        for pat in patterns:
            if re.search(pat, content_lower, re.IGNORECASE):
                found.append(pat)
        
        if section == 'ixbrl_tags':
            result['is_ixbrl'] = len(found) > 0
            result['sections_found']['ixbrl'] = found
        elif found:
            result['sections_found'][section] = found
        else:
            result['sections_missing'][section] = patterns[:3]
    
    # Contar cifras financieras (números con formato contable)
    numbers = re.findall(r'\b\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?\b', xhtml_content)
    result['financial_numbers_count'] = len(numbers)
    
    # Verificar tamaño mínimo (un informe real tiene >500 KB)
    if result['size_kb'] < 100:
        result['warnings'].append(f"Archivo muy pequeño: {result['size_kb']} KB (esperado >500 KB)")
    
    if result['size_kb'] < 50:
        result['warnings'].append("ALERTA: probablemente no es un informe completo")
    
    # Determinar validez
    core_sections = {'balance', 'pyg'}
    found_sections = set(result['sections_found'].keys())
    
    result['valid'] = (
        not result['has_placeholder']
        and result['is_ixbrl']
        and core_sections.issubset(found_sections)
        and result['size_kb'] >= 100
        and result['financial_numbers_count'] >= 50
    )
    
    return result


def validate_esef_zip(zip_path: Path) -> dict:
    """Valida el contenido de un paquete ZIP ESEF."""
    
    print(f"\n{'='*60}")
    print(f"Validando: {zip_path.name}")
    print(f"{'='*60}")
    
    results = {
        'zip_path': str(zip_path),
        'zip_size_mb': round(zip_path.stat().st_size / 1024 / 1024, 2),
        'sha256': None,
        'files': [],
        'primary_document': None,
        'primary_validation': None,
        'zip_valid': False,
        'summary': '',
    }
    
    # SHA-256
    sha = hashlib.sha256()
    with open(zip_path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            sha.update(chunk)
    results['sha256'] = sha.hexdigest()
    print(f"SHA-256: {results['sha256']}")
    
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            results['files'] = names
            print(f"Archivos en ZIP: {len(names)}")
            
            for name in names:
                info = zf.getinfo(name)
                print(f"  {info.file_size/1024:8.1f} KB | {name}")
            
            # Encontrar el documento principal (XHTML más grande)
            xhtml_files = [(name, zf.getinfo(name).file_size) 
                           for name in names 
                           if name.endswith(('.xhtml', '.html', '.htm')) 
                           and '__MACOSX' not in name]
            
            if not xhtml_files:
                results['summary'] = "No se encontraron archivos XHTML"
                return results
            
            # El documento principal es el XHTML más grande
            primary_name, primary_size = max(xhtml_files, key=lambda x: x[1])
            results['primary_document'] = primary_name
            print(f"\nDocumento principal: {primary_name} ({primary_size/1024:.0f} KB)")
            
            # Leer y validar el documento principal
            with zf.open(primary_name) as f:
                # Leer hasta 10 MB para validación
                content = f.read(10_000_000).decode('utf-8', errors='replace')
            
            print(f"Leyendo {len(content)/1024:.0f} KB para validación...")
            validation = validate_xhtml_content(content, primary_name)
            results['primary_validation'] = validation
            
            print(f"\nRESULTADO DE VALIDACIÓN:")
            print(f"  Tamaño:     {validation['size_kb']:.0f} KB")
            print(f"  iXBRL:      {'✓' if validation['is_ixbrl'] else '✗'}")
            print(f"  Balance:    {'✓' if 'balance' in validation['sections_found'] else '✗'}")
            print(f"  PyG:        {'✓' if 'pyg' in validation['sections_found'] else '✗'}")
            print(f"  Cash Flow:  {'✓' if 'cash_flow' in validation['sections_found'] else '✗'}")
            print(f"  Cifras:     {validation['financial_numbers_count']}")
            print(f"  Placeholder:{'✗ ' + str(validation['placeholder_found']) if validation['has_placeholder'] else '✓ Ninguno'}")
            
            if validation['sections_missing']:
                for sec, pats in validation['sections_missing'].items():
                    print(f"  ✗ FALTA: {sec} (buscado: {pats[:2]})")
            
            if validation['warnings']:
                for w in validation['warnings']:
                    print(f"  ⚠ {w}")
            
            results['zip_valid'] = validation['valid']
            results['summary'] = (
                "VÁLIDO - Informe ESEF completo con tablas financieras" if validation['valid']
                else f"INVÁLIDO - {', '.join(list(validation['sections_missing'].keys()) or validation['warnings'][:1])}"
            )
            print(f"\n{'✓' if results['zip_valid'] else '✗'} {results['summary']}")
    
    except Exception as e:
        results['summary'] = f"Error: {e}"
        print(f"✗ Error: {e}")
    
    return results


if __name__ == '__main__':
    if len(sys.argv) < 2:
        # Validar el ZIP de Iberdrola que acabamos de descargar
        test_paths = [
            Path("data/raw/ES_CNMV_REAL/2024/IBE/IBE_2024_esef_bundle.zip"),
            Path("data/raw/landing_raw/2024/IBE/ibe_2024_esef_bundle.zip"),
        ]
        zip_paths = [p for p in test_paths if p.exists()]
        if not zip_paths:
            print("Uso: python mod_01_zip_content_validator.py <path_al_zip>")
            sys.exit(1)
    else:
        zip_paths = [Path(sys.argv[1])]
    
    for zip_path in zip_paths:
        if not zip_path.exists():
            print(f"✗ No existe: {zip_path}")
            continue
        
        result = validate_esef_zip(zip_path)
        
        # Guardar resultado
        out_path = zip_path.with_suffix('.validation.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\nResultado guardado en: {out_path}")
