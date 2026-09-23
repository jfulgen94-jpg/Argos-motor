#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STATER / ARGOS MOTOR — Generador del mapa de slugs corporativos EQS / DGAP
==========================================================================
Lee:     ARGOS_MOTOR/config/prime_standard_companies.json (172 emisores Prime Standard)
Escribe: ARGOS_MOTOR/config/eqs_company_slugs.json

Para cada empresa produce una lista ORDENADA de slugs candidatos (2-5) para que
el descargador / crawler pruebe la existencia de los PDFs en:
  https://irpages2.eqs.com/Download/Companies/{CompanySlug}/Annual%20Reports/{ISIN}-JA-{Year}-EQ-D-{Version}.pdf

Reglas aplicadas:
  1. Nombre común sin espacios ni caracteres especiales.
  2. Nombre comercial limpio en PascalCase / Upper.
  3. Alias históricos / fusiones previas (CRÍTICO 2012-2020) -> tabla HISTORICAL_ALIASES por ISIN.
  4. Ticker en mayúsculas y minúsculas como fallback final.
"""

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INPUT_FILE = ROOT / "config" / "prime_standard_companies.json"
OUTPUT_FILE = ROOT / "config" / "eqs_company_slugs.json"

MAX_SLUGS = 5

HISTORICAL_ALIASES = {
    # --- Renombrados / fusiones críticas para el periodo 2012-2020 ---
    "DE0007100000": ["Daimler", "MercedesBenz", "Mercedes-Benz"],            # Mercedes-Benz Group AG (ex Daimler)
    "DE0006047004": ["HeidelbergCement", "HeidelbergMaterials"],              # Heidelberg Materials (ex HeidelbergCement)
    "NL0000235190": ["eads", "Airbus", "EADS"],                               # Airbus SE (ex EADS N.V.)
    "DE0005552004": ["DeutschePost", "dhl", "DHL"],                           # DHL Group (ex Deutsche Post)
    "DE0005785604": ["Fresenius"],                                            # Fresenius
    "DE0005785802": ["FMC", "FreseniusMedicalCare"],                          # Fresenius Medical Care
    "DE0008430026": ["MunichRe", "MuenchenerRueck"],                          # Munich Re (Münchener Rück)
    "DE0008402215": ["HannoverRueck", "HannoverRe"],                          # Hannover Rueck SE
    "DE0007500001": ["Thyssenkrupp", "thyssenkrupp"],                         # thyssenkrupp AG
    "DE000NCA0001": ["thyssenkruppnucera", "ThyssenkruppNucera", "Thyssenkrupp"],  # thyssenkrupp nucera
    "DE0007664005": ["Volkswagen", "volkswagen"],                             # Volkswagen AG (stam shares)
    "DE0007664039": ["Volkswagen", "volkswagen"],                             # Volkswagen Vz.
    "DE000BAY0017": ["Bayer"],                                                # Bayer AG
    "DE0008404005": ["Allianz"],                                              # Allianz SE
    "DE0005557508": ["DeutscheTelekom", "Telekom"],                           # Deutsche Telekom AG
    "DE0005140008": ["DeutscheBank"],                                         # Deutsche Bank AG
    "DE000CBK1001": ["Commerzbank"],                                          # Commerzbank AG
    "DE0007037129": ["RWE"],                                                  # RWE AG
    "DE000ENAG999": ["EON", "E.ON"],                                          # E.ON SE
    "DE0007164600": ["SAP"],                                                  # SAP SE
    "DE000BASF111": ["BASF"],                                                 # BASF SE
    "DE0005190003": ["BMW", "BayerischeMotorenWerke"],                        # BMW AG (Vorzüge)
    "DE0005190037": ["BMW", "BayerischeMotorenWerke"],                        # BMW AG (Stämme)
    "DE0007236101": ["Siemens", "SIEMENS"],                                   # Siemens AG
    "DE000A0LAUP1": ["SiemensEnergy", "SiemensEnergyAG"],                     # Siemens Energy AG
    "DE0007201107": ["Continental", "CONTI"],                                 # Continental AG
    "DE0006231004": ["Infineon", "InfineonTechnologies"],                     # Infineon Technologies
    "DE0005558696": ["DeutscheBoerse", "DeutscheBorse"],                      # Deutsche Börse AG
    "DE000A1EWWW0": ["adidas", "Adidas"],                                     # adidas AG
    "DE000ZAL1111": ["Zalando"],                                              # Zalando SE
    "DE000A1ML7J1": ["Vonovia", "vonovia"],                                   # Vonovia SE
    "DE0006062144": ["Covestro"],                                             # Covestro AG
    "DE000DTR0CK8": ["DaimlerTruck", "DaimlerTruckHolding"],                  # Daimler Truck Holding AG
    "DE0008232125": ["Lufthansa", "DeutscheLufthansa", "DLH"],                # Deutsche Lufthansa AG
    "DE000FTG1111": ["flatexDEGIRO", "flatex", "BIWAG"],                      # flatexDEGIRO (ex biw AG / flatex)
    "DE0007472060": ["Wirecard"],                                             # Wirecard AG
    "DE0005428007": ["comdirect", "comdirectbank"],                           # comdirect bank
    "DE0005470306": ["CTSEventim"],                                           # CTS Eventim
    "DE0005403901": ["CEWE"],                                                 # CEWE Stiftung
    "DE000LEG1110": ["LEGImmobilien"],                                        # LEG Immobilien SE
}

def deumlaut(s: str) -> str:
    """ä->ae, ö->oe, ü->ue, ß->ss (convención alemana clásica para slugs)."""
    return (s.replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
             .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
             .replace("ß", "ss"))

def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

LEGAL_SUFFIXES = [
    "Aktiengesellschaft", "Kommanditgesellschaft auf Aktien", "KGaA",
    "GmbH & Co. KGaA", "GmbH & Co. KG", "SE & Co. KGaA", "Stiftung & Co. KGaA",
    "AG & Co. KGaA", "Holding AG", "Verwaltungs GmbH",
    "SE", "AG", "GmbH", "KG", "OHG", "PartG", "eG", "nv", "plc", "N.V.", "S.A.",
]

def clean_name(name: str) -> str:
    """Elimina sufijos legales y ruido ('&', '.', ',') del nombre."""
    n = re.sub(r"\(.*?\)", " ", name)
    for suf in LEGAL_SUFFIXES:
        n = re.sub(r"(?i)\b%s\b" % re.escape(suf), " ", n)
    n = n.replace("&", " ").replace(".", " ").replace(",", " ")
    n = re.sub(r"[^A-Za-zÀ-ÿ0-9\s\-/]", " ", n)
    return re.sub(r"\s+", " ", n).strip()

def pascal(s: str) -> str:
    out = []
    for w in re.split(r"[\s\-/]+", s):
        if not w:
            continue
        if w.isupper() and len(w) <= 5:      # siglas: BASF, RWE, SAP, MTU...
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return "".join(out)

def compact(name: str) -> str:
    """Nombre sin espacios ni caracteres especiales."""
    base = pascal(clean_name(deumlaut(strip_accents(name))))
    return re.sub(r"[^A-Za-z0-9]", "", base)

def build_slugs(rec: dict) -> list:
    ticker = rec["ticker"]
    isin = rec.get("isin", "")
    common = rec.get("name_common", "") or ""
    legal = rec.get("name_legal", "") or ""

    candidates = []

    # Regla 3: alias históricos/corporativos (prioridad máxima)
    candidates.extend(HISTORICAL_ALIASES.get(isin, []))

    # Regla 1: nombre común compactado
    c1 = compact(common)
    if c1:
        candidates += [c1, c1.upper()]

    # Regla 2: nombre legal compactado (PascalCase limpio)
    c2 = compact(legal)
    if c2 and c2 != c1:
        candidates.append(c2)

    # Variante lower del nombre común (EQS usa a veces minúsculas: eads, dhl, adidas)
    if c1:
        candidates.append(c1.lower())

    # Regla 4: ticker como fallback final (mayúsculas y minúsculas)
    candidates += [ticker.upper(), ticker.lower()]

    # Dedup preservando orden
    seen, out = set(), []
    for s in candidates:
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out[:MAX_SLUGS]

def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Archivo de entrada no encontrado: {INPUT_FILE}")

    companies_raw = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    result = {}
    for rec in companies_raw:
        result[rec["ticker"]] = {
            "isin": rec.get("isin", ""),
            "name": rec.get("name_legal") or rec.get("name_common", ""),
            "slugs": build_slugs(rec),
        }

    payload = {
        "_metadata": {
            "generated_at": date.today().isoformat(),
            "total_companies": len(result),
            "purpose": "EQS / DGAP corporate storage slug mappings for German listed issuers",
            "source_config": "ARGOS_MOTOR/config/prime_standard_companies.json",
            "url_template": "https://irpages2.eqs.com/Download/Companies/{CompanySlug}/Annual%20Reports/{ISIN}-JA-{Year}-EQ-D-{Version}.pdf",
        },
        "companies": result,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK -> {OUTPUT_FILE} ({len(result)} empresas generadas)")

if __name__ == "__main__":
    main()
