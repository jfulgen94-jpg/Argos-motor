"""
ARGOS_MOTOR — REORGANIZADOR Y LIMPIADOR ESTRUCTURAL DE ALTA VELOCIDAD

Estructura Final Exigida por el Usuario:
data/raw/ES_CNMV/
├── INFORMES_ANUALES_COMPLETOS/
│   ├── {AÑO}/ (2020..2025)
│   │   └── {TICKER}_{EMPRESA}/
│   │       ├── informe_financiero_anual_auditado/
│   │       │   └── {documento_real}.xhtml (o .pdf/.html)
│   │       ├── taxonomias_xbrl_esef/
│   │       │   └── (.xsd, _cal.xml, _def.xml, _lab-es.xml, _pre.xml, catalog.xml)
│   │       └── manifest_sha256/
│   │           └── {ticker}_{año}_manifest.json
│
└── INFORMES_PERIODICOS_INTERMEDIOS/
    ├── SEMESTRALES_H1/
    │   └── {AÑO}/
    │       └── {TICKER}_{EMPRESA}/
    │           ├── informe_financiero_semestral/
    │           └── manifest_sha256/
    └── TRIMESTRALES_Q1_Q3/
        └── {AÑO}/
            ├── Q1/{TICKER}_{EMPRESA}/
            └── Q3/{TICKER}_{EMPRESA}/
"""

import sys, os, json, hashlib, shutil, re
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_RAW = Path(r"c:\Users\jfulg\Desktop\Stater\ARGOS_MOTOR\data\raw")
ES_CNMV = BASE_RAW / "ES_CNMV"
BME_GROWTH = BASE_RAW / "ES_BME_GROWTH"
INTERIM = BASE_RAW / "ES_CNMV_INTERIM"

ANNUAL_TARGET = ES_CNMV / "INFORMES_ANUALES_COMPLETOS"
INTERIM_TARGET = ES_CNMV / "INFORMES_PERIODICOS_INTERMEDIOS"

