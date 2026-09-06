"""
Resuelve los 18 LEIs restantes buscando el CIF/NIF o la denominación social en el texto de los XHTML.
"""

import sys, re, requests
from pathlib import Path
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

LEIS = [
    "549300EQ15OJK3S3LL42",
    "549300GJVY6K3NC8MA89",
    "95980007WW7TNTYX8B36",
    "9598000XPMA4HRVG3Z89",
    "959800FJKW0UGKWEKN36",
    "959800GQ29X3QTKYUM69",
    "959800MAFGMXMGJHCH48",
    "959800RCPA4USH4RFB78",
    "959800TVV5HTKGAPCW40",
    "959800V35MGZXBNZP485",
    "9598002PHMH00MHN3741",
    "95980049KFSE6UNLSJ86",
    "959800XL1Q2FK0S18W48",
    "8EWQ2UQKS07AKK8ANH81",
    "959800BWQT8L5QURPM06",
    "95980020140005309084",
    "9598006D23D7P4E94814",
    "959800QE24B01E226068"
]

def query_gleif(lei):
    url = f"https://api.gleif.org/api/v1/lei-records/{lei}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            legal_name = data.get("data", {}).get("attributes", {}).get("entity", {}).get("legalName", {}).get("name", "")
            return legal_name
    except:
        pass
    return None

def resolve_all():
    print("Consultando API oficial GLEIF para resolución exacta de los 18 LEIs...")
    mapping = {}
    for lei in LEIS:
        name = query_gleif(lei)
        print(f"• {lei} -> {name}")
        if name:
            mapping[lei[:8]] = name
            
    print("\nResultado JSON:")
    import json
    print(json.dumps(mapping, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    resolve_all()
