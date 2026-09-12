import os
from pathlib import Path
from collections import defaultdict

base = Path(r"D:\ARGOS_DATA\raw\ES_CNMV")

junk_keywords = [
    'cnmv_2030', 'c_digo_de_conducta', 'codigo_de_conducta',
    'ciberseguridad_en_las_infraestructuras',
    'listado_individualizado_de_art_culos',
    'plan_de_sostenibilidad_ambiental'
]

categories = defaultdict(list)
total_bytes = defaultdict(int)

for p in base.rglob('*'):
    if not p.is_file():
        continue
    fname = p.name.lower()
    sz = p.stat().st_size

    if any(k in fname for k in junk_keywords):
        categories['JUNK_CNMV_FOOTER'].append(p)
        total_bytes['JUNK_CNMV_FOOTER'] += sz
    elif p.suffix.lower() == '.zip':
        categories['GENUINE_ESEF_ZIP'].append(p)
        total_bytes['GENUINE_ESEF_ZIP'] += sz
    elif p.suffix.lower() == '.pdf' and 'annual_report_' in fname:
        # Check if it has a registration number e.g. annual_report_18288.pdf
        parts = fname.replace('.pdf', '').split('_')
        last_part = parts[-1]
        if last_part.isdigit():
            categories['GENUINE_AUDIT_PDF'].append(p)
            total_bytes['GENUINE_AUDIT_PDF'] += sz
        else:
            categories['OTHER_PDF'].append(p)
            total_bytes['OTHER_PDF'] += sz
    elif p.suffix.lower() == '.json' and p.name.startswith('MANIFEST'):
        categories['MANIFEST'].append(p)
        total_bytes['MANIFEST'] += sz
    else:
        categories['OTHER'].append(p)
        total_bytes['OTHER'] += sz

print("=== CLASIFICACIÓN EXHAUSTIVA DE ARCHIVOS EN D:\\ARGOS_DATA\\raw\\ES_CNMV ===")
for cat, flist in categories.items():
    mb = total_bytes[cat] / (1024 * 1024)
    gb = total_bytes[cat] / (1024 ** 3)
    print(f"{cat:22s}: {len(flist):5d} archivos | {mb:10.2f} MB ({gb:5.2f} GB)")

if categories['OTHER']:
    print("\nMuestra de archivos en categoría OTHER:")
    for f in categories['OTHER'][:5]:
        print(" ", f)