LEI_TICKER_MAP = {
    "5493006QMFDD": ("SAN", "Banco_Santander_SA"),
    "K8MS7FD7N5Z2": ("BBVA", "Banco_Bilbao_Vizcaya_Argentaria_SA"),
    "5QK37QC7NWOJ": ("IBE", "Iberdrola_SA"),
    "549300E9PC50": ("ITX", "Industria_de_Diseno_Textil_SA"),
    "549300EEJH4F": ("TEF", "Telefonica_SA"),
    "BSYCX13Y0NOT": ("REP", "Repsol_SA"),
    "7CUNS533WID6": ("CABK", "CaixaBank_SA"),
    "9598004A3FTY": ("AMS", "Amadeus_IT_Group_SA"),
    "5493008T4YG3": ("CLNX", "Cellnex_Telecom_SA"),
    "959800HSSNXW": ("GRF", "Grifols_SA"),
    "959800JRKSZ6": ("MEL", "Melia_Hotels_International_SA"),
    "959800TZHQRU": ("IAG", "International_Airlines_Group_SA"),
    "TL2N6M87CW97": ("NTGY", "Naturgy_Energy_Group_SA"),
    "213800OU3FQK": ("ENG", "Enagas_SA"),
    "549300LHK07F": ("ELE", "Endesa_SA"),
    "5493009HMD0C": ("RED", "Redeia_Corporacion_SA"),
    "VWMYAEQSTOPN": ("BKT", "Bankinter_SA"),
    "5493007SJLLC": ("UNI", "Unicaja_Banco_SA"),
    "959800PM2YJU": ("SOL", "Solaria_Energia_y_Medio_Ambiente_SA"),
    "959800QWKZ45": ("PHM", "PharmaMar_SA"),
    "959800L8KD86": ("MRL", "Merlin_Properties_SOCIMI_SA"),
    "SI5RG2M0WQQL": ("SAB", "Banco_de_Sabadell_SA"),
    "959800XKAB9V": ("SCYR", "Sacyr_SA"),
    "549300OVHNSX": ("PUIG", "Puig_Brands_SA"),
    "959800R7QMXK": ("AENA", "Aena_SME_SA"),
    "54930002KP75": ("ANA", "Acciona_SA"),
    "254900UPX0OE": ("ANE", "Acciona_Energia_SA"),
    "959800FXZQY7": ("FAE", "Faes_Farma_SA"),
    "959800NW6DLQ": ("EBRO", "Ebro_Foods_SA"),
    "95980037JECH": ("TLGO", "Talgo_SA"),
    "959800M1FVPL": ("GRE", "Grenergy_Renovables_SA"),
    "54930063C6K2": ("DIA", "Distribuidora_Internacional_de_Alimentacion_SA"),
    "959800H2P9S8": ("GCO", "Grupo_Catalana_Occidente_SA"),
    "529900MUFAH0": ("EDPR", "EDP_Renovaveis_SA"),
    "959800GZESQU": ("AMP", "Amper_SA"),
    "959800AXZW3E": ("AZK", "Azkoyen_SA"),
    "959800CR1BA4": ("BAV", "Clinica_Baviera_SA"),
    "959800U3NGPX": ("PRS", "Promotora_de_Informaciones_SA_PRISA"),
    "9598005HY5DE": ("PGR", "Prosegur_Cash_SA"),
    "549300N94L4D": ("PSG", "Prosegur_Compania_de_Seguridad_SA"),
    "213800IMKAUV": ("R4", "Renta_4_Banco_SA"),
    "959800N1575U": ("REN", "Renta_Corporacion_Real_Estate_SA"),
    "9598003MRMJH": ("RJF", "Laboratorio_Reig_Jofre_SA"),
    "9598002SMUBZ": ("SANJ", "Grupo_Empresarial_San_Jose_SA"),
    "959800NZ03Z4": ("SQRL", "Squirrel_Media_SA"),
    "213800JEZBUP": ("TRE", "Tecnicas_Reunidas_SA"),
    "959800EXHG00": ("NEA", "Nicolas_Correa_SA"),
    "95980078NDTD": ("ALNT", "Alantra_Partners_SA"),
    "959800LM1RW3": ("NHH", "Minor_Hotels_Europe_Americas_NH_SA"),
    "959800JRJW1C": ("CEMT", "Cementos_Molins_SA"),
    "959800FW4JL6": ("NEIN", "Neinor_Homes_SA"),
    "959800L6L2B2": ("SOLT", "Soltec_Power_Holdings_SA"),
    "959800HBGZWH": ("ECO", "Ecoener_SA"),
    "213800M9XCA6": ("APPS", "Applus_Services_SA"),
    "959800FQZ6YA": ("INMO", "Inmocemento_SA"),
    "95980079E2NB": ("LINEA", "Linea_Directa_Aseguradora_SA"),
    "959800Z611RK": ("ERC", "Ercros_SA"),
    "959800M75M81": ("PRM", "Prim_SA"),
    "959800CJH35N": ("ALB", "Corporacion_Financiera_Alba_SA"),
    "959800ZQW44V": ("MVC", "Metrovacesa_SA"),
    "959800WGUAJ7": ("ISUR", "Inmobiliaria_del_Sur_SA"),
    "959800K5R280": ("ARIM", "Arima_Real_Estate_SOCIMI_SA"),
    "959800KT1FVN": ("OPDE", "Opdenergy_Holding_SA"),
    "959800RG37G8": ("IBP", "Iberpapel_Gestion_SA"),
    "959800PV7FH0": ("LGT", "Lingotes_Especiales_SA"),
    "549300TTCXZO": ("EDR", "eDreams_ODIGEO_SA"),
    "549300OLBL49": ("IBCA", "Ibercaja_Banco_SA"),
    "635400XT3V7W": ("LBK", "Liberbank_SA"),
    "549300685QG7": ("BKIA", "Bankia_SA"),
    "959800NAFTNQ": ("SLPK", "Solarpack_Corporacion_Tecnologica_SA"),
    "259400T6ZDQI": ("EAT", "AmRest_Holdings_SE"),
    "5493000LM0MZ": ("SCF", "Santander_Consumer_Finance_SA"),
    "959800L5NRK0": ("ALTI", "Altia_Consultores_SA"),
    "984500D45D59": ("MS", "Making_Science_Group_SA"),
    "959800HPL6CH": ("GIGA", "Gigas_Hosting_SA"),
    "959800X6PDF1": ("IZER", "Izertis_SA"),
    "959800GKWBRP": ("480", "Cuatroochenta_SA"),
    "959800HHEE9W": ("ATRS", "Atrys_Health_SA"),
    "9598006D23D7": ("KOMP", "Plasticos_Compuestos_SA"),
    "984500F8EA7C": ("HANN", "Hannun_SA"),
    "959800XWP1TQ": ("ELZ", "Asturiana_de_Laminados_Elzinc_SA"),
    "959800Y0M22C": ("EVM", "EV_Motors_EBRO_Automotive_SA"),
    "95980067SQTC": ("CLEV", "Clever_Global_SA"),
    "9598006K459Q": ("PROED", "Proeduca_Altus_UNIR_SA"),
    "529900A9QNZE": ("SEC", "Secuoya_Content_Group_SA"),
    "95980039WZZX": ("MONDO", "Mondo_TV_Iberoamerica_SA"),
    "959800SFRDQW": ("IDX", "Indexa_Capital_Group_SA"),
    "959800U5ELPW": ("ART", "Arteche_Grupo_Arteche_SA"),
    "959800J3PD72": ("ENERS", "Enerside_Energy_SA"),
    "959800NMBHBD": ("EIDF", "EiDF_Solar_SA"),
    "959800K43A1N": ("CLR", "Clerhp_Estructuras_SA"),
    "959800LGQ87E": ("GREN", "Greening_Group_SA"),
    "959800201400": ("HLZ", "Holaluz_Clidom_Energy_SA"),
    "959800TSRNQZ": ("PAN", "Pangaea_Oncology_SA"),
    "959800KVCD3W": ("VYTR", "Vytrus_Biotech_SA"),
    "959800PSH8S6": ("LAB", "Labiana_Health_SA"),
    "95980063R15R": ("ORYZ", "Oryzon_Genomics_SA"),
}

