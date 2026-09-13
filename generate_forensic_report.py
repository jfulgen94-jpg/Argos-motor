import json
from pathlib import Path


def generate_forensic_report(universe_path, data_path, report_path):
    with open(universe_path, 'r', encoding='utf-8') as f:
        universe = json.load(f)

    segments = {}
    for company in universe['companies'].values():
        segment = company['segment']
        if segment not in segments:
            segments[segment] = 0
        segments[segment] += 1

    orphan_folders = []
    for year_folder in Path(data_path).iterdir():
        if not year_folder.is_dir():
            continue
        for company_folder in year_folder.iterdir():
            if "LEI" in company_folder.name:
                orphan_folders.append(company_folder.name)

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# Informe Forense: Universo de Empresas de España\n\n")
        f.write("## Resumen de Empresas por Segmento\n\n")
        for segment, count in segments.items():
            f.write(f"- **{segment}:** {count} empresas\n")
        f.write(f"\n**Total de Empresas:** {universe['total_entities']}\n")

        f.write("\n## Auditoría de Carpetas Huérfanas\n\n")
        if not orphan_folders:
            f.write("No se encontraron carpetas con nombres de LEI sin resolver.\n")
        else:
            f.write("Se encontraron las siguientes carpetas huérfanas:\n")
            for folder in orphan_folders:
                f.write(f"- {folder}\n")


if __name__ == '__main__':
    universe_path = '/workspace/project/Argos-motor/ARGOS_MOTOR/config/master_universe_es.json'
    data_path = '/workspace/project/Argos-motor/ARGOS_MOTOR/data/raw/ES_CNMV'
    report_path = '/workspace/project/Argos-motor/AUDIT_ESPANNA_UNIVERSAL_SANEADO.md'
    generate_forensic_report(universe_path, data_path, report_path)
