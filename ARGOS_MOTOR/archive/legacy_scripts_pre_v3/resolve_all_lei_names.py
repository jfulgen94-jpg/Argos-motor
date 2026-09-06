"""
Detector forense de nombres de entidad para carpetas LEI no resueltas.
"""

import sys, re
from pathlib import Path
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_ANNUAL = Path(r"c:\Users\jfulg\Desktop\Stater\ARGOS_MOTOR\data\raw\ES_CNMV\INFORMES_ANUALES_COMPLETOS")

def inspect_lei_folders():
    unresolved_map = {}
    
    for y in ["2024", "2023", "2022", "2021", "2020"]:
        yd = BASE_ANNUAL / y
        if not yd.exists():
            continue
        unresolved = [c for c in yd.iterdir() if c.is_dir() and (c.name[0].isdigit() or len(c.name.split('_')[0]) > 8)]
        
        for c in unresolved:
            prefix = c.name.split('_')[0]
            if prefix in unresolved_map:
                continue
                
            audit_dir = c / "informe_financiero_anual_auditado"
            docs = list(audit_dir.glob("*.xhtml")) + list(audit_dir.glob("*.html"))
            
            ent_name = None
            if docs:
                doc = docs[0]
                try:
                    with open(doc, "r", encoding="utf-8", errors="ignore") as f:
                        # Leer primeros 50KB para encontrar datos de identificación
                        content = f.read(50000)
                        
                        # Buscar NameOfReportingEntity
                        m_name = re.search(r'NameOfReportingEntityOrOtherMeansOfIdentification[^>]*>([^<]+)<', content, re.IGNORECASE)
                        if m_name:
                            ent_name = m_name.group(1).strip()
                            
                        if not ent_name:
                            m_title = re.search(r'<title>(.*?)</title>', content, re.IGNORECASE)
                            if m_title and len(m_title.group(1).strip()) > 3:
                                ent_name = m_title.group(1).strip()
                                
                        if not ent_name:
                            # Buscar en el texto general
                            soup = BeautifulSoup(content[:20000], "html.parser")
                            text = soup.get_text()
                            lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 5 and 'S.A' in l.upper() or 'S.A.' in l.upper()]
                            if lines:
                                ent_name = lines[0]
                except Exception as e:
                    pass
                    
            unresolved_map[prefix] = (c.name, ent_name, docs[0].name if docs else "No doc")
            
    print("=" * 80)
    print(f"RESULTADOS DE IDENTIFICACIÓN FORENSE ({len(unresolved_map)} carpetas LEI encontradas):")
    print("=" * 80)
    for prefix, (folder, name, doc) in unresolved_map.items():
        print(f"• Prefijo: {prefix}")
        print(f"  Carpeta actual: {folder}")
        print(f"  Nombre detectado: {name}")
        print(f"  Doc: {doc}")
        print("-" * 50)
        
    return unresolved_map

if __name__ == "__main__":
    inspect_lei_folders()
