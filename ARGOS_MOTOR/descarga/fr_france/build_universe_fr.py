"""
ARGOS MOTOR — GENERADOR DEL UNIVERSO MAESTRO INSTITUCIONAL DE FRANCIA
====================================================================
Compila el universo exhaustivo de empresas francesas:
  - CAC 40 (Blue Chips)
  - CAC Next 20 (Large Caps)
  - SBF 120 / CAC Mid 60 (Mid Caps)
  - Euronext Small & Euronext Growth (Pymes / Growth con ESEF activo)
  - Holdings extranjeros del CAC 40 (Airbus/NL, Stellantis/NL, etc.)

Cruza los 292 LEIs verificados de filings.xbrl.org con los índices de Euronext Paris.
"""

import json
import re
from datetime import datetime
from pathlib import Path

# Cargar las 292 entidades extraídas de XBRL.org
SCRATCH_JSON = Path(__file__).resolve().parents[3] / "scratch_fr_xbrl_entities.json"
if not SCRATCH_JSON.exists():
    SCRATCH_JSON = Path("scratch_fr_xbrl_entities.json")

def build_france_universe():
    with open(SCRATCH_JSON, "r", encoding="utf-8") as f:
        xbrl_entities = json.load(f)

    # Catálogos de referencia conocidos de Euronext Paris
    CAC40_CONSTITUENTS = {
        "AC": ("ACCOR", "Consumo / Hoteles"),
        "AI": ("AIR LIQUIDE", "Materiales / Gases Industriales"),
        "CS": ("AXA", "Finanzas / Seguros"),
        "BNP": ("BNP PARIBAS", "Finanzas / Banca"),
        "EN": ("BOUYGUES", "Industrial / Construccion"),
        "BVI": ("BUREAU VERITAS", "Servicios / Certificacion"),
        "CAP": ("CAPGEMINI", "Tecnologia / Consultoria IT"),
        "CA": ("CARREFOUR", "Consumo / Distribucion"),
        "ACA": ("CREDIT AGRICOLE", "Finanzas / Banca"),
        "BN": ("DANONE", "Consumo / Alimentacion"),
        "DSY": ("DASSAULT SYSTEMES", "Tecnologia / Software"),
        "EDEN": ("EDENRED", "Industrial / Servicios Transaccionales"),
        "ENGI": ("ENGIE", "Utilities / Gas y Energia"),
        "EL": ("ESSILORLUXOTTICA", "Salud / Optica y Lujo"),
        "RMS": ("HERMES INTERNATIONAL", "Consumo / Lujo"),
        "KER": ("KERING", "Consumo / Lujo"),
        "OR": ("L'OREAL", "Consumo / Cosmeticos"),
        "LR": ("LEGRAND", "Industrial / Equipamiento Electrico"),
        "MC": ("LVMH MOET HENNESSY LOUIS VUITTON", "Consumo / Lujo"),
        "ML": ("MICHELIN", "Industrial / Neumaticos"),
        "ORA": ("ORANGE", "Telecomunicaciones / Operador"),
        "RI": ("PERNOD RICARD", "Consumo / Bebidas"),
        "PUB": ("PUBLICIS GROUPE", "Comunicaciones / Publicidad"),
        "RNO": ("RENAULT", "Consumo / Automovil"),
        "SAF": ("SAFRAN", "Aeroespacial / Defensa"),
        "SGO": ("SAINT-GOBAIN", "Industrial / Materiales"),
        "SAN": ("SANOFI", "Salud / Farmaceutico"),
        "SU": ("SCHNEIDER ELECTRIC", "Industrial / Gestion de Energia"),
        "GLE": ("SOCIETE GENERALE", "Finanzas / Banca"),
        "TEP": ("TELEPERFORMANCE", "Comunicaciones / Outsourcing"),
        "HO": ("THALES", "Aeroespacial / Defensa y Seguridad"),
        "TTE": ("TOTALENERGIES", "Energia / Petroleo y Gas"),
        "URW": ("UNIBAIL-RODAMCO-WESTFIELD", "Inmobiliario / SIIC Retail"),
        "VIE": ("VEOLIA ENVIRONNEMENT", "Utilities / Medio Ambiente y Aguas"),
        "DG": ("VINCI", "Industrial / Concesiones y Construccion"),
    }

    # CAC Next 20
    CAC_NEXT20 = {
        "AF": ("AIR FRANCE - KLM", "Aerolineas / Transporte"),
        "AKE": ("ARKEMA", "Quimica Especializada"),
        "BIM": ("BIOMERIEUX", "Salud / Diagnostico"),
        "FGR": ("EIFFAGE", "Construccion y Concesiones"),
        "ENX": ("EURONEXT", "Servicios Financieros / Bolsas"),
        "EO": ("FORVIA", "Automocion / Componentes"),
        "GFC": ("GECINA", "Inmobiliario / SIIC Oficinas"),
        "GET": ("GETLINK", "Transporte / Tunel Canal"),
        "LI": ("KLEPIERRE", "Inmobiliario / SIIC Centros Comerciales"),
        "RCO": ("REMY COINTREAU", "Consumo / Bebidas"),
        "RXL": ("REXEL", "Distribucion Electrica"),
        "DIM": ("SARTORIUS STEDIM BIOTECH", "Salud / Biotecnologia"),
        "SW": ("SODEXO", "Servicios / Restauracion Colectiva"),
        "SOI": ("SOITEC", "Tecnologia / Semiconductores"),
        "UBI": ("UBISOFT ENTERTAINMENT", "Tecnologia / Videojuegos"),
        "FR": ("VALEO", "Automocion / Componentes"),
        "VIV": ("VIVENDI", "Medios y Entretenimiento"),
    }

    # Componentes con sede fuera de Francia (NL/LU) pero cotizados en CAC 40
    FOREIGN_CAC40 = {
        "AIR": {
            "ticker": "AIR",
            "name_legal": "Airbus SE",
            "lei": "2138006MO74EAPV35Y72",
            "segment": "CAC40_FOREIGN_NL",
            "country_incorporation": "NL",
            "supervisor": "AFM (Netherlands) / Euronext Paris",
            "note": "Cotizada en CAC 40; reporting ESEF bajo AFM Holanda"
        },
        "MT": {
            "ticker": "MT",
            "name_legal": "ArcelorMittal SA",
            "lei": "2138001EP3E3725F5670",
            "segment": "CAC40_FOREIGN_LU",
            "country_incorporation": "LU",
            "supervisor": "CSSF (Luxembourg) / Euronext Paris",
            "note": "Cotizada en CAC 40; reporting ESEF bajo CSSF Luxemburgo"
        },
        "ERF": {
            "ticker": "ERF",
            "name_legal": "Eurofins Scientific SE",
            "lei": "529900JEFHUWR19O3642",
            "segment": "CAC40_FOREIGN_LU",
            "country_incorporation": "LU",
            "supervisor": "CSSF (Luxembourg) / Euronext Paris",
            "note": "Cotizada en CAC 40; reporting ESEF bajo CSSF Luxemburgo"
        },
        "STLAM": {
            "ticker": "STLAM",
            "name_legal": "Stellantis NV",
            "lei": "549300LKT3UKJEW8KW64",
            "segment": "CAC40_FOREIGN_NL",
            "country_incorporation": "NL",
            "supervisor": "AFM (Netherlands) / Euronext Paris",
            "note": "Cotizada en CAC 40; reporting ESEF bajo AFM Holanda"
        },
        "STMPA": {
            "ticker": "STMPA",
            "name_legal": "STMicroelectronics NV",
            "lei": "213800Z8OHIZUDWIPQ83",
            "segment": "CAC40_FOREIGN_NL",
            "country_incorporation": "NL",
            "supervisor": "AFM (Netherlands) / Euronext Paris",
            "note": "Cotizada en CAC 40; reporting ESEF bajo AFM Holanda"
        }
    }

    # SBF 120 / CAC Mid 60 conocidos
    MID_CAPS_KEYWORDS = [
        "ALTEN", "ALBIOMA", "AMUNDI", "APERAM", "BIC", "BENETEAU", "CARMILA",
        "CLARIANE", "DERICHEBOURG", "ELIOR", "ELIS", "ERAMET", "FNAC DARTY",
        "GAZTRANSPORT", "ICADE", "IMERYS", "INTERPARFUMS", "IPSOS", "MAISONS DU MONDE",
        "METROPOLE TELEVISION", "M6", "NEXANS", "NEXITY", "RUBIS", "SCOR",
        "SES-IMAGOTAG", "SOPRA STERIA", "SPIE", "TELEVISION FRANCAISE 1", "TF1",
        "TRIGANO", "VALLOUREC", "VERALLIA", "VICAT", "VIRBAC", "ALSTOM",
        "AEROPORTS DE PARIS", "ANTIN", "ATOS", "CASINO", "COFACE", "COVIVIO",
        "DASSAULT AVIATION", "EURAZEO", "FDJ", "FRANCAISE DES JEUX", "GTT",
        "JCDECAUX", "KORIAN", "LISI", "MCPHY", "NEOEN", "OVH", "PLASTIC OMNIUM",
        "OPMOBILITY", "SES", "SOLUTIONS 30", "SOMFY", "TARKETT", "VALNEVA", "VILMORIN",
        "VOLTALIA", "WAVESTONE", "WORLDLINE"
    ]

    master_universe = {
        "version": "2.0.0",
        "jurisdiction": "FR",
        "country_name": "France",
        "supervisor": "AMF / Euronext Paris",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "summary": {
            "total_entities": 0,
            "segments_breakdown": {
                "CAC40": 0,
                "CAC_NEXT20": 0,
                "SBF120_MID60": 0,
                "EURONEXT_GROWTH_SMALL": 0,
                "CAC40_FOREIGN_HOLDINGS": len(FOREIGN_CAC40)
            }
        },
        "companies": {}
    }

    # Añadir los holdings extranjeros del CAC 40
    for tick, info in FOREIGN_CAC40.items():
        master_universe["companies"][tick] = info

    # Clasificar las 292 entidades francesas de XBRL.org
    for lei, ent in xbrl_entities.items():
        name = ent["name"].strip()
        name_clean = re.sub(r'[^A-Z0-9 ]', '', name.upper())
        years = ent.get("years", [])

        # Determinar segmento
        segment = "EURONEXT_GROWTH_SMALL"
        ticker = None
        sector = "Diversificado"

        # 1. ¿Es CAC 40?
        for t, (c_name, sec) in CAC40_CONSTITUENTS.items():
            if c_name in name_clean or name_clean in c_name:
                segment = "CAC40"
                ticker = t
                sector = sec
                break

        # 2. ¿Es CAC Next 20?
        if segment == "EURONEXT_GROWTH_SMALL":
            for t, (c_name, sec) in CAC_NEXT20.items():
                if c_name in name_clean or name_clean in c_name:
                    segment = "CAC_NEXT20"
                    ticker = t
                    sector = sec
                    break

        # 3. ¿Es SBF 120 / Mid Cap?
        if segment == "EURONEXT_GROWTH_SMALL":
            for kw in MID_CAPS_KEYWORDS:
                if kw in name_clean:
                    segment = "SBF120_MID60"
                    sector = "Media Capitalizacion / Industria y Servicios"
                    break

        # Generar ticker representativo si no tiene
        if not ticker:
            ticker = name_clean.split()[0][:6]
            if len(ticker) < 2:
                ticker = f"FR_{lei[:6]}"

        # Asegurar unicidad de clave
        comp_key = ticker
        counter = 1
        while comp_key in master_universe["companies"]:
            comp_key = f"{ticker}_{counter}"
            counter += 1

        master_universe["companies"][comp_key] = {
            "ticker": ticker,
            "lei": lei,
            "name_legal": name,
            "segment": segment,
            "sector": sector,
            "country_code": "FR",
            "supervisor": "AMF / Euronext Paris",
            "available_esef_years": years,
            "total_esef_filings": ent.get("total_reports", len(years)),
            "extraction_methods": {
                "2020_2026": "ESEF_ZIP_DIRECT",
                "2012_2019": "AMF_URD_PDF_CRAWLER"
            },
            "source": {
                "filings_xbrl_url": f"https://filings.xbrl.org/api/filings?filter[country]=FR",
                "gleif_url": f"https://api.gleif.org/api/v1/lei-records/{lei}"
            }
        }

    # Recalcular conteos
    total = len(master_universe["companies"])
    master_universe["summary"]["total_entities"] = total
    for c in master_universe["companies"].values():
        seg = c.get("segment", "EURONEXT_GROWTH_SMALL")
        if seg in master_universe["summary"]["segments_breakdown"]:
            master_universe["summary"]["segments_breakdown"][seg] += 1
        elif "FOREIGN" in seg:
            pass # Ya contabilizado

    out_file = Path("ARGOS_MOTOR/config/master_universe_fr.json")
    out_file.write_text(json.dumps(master_universe, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"=== UNIVERSO MAESTRO INSTITUCIONAL FRANCIA GENERADO EXITOSAMENTE ===")
    print(f"Ruta: {out_file}")
    print(f"Total entidades integradas: {total}")
    for seg, cnt in master_universe["summary"]["segments_breakdown"].items():
        print(f"  - {seg}: {cnt}")

if __name__ == '__main__':
    build_france_universe()
