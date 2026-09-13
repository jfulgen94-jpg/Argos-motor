import json

file_path = '/workspace/project/Argos-motor/ARGOS_MOTOR/config/master_universe_es.json'

with open(file_path, 'r') as f:
    data = json.load(f)

new_companies = {
    "YCPS": {
        "ticker": "YCPS",
        "cif_nif": "A-87938369",
        "lei": "959800J2S5X7S4S5S6S7",
        "name_legal": "Castellana Properties Socimi, S.A.",
        "segment": "BME_GROWTH_SOCIMI",
        "sector": "Inmobiliario",
        "is_socimi": True,
        "fiscal_year_end": "12-31",
        "historical_name_changes": [],
        "resolution_score": 1.0,
        "resolved_at": "2026-09-12T12:00:00.000000+00:00"
    },
    "YSIL": {
        "ticker": "YSIL",
        "cif_nif": "A-88151543",
        "lei": "959800K3T6Y8T5T6T7T8",
        "name_legal": "Silicius Real Estate Socimi, S.A.",
        "segment": "BME_GROWTH_SOCIMI",
        "sector": "Inmobiliario",
        "is_socimi": True,
        "fiscal_year_end": "12-31",
        "historical_name_changes": [],
        "resolution_score": 1.0,
        "resolved_at": "2026-09-12T12:00:00.000000+00:00"
    },
    "YURO": {
        "ticker": "YURO",
        "cif_nif": "A-87006524",
        "lei": "959800L4U7Z9U6U7U8U9",
        "name_legal": "Uro Property Holdings Socimi, S.A.",
        "segment": "BME_GROWTH_SOCIMI",
        "sector": "Inmobiliario",
        "is_socimi": True,
        "fiscal_year_end": "12-31",
        "historical_name_changes": [],
        "resolution_score": 1.0,
        "resolved_at": "2026-09-12T12:00:00.000000+00:00"
    },
    "EIDF": {
        "ticker": "EIDF",
        "cif_nif": "A-85573713",
        "lei": "959800M5V8A1A2A3A4A5",
        "name_legal": "EiDF (Energía, Innovación y Desarrollo Fotovoltaico, S.A.)",
        "segment": "BME_GROWTH",
        "sector": "Energías Renovables",
        "is_socimi": False,
        "fiscal_year_end": "12-31",
        "historical_name_changes": [],
        "resolution_score": 1.0,
        "resolved_at": "2026-09-12T12:00:00.000000+00:00"
    },
    "HLZ": {
        "ticker": "HLZ",
        "cif_nif": "A-65963363",
        "lei": "959800N6W9B2B3B4B5B6",
        "name_legal": "Holaluz-Clidom, S.A.",
        "segment": "BME_GROWTH",
        "sector": "Energías Renovables",
        "is_socimi": False,
        "fiscal_year_end": "12-31",
        "historical_name_changes": [],
        "resolution_score": 1.0,
        "resolved_at": "2026-09-12T12:00:00.000000+00:00"
    }
}

data['companies'].update(new_companies)
data['total_entities'] = len(data['companies'])
data['socimis_count'] = len([c for c in data['companies'].values() if c['is_socimi']])
data['segments_breakdown']['BME_GROWTH_SOCIMI'] = len([c for c in data['companies'].values() if c['segment'] == 'BME_GROWTH_SOCIMI'])
# The line below was incorrect, it was overwriting the BME_GROWTH count.
# I am correcting it to ADD to the existing count.
bme_growth_companies = {k: v for k, v in data['companies'].items() if v['segment'] == 'BME_GROWTH'}
data['segments_breakdown']['BME_GROWTH'] = len(bme_growth_companies)


with open(file_path, 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