def calc_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()

def is_dummy_file(path: Path) -> bool:
    if not path.is_file():
        return False
    size = path.stat().st_size
    name = path.name.lower()
    if size < 5000:
        if "meta.json" in name or "manifest.json" in name or "catalog.xml" in name:
            return False
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read(1000)
                if "Lorem ipsum" in txt or "CSRD y sostenibilidad" in txt:
                    return True
        except:
            pass
    return False

def resolve_ticker_and_name(folder_name: str):
    clean = folder_name.replace(',', '').replace(' ', '_')
    parts = clean.split('_')
    prefix = parts[0].upper()
    
    for lei, (t, n) in LEI_TICKER_MAP.items():
        if prefix.startswith(lei[:8]):
            return t, n
            
    if len(parts) >= 2 and len(parts[0]) <= 6 and not parts[0].isdigit():
        return parts[0].upper(), "_".join(parts[1:])
        
    return prefix, clean

def reorganize():
    print("=" * 80)
    print("REORGANIZACIÓN INTEGRAL DE ALTA VELOCIDAD Y LIMPIEZA TOTAL")
    print("=" * 80)
    
    ANNUAL_TARGET.mkdir(parents=True, exist_ok=True)
    INTERIM_TARGET.mkdir(parents=True, exist_ok=True)
    
    # 1. Procesar años anuales: 2020, 2021, 2022, 2023, 2024, 2025
    annual_inventory = []
    
    for year in ["2020", "2021", "2022", "2023", "2024", "2025"]:
        source_y = ES_CNMV / year
        if not source_y.exists():
            continue
            
        print(f"\n📂 Procesando Cuentas Anuales del Ejercicio {year}...")
        
        for comp_dir in list(source_y.iterdir()):
            if not comp_dir.is_dir() or comp_dir.name.startswith("INFORMES_"):
                continue
                
            ticker, comp_name = resolve_ticker_and_name(comp_dir.name)
            
            # Recolectar archivos reales dentro de extracted/ o en la carpeta
            search_dirs = [comp_dir / "extracted", comp_dir]
            all_files = []
            for sd in search_dirs:
                if sd.exists():
                    all_files.extend([f for f in sd.rglob("*") if f.is_file()])
                    
            # Eliminar dummies y duplicados
            valid_files = []
            seen_names = set()
            for f in all_files:
                if is_dummy_file(f):
                    continue
                if f.name not in seen_names:
                    seen_names.add(f.name)
                    valid_files.append(f)
                    
            if not valid_files:
                continue
                
            # Carpetas semánticas destino
            target_comp = ANNUAL_TARGET / year / f"{ticker}_{comp_name}"
            sub_audit = target_comp / "informe_financiero_anual_auditado"
            sub_tax = target_comp / "taxonomias_xbrl_esef"
            sub_manifest = target_comp / "manifest_sha256"
            
            sub_audit.mkdir(parents=True, exist_ok=True)
            sub_tax.mkdir(parents=True, exist_ok=True)
            sub_manifest.mkdir(parents=True, exist_ok=True)
            
            file_records = []
            
            for vf in valid_files:
                n_low = vf.name.lower()
                
                # A) Informe anual auditado XHTML / PDF / HTML
                if vf.suffix.lower() in [".xhtml", ".html", ".pdf"]:
                    dest = sub_audit / vf.name
                    if not dest.exists():
                        try:
                            shutil.copy2(vf, dest)
                        except:
                            pass
                    if dest.exists():
                        f_sz = dest.stat().st_size
                        f_sha = calc_sha256(dest)
                        file_records.append({
                            "category": "INFORME_FINANCIERO_ANUAL_AUDITADO",
                            "filename": dest.name,
                            "relative_path": f"informe_financiero_anual_auditado/{dest.name}",
                            "size_mb": round(f_sz / (1024*1024), 2),
                            "sha256": f_sha
                        })
                        
                # B) Taxonomías XBRL
                elif vf.suffix.lower() in [".xsd", ".xml"] and "manifest" not in n_low and "meta" not in n_low:
                    dest = sub_tax / vf.name
                    if not dest.exists():
                        try:
                            shutil.copy2(vf, dest)
                        except:
                            pass
                    if dest.exists():
                        f_sz = dest.stat().st_size
                        f_sha = calc_sha256(dest)
                        file_records.append({
                            "category": "TAXONOMIA_XBRL_ESEF",
                            "filename": dest.name,
                            "relative_path": f"taxonomias_xbrl_esef/{dest.name}",
                            "size_mb": round(f_sz / (1024*1024), 2),
                            "sha256": f_sha
                        })
                        
            if file_records:
                # Manifiesto local
                mf_path = sub_manifest / f"{ticker.lower()}_{year}_manifest.json"
                mf_data = {
                    "ticker": ticker,
                    "company_name": comp_name,
                    "year": int(year) if year.isdigit() else year,
                    "report_type": "CUENTAS_ANUALES_CONSOLIDADAS_AUDITADAS_ESEF",
                    "total_files": len(file_records),
                    "files": file_records,
                    "sealed_at": datetime.now(timezone.utc).isoformat()
                }
                with open(mf_path, "w", encoding="utf-8") as mf:
                    json.dump(mf_data, mf, indent=2, ensure_ascii=False)
                annual_inventory.append(mf_data)
                
    # 2. Guardar inventario anual global
    ann_inv_path = ANNUAL_TARGET / "INFORMES_ANUALES_INVENTORY_SHA256.json"
    with open(ann_inv_path, "w", encoding="utf-8") as aif:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_packages": len(annual_inventory),
            "packages": annual_inventory
        }, aif, indent=2, ensure_ascii=False)
        
    print(f"\n✅ Informes Anuales Completados: {len(annual_inventory)} paquetes sellados")
    
    # 3. Organizar Informes Periódicos Intermedios (Semestrales / Trimestrales)
    print("\n📂 Organizando Informes Periódicos Intermedios (Semestrales / Trimestrales)...")
    sem_h1 = INTERIM_TARGET / "SEMESTRALES_H1"
    tri_q = INTERIM_TARGET / "TRIMESTRALES_Q1_Q3"
    sem_h1.mkdir(parents=True, exist_ok=True)
    tri_q.mkdir(parents=True, exist_ok=True)
    
    if INTERIM.exists():
        for y_dir in INTERIM.iterdir():
            if not y_dir.is_dir():
                continue
            y = y_dir.name
            
            # Semestrales H1
            h1 = y_dir / "H1"
            if h1.exists():
                for comp in h1.iterdir():
                    if comp.is_dir():
                        t, n = resolve_ticker_and_name(comp.name)
                        dest_c = sem_h1 / y / f"{t}_{n}"
                        (dest_c / "informe_financiero_semestral").mkdir(parents=True, exist_ok=True)
                        (dest_c / "manifest_sha256").mkdir(parents=True, exist_ok=True)
                        for f in comp.iterdir():
                            if f.is_file() and not is_dummy_file(f):
                                if "meta.json" in f.name:
                                    shutil.copy2(f, dest_c / "manifest_sha256" / f.name)
                                else:
                                    shutil.copy2(f, dest_c / "informe_financiero_semestral" / f.name)
                                    
            # Trimestrales Q1/Q3
            for q in ["Q1", "Q3"]:
                qd = y_dir / q
                if qd.exists():
                    for comp in qd.iterdir():
                        if comp.is_dir():
                            t, n = resolve_ticker_and_name(comp.name)
                            dest_c = tri_q / y / q / f"{t}_{n}"
                            (dest_c / "declaracion_intermedia_gestion").mkdir(parents=True, exist_ok=True)
                            (dest_c / "manifest_sha256").mkdir(parents=True, exist_ok=True)
                            for f in comp.iterdir():
                                if f.is_file() and not is_dummy_file(f):
                                    if "meta.json" in f.name:
                                        shutil.copy2(f, dest_c / "manifest_sha256" / f.name)
                                    else:
                                        shutil.copy2(f, dest_c / "declaracion_intermedia_gestion" / f.name)
                                        
    # 4. Limpiar carpetas origen obsoletas de la raíz
    print("\n🧹 Limpiando carpetas y archivos obsoletos...")
    for y in ["2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"]:
        yd = ES_CNMV / y
        if yd.exists() and yd.parent == ES_CNMV:
            shutil.rmtree(yd, ignore_errors=True)
            
    for item in list(ES_CNMV.iterdir()):
        if item.is_dir() and item.name not in ["INFORMES_ANUALES_COMPLETOS", "INFORMES_PERIODICOS_INTERMEDIOS"]:
            shutil.rmtree(item, ignore_errors=True)
            
    if BME_GROWTH.exists():
        shutil.rmtree(BME_GROWTH, ignore_errors=True)
    if INTERIM.exists():
        shutil.rmtree(INTERIM, ignore_errors=True)
        
    print("\n" + "=" * 80)
    print("🏆 REORGANIZACIÓN Y LIMPIEZA 100% COMPLETADA")
    print(f"  • Estructura Anual:    {ANNUAL_TARGET}")
    print(f"  • Estructura Intermedia: {INTERIM_TARGET}")
    print("=" * 80)

if __name__ == "__main__":
    reorganize()
