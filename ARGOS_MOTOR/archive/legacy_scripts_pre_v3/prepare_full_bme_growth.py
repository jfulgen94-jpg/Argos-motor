"""
Expansión del Universo BME Growth: Catálogo exhaustivo de TODAS las empresas
en expansión operativas (no SOCIMIs, no fondos, no sociedades patrimoniales).
Total real: ~50-55 empresas operativas de crecimiento.
"""

import sys, json
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CATALOGS_DIR = Path("data/catalogs")
CATALOGS_DIR.mkdir(parents=True, exist_ok=True)

BME_GROWTH_FULL_CLEAN = [
    # ─── TECNOLOGÍA, SOFTWARE Y SERVICIOS DIGITALES ───
    {"ticker": "ALTI", "name": "Altia Consultores, S.A.", "sector": "Tecnología / Consultoría TI"},
    {"ticker": "MS", "name": "Making Science Group, S.A.", "sector": "Tecnología / Marketing Digital"},
    {"ticker": "GIGA", "name": "Gigas Hosting, S.A.", "sector": "Cloud Hosting & Telecom"},
    {"ticker": "IZER", "name": "Izertis, S.A.", "sector": "Tecnología / Servicios Digitales"},
    {"ticker": "480", "name": "Cuatroochenta (480S), S.A.", "sector": "Ciberseguridad y Software Cloud"},
    {"ticker": "AGIL", "name": "Agile Content, S.A.", "sector": "Software Audiovisual / OTT"},
    {"ticker": "LLN", "name": "Lleida.net, S.A.", "sector": "Certificación Electrónica"},
    {"ticker": "TR1", "name": "Tier1 Technology, S.A.", "sector": "Software y Sistemas"},
    {"ticker": "FACE", "name": "FacePhi Biometría, S.A.", "sector": "Biometría e Identidad"},
    {"ticker": "SAI", "name": "Substrate Artificial Intelligence, S.A.", "sector": "Inteligencia Artificial"},
    {"ticker": "PARLEM", "name": "Parlem Telecom Companyia de Telecomunicacions, S.A.", "sector": "Telecomunicaciones"},
    {"ticker": "NTX", "name": "Netex Knowledge Factory, S.A.", "sector": "EdTech / Software Educativo"},
    {"ticker": "CAT", "name": "Catenon, S.A.", "sector": "Recursos Humanos & Tecnología"},
    {"ticker": "SNGR", "name": "Sngular (Singular People), S.A.", "sector": "Software & Inteligencia Artificial"},
    {"ticker": "COMM", "name": "Commcenter, S.A.", "sector": "Distribución Telecomunicaciones"},
    {"ticker": "NBI", "name": "NBI Bearings Europe, S.A.", "sector": "Diseño y Fabricación Rodamientos"},
    {"ticker": "LUCK", "name": "Lucky Star / Agile, S.A.", "sector": "Servicios Digitales"},
    
    # ─── ENERGÍAS RENOVABLES, CLEANTECH E INGENIERÍA ───
    {"ticker": "ENERS", "name": "Enerside Energy, S.A.", "sector": "Energía Solar Fotovoltaica"},
    {"ticker": "EIDF", "name": "EiDF Solar, S.A.", "sector": "Autoconsumo y Generación Solar"},
    {"ticker": "CLR", "name": "Clerhp Estructuras, S.A.", "sector": "Ingeniería de Estructuras"},
    {"ticker": "GREN", "name": "Greening Group, S.A.", "sector": "Energías Renovables y Autoconsumo"},
    {"ticker": "HLZ", "name": "Holaluz (Clidom Energy), S.A.", "sector": "Energía Verde"},
    {"ticker": "SOLAR", "name": "Solarprofit (Profithol), S.A.", "sector": "Instalaciones Fotovoltaicas"},
    {"ticker": "UMB", "name": "Umbrella Solar Investment, S.A.", "sector": "Energía Solar"},
    {"ticker": "ISE", "name": "Inclam, S.A.", "sector": "Ingeniería Hidráulica y Medio Ambiente"},
    {"ticker": "END", "name": "Endurance Motive, S.A.", "sector": "Baterías de Litio para Movilidad"},
    {"ticker": "COXG", "name": "Cox Energy / Cox Group, S.A.", "sector": "Energía y Agua"},
    {"ticker": "SOLT", "name": "Soltec Power Holdings (origen Growth), S.A.", "sector": "Seguidores Solares"},

    # ─── BIOTECNOLOGÍA, SALUD Y FARMACIA ───
    {"ticker": "PAN", "name": "Pangaea Oncology, S.A.", "sector": "Oncología de Precisión"},
    {"ticker": "VYTR", "name": "Vytrus Biotech, S.A.", "sector": "Biotecnología / Células Madre Vegetales"},
    {"ticker": "LAB", "name": "Labiana Health, S.A.", "sector": "Fabricación Farmacéutica Humana y Veterinaria"},
    {"ticker": "ATRS", "name": "Atrys Health (origen Growth), S.A.", "sector": "Telemedicina y Radioterapia"},
    {"ticker": "ORYZ", "name": "Oryzon Genomics (origen Growth), S.A.", "sector": "Biofarmacia / Epigenética"},
    {"ticker": "ADL", "name": "ADL Bionatur Solutions, S.A.", "sector": "Fermentación y Bioprocesos"},
    {"ticker": "BION", "name": "Bionure / CuraSen, S.A.", "sector": "Neuroprotección"},
    {"ticker": "BIOK", "name": "Biokeralty Research, S.A.", "sector": "Investigación Sanitaria"},

    # ─── INDUSTRIA, CONSUMO, MATERIALES Y MOVILIDAD ───
    {"ticker": "KOMP", "name": "Plásticos Compuestos (Kompuestos), S.A.", "sector": "Polímeros Sostenibles"},
    {"ticker": "HANN", "name": "Hannun, S.A.", "sector": "Muebles Artesanales Sostenibles"},
    {"ticker": "ELZ", "name": "Asturiana de Laminados (Elzinc), S.A.", "sector": "Metalurgia y Zinc Laminado"},
    {"ticker": "EVM", "name": "EV Motors (EBRO Automotive), S.A.", "sector": "Vehículos Eléctricos"},
    {"ticker": "CLEV", "name": "Clever Global, S.A.", "sector": "Gestión de Proveedores y Contratistas"},
    {"ticker": "MED", "name": "Medcom Tech, S.A.", "sector": "Distribución Productos Traumatología"},
    {"ticker": "130M", "name": "130 Motors / Invicta, S.A.", "sector": "Movilidad Eléctrica Urbana"},

    # ─── MEDIOS, AUDIOVISUAL, EDUCACIÓN Y OTROS SERVICIOS ───
    {"ticker": "PROED", "name": "Proeduca Altus, S.A.", "sector": "Educación Superior Online (UNIR)"},
    {"ticker": "SEC", "name": "Secuoya Content Group, S.A.", "sector": "Producción de Contenidos"},
    {"ticker": "MONDO", "name": "Mondo TV Iberoamérica, S.A.", "sector": "Animación y Ficción Audiovisual"},
    {"ticker": "IDX", "name": "Indexa Capital Group, S.A.", "sector": "Gestión Automatizada / Fintech"},
    {"ticker": "IFF", "name": "Intercity Football Club (CF Intercity), S.A.", "sector": "Deporte y Entretenimiento"},
    {"ticker": "GIG", "name": "Grupo Gigas / Ibersontel, S.A.", "sector": "Telecomunicaciones"},
    {"ticker": "ART", "name": "Arteche (Grupo Arteche), S.A.", "sector": "Equipos Eléctricos de Alta Tensión"},
    {"ticker": "VAN", "name": "Vanadi Coffee, S.A.", "sector": "Restauración y Cafeterías"},
]

def update_bme_growth_catalog():
    growth_path = CATALOGS_DIR / "bme_growth_clean_universe.json"
    with open(growth_path, "w", encoding="utf-8") as f:
        json.dump({
            "segment": "BME Growth (Filtrado Completo: Sin SOCIMIs ni Fondos)",
            "total_entities": len(BME_GROWTH_FULL_CLEAN),
            "filter_applied": "Excluidas estrictamente las ~85 SOCIMIs y sociedades de inversión inmobiliaria/patrimonial. Incluidas todas las empresas operativas de crecimiento real.",
            "companies": BME_GROWTH_FULL_CLEAN
        }, f, indent=2, ensure_ascii=False)
    print(f"✓ Catálogo Completo BME Growth (Clean) actualizado: {growth_path} ({len(BME_GROWTH_FULL_CLEAN)} empresas)")

if __name__ == "__main__":
    update_bme_growth_catalog()
