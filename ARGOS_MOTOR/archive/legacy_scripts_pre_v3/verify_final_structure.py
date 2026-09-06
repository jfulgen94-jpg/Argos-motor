"""
Auditoría Final y Verificación de la Estructura Canónica ES_CNMV.
"""

import sys, json
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

base_cnmv = Path(r"c:\Users\jfulg\Desktop\Stater\ARGOS_MOTOR\data\raw\ES_CNMV")
base_annual = base_cnmv / "INFORMES_ANUALES_COMPLETOS"
base_interim = base_cnmv / "INFORMES_PERIODICOS_INTERMEDIOS"

def audit():
    print("=" * 80)
    print("AUDITORÍA DE LA ESTRUCTURA CANÓNICA DEFINITIVA (ES_CNMV)")
    print("=" * 80)

    print("\n📦 1. INFORMES ANUALES COMPLETOS (ESEF / CCAA Consolidadas Auditadas):")
    if base_annual.exists():
        for yd in sorted(base_annual.iterdir()):
            if yd.is_dir():
                comps = [c for c in yd.iterdir() if c.is_dir()]
                print(f"   • Ejercicio {yd.name}: {len(comps)} empresas")
                if comps:
                    ex = comps[0]
                    subs = [s.name for s in ex.iterdir() if s.is_dir()]
                    files_in_audit = list((ex / "informe_financiero_anual_auditado").glob("*"))
                    print(f"     └─ Ejemplo: {ex.name}/")
                    print(f"        ├── informe_financiero_anual_auditado/ -> {[f.name for f in files_in_audit[:2]]}")
                    print(f"        ├── taxonomias_xbrl_esef/ -> {len(list((ex / 'taxonomias_xbrl_esef').glob('*')))} taxonomías")
                    print(f"        └── manifest_sha256/ -> {[f.name for f in (ex / 'manifest_sha256').glob('*')]}")

    print("\n📑 2. INFORMES PERIÓDICOS INTERMEDIOS:")
    if base_interim.exists():
        for sub in sorted(base_interim.iterdir()):
            if sub.is_dir():
                print(f"   • {sub.name}:")
                for y_or_q in sorted(sub.iterdir()):
                    if y_or_q.is_dir():
                        c_count = len(list(y_or_q.iterdir()))
                        print(f"      └─ {y_or_q.name}/ ({c_count} empresas registradas)")

    print("\n📁 3. Contenido en la raíz ES_CNMV:")
    for item in sorted(base_cnmv.iterdir()):
        if item.is_dir():
            print(f"   - 📁 {item.name}/")
        else:
            print(f"   - 📄 {item.name}")

    inv = base_annual / "INFORMES_ANUALES_INVENTORY_SHA256.json"
    if inv.exists():
        with open(inv, encoding="utf-8") as f:
            data = json.load(f)
        pkg_count = data.get("total_packages", len(data.get("packages", [])))
        print(f"\n🛡️ Total paquetes anuales sellados con SHA-256 en inventario: {pkg_count}")
    print("=" * 80)

if __name__ == "__main__":
    audit()
