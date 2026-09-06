"""Parser for European ESEF (inline XBRL / XHTML) packages."""
from pathlib import Path
from typing import Dict, Any, List
from bs4 import BeautifulSoup
from mod_02_parser.src.taxonomy_mapper import TaxonomyMapper


class XBRLParser:
    def __init__(self, taxonomy_mapper: TaxonomyMapper = None):
        self.mapper = taxonomy_mapper or TaxonomyMapper()

    def parse_ixbrl_html(self, content_str: str, entity_lei: str, fiscal_year: int) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(content_str, "html.parser")
        facts = []
        # Buscar etiquetas ix:nonFraction o ix:fraction
        for tag in soup.find_all(lambda t: t.name and ("nonfraction" in t.name.lower() or "fraction" in t.name.lower())):
            concept = tag.get("name", "")
            val_text = tag.text.strip().replace(",", "")
            try:
                val = float(val_text)
            except ValueError:
                continue
            canonical = self.mapper.map_concept(concept)
            if canonical:
                facts.append({
                    "entity_lei": entity_lei,
                    "fiscal_year": fiscal_year,
                    "concept_raw": concept,
                    "concept_std": canonical,
                    "value": val,
                    "unit": tag.get("unitref", "EUR"),
                })
        return facts
