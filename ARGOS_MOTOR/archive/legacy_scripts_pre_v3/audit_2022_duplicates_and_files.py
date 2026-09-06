"""
STATER — AUDITORÍA FORENSE 2022: EXPLICACIÓN DE 178 CARPETAS VS 136 EMPRESAS ÚNICAS
Comprueba todos los archivos XHTML > 100KB, calcula hashes y genera un informe de duplicados.
"""

import sys, json, hashlib
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_2022 = Path(r"c:\Users\jfulg\Desktop\Stater\ARGOS_MOTOR\data\raw\ES_CNMV\INFORMES_ANUALES_COMPLETOS\2022")
AUDIT_DIR = Path(r"c:\Users\jfulg\Desktop\Stater\ARGOS_MOTOR\data\raw\AUDITORIA_FILINGS_Y_DUPLICADOS_2022")
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

def calc_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()

def audit_2022():
    print("=" * 80)
    print("AUDITORÍA FORENSE 2022: VERIFICACIÓN DE TODOS LOS ARCHIVOS PESADOS")
    print("=" * 80)
    
    companies_data = []
    total_heavy_files = 0
    total_bytes = 0
    multi_file_companies = []
    
    for comp_dir in sorted(BASE_2022.iterdir()):
        if not comp_dir.is_dir():
            continue
            
        audit_sub = comp_dir / "informe_financiero_anual_auditado"
        tax_sub = comp_dir / "taxonomias_xbrl_esef"
        
        docs = []
        if audit_sub.exists():
            for f in audit_sub.iterdir():
                if f.is_file() and f.stat().st_size > 100000: # > 100 KB
                    f_size = f.stat().st_size
                    total_bytes += f_size
                    total_heavy_files += 1
                    docs.append({
                        "filename": f.name,
                        "size_mb": round(f_size / (1024 * 1024), 2),
                        "size_bytes": f_size,
                        "sha256": calc_sha256(f)
                    })
                    
        tax_count = len(list(tax_sub.glob("*"))) if tax_sub.exists() else 0
        
        comp_record = {
            "canonical_name": comp_dir.name,
            "total_documents": len(docs),
            "documents": docs,
            "taxonomies_count": tax_count
        }
        companies_data.append(comp_record)
        
        if len(docs) > 1:
            multi_file_companies.append(comp_record)
            
    print(f"\n📊 RESUMEN 2022:")
    print(f"  • Total Empresas Únicas Analizadas: {len(companies_data)}")
    print(f"  • Total Archivos XHTML/HTML Pesados (> 100 KB): {total_heavy_files}")
    print(f"  • Volumen Total de Datos en 2022: {round(total_bytes / (1024**3), 2)} GB ({round(total_bytes / (1024**2), 2)} MB)")
    print(f"  • Empresas con Múltiples Versiones / Idiomas (ES/EN): {len(multi_file_companies)}")
    
    # Guardar informe JSON completo
    report_json_path = AUDIT_DIR / "INFORME_COMPLETO_FILINGS_2022.json"
    with open(report_json_path, "w", encoding="utf-8") as jf:
        json.dump({
            "year": 2022,
            "total_companies": len(companies_data),
            "total_heavy_files": total_heavy_files,
            "total_volume_mb": round(total_bytes / (1024**2), 2),
            "multi_file_companies_count": len(multi_file_companies),
            "companies": companies_data
        }, jf, indent=2, ensure_ascii=False)
        
    print(f"\n📄 Informe JSON generado en: {report_json_path}")
    
    # Generar tabla resumen en Markdown
    report_md_path = AUDIT_DIR / "TABLA_AUDITORIA_FILINGS_2022.md"
    with open(report_md_path, "w", encoding="utf-8") as mf:
        mf.write("# Auditoría Forense de Filings Oficiales 2022\n\n")
        mf.write(f"**Total Empresas Únicas:** {len(companies_data)}  \n")
        mf.write(f"**Total Archivos XHTML Pesados:** {total_heavy_files}  \n")
        mf.write(f"**Volumen Total:** {round(total_bytes / (1024**3), 2)} GB  \n\n")
        mf.write("## Detalle por Empresa\n\n")
        mf.write("| Empresa (Carpeta Canónica) | Documentos | Tamaño (MB) | Archivos Principales |\n")
        mf.write("| :--- | :---: | :---: | :--- |\n")
        for c in companies_data:
            c_name = c["canonical_name"]
            n_docs = c["total_documents"]
            sz_mb = sum(d["size_mb"] for d in c["documents"])
            files_str = "<br>".join([f"`{d['filename']}` ({d['size_mb']} MB)" for d in c["documents"]]) if c["documents"] else "*(Taxonomías / IFRS NIC1)*"
            mf.write(f"| **{c_name}** | {n_docs} | {round(sz_mb, 2)} MB | {files_str} |\n")
            
    print(f"📄 Tabla Markdown generada en: {report_md_path}")
    print("=" * 80)

if __name__ == "__main__":
    audit_2022()
