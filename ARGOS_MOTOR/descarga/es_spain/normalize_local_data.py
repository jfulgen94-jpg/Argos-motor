
import os
import json
import re
from pathlib import Path

def load_master_universe(master_universe_path):
    with open(master_universe_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def find_company_by_lei(master_universe, lei):
    for company_data in master_universe['companies'].values():
        if company_data.get('lei') == lei:
            return company_data
    return None

def normalize_data(base_path, master_universe_path):
    master_universe = load_master_universe(master_universe_path)
    base_path = Path(base_path)

    for year_folder in base_path.iterdir():
        if not year_folder.is_dir() or not year_folder.name.isdigit():
            continue

        for company_folder in year_folder.iterdir():
            if not company_folder.is_dir() or "LEI" not in company_folder.name:
                continue

            # Extract LEI from folder name
            match = re.search(r'([A-Z0-9]{20})', company_folder.name)
            if not match:
                print(f"Could not extract LEI from {company_folder.name}")
                continue
            
            lei = match.group(1)
            company_info = find_company_by_lei(master_universe, lei)

            if not company_info:
                print(f"Could not find company for LEI {lei} in master universe")
                continue

            cif = company_info['cif_nif']
            ticker = company_info['ticker']
            new_folder_name = f"{cif}_{ticker}"
            new_folder_path = year_folder / new_folder_name
            
            # Rename folder
            company_folder.rename(new_folder_path)
            print(f"Renamed folder {company_folder.name} to {new_folder_name}")

            # Rename files and create meta files
            for file in new_folder_path.iterdir():
                if file.suffix == '.zip':
                    new_zip_name = f"{ticker}_{year_folder.name}_ESEF.zip"
                    file.rename(new_folder_path / new_zip_name)
                    print(f"Renamed file {file.name} to {new_zip_name}")

                    meta_file_name = f"{ticker}_{year_folder.name}_ESEF.meta.json"
                    with open(new_folder_path / meta_file_name, 'w', encoding='utf-8') as f:
                        json.dump({"source_channel": "ESEF"}, f, indent=2)
                    print(f"Created meta file {meta_file_name}")

                elif file.suffix == '.pdf':
                    new_pdf_name = f"{ticker}_{year_folder.name}_ANUAL.pdf"
                    file.rename(new_folder_path / new_pdf_name)
                    print(f"Renamed file {file.name} to {new_pdf_name}")

                    meta_file_name = f"{ticker}_{year_folder.name}_ANUAL.meta.json"
                    with open(new_folder_path / meta_file_name, 'w', encoding='utf-8') as f:
                        json.dump({"source_channel": "CNMV_CRAWLER"}, f, indent=2)
                    print(f"Created meta file {meta_file_name}")


if __name__ == '__main__':
    data_path = "/workspace/project/Argos-motor/ARGOS_MOTOR/data/raw/ES_CNMV"
    universe_path = "/workspace/project/Argos-motor/ARGOS_MOTOR/config/master_universe_es.json"
    normalize_data(data_path, universe_path)

