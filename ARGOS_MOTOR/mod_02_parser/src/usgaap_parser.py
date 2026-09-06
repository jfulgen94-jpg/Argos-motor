"""Parser for SEC EDGAR US-GAAP XBRL XML submissions."""
from bs4 import BeautifulSoup
from typing import Dict, Any, List
from mod_02_parser.src.taxonomy_mapper import TaxonomyMapper


class USGAAPParser:
    def __init__(self, taxonomy_mapper: TaxonomyMapper = None):
        self.mapper = taxonomy_mapper or TaxonomyMapper()

    def parse_xbrl_xml(self, xml_content: str, entity_lei: str, fiscal_year: int) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(xml_content, "xml")
        facts = []
        for tag in soup.find_all(True):
            full_concept = f"{tag.prefix}:{tag.name}" if tag.prefix else tag.name
            if "us-gaap" in full_concept.lower() or tag.prefix == "us-gaap":
                try:
                    val = float(tag.text.strip().replace(",", ""))
                except (ValueError, TypeError):
                    continue
                canonical = self.mapper.map_concept(full_concept) or self.mapper.map_concept(tag.name)
                if canonical:
                    facts.append({
                        "entity_lei": entity_lei,
                        "fiscal_year": fiscal_year,
                        "concept_raw": full_concept,
                        "concept_std": canonical,
                        "value": val,
                        "unit": tag.get("unitRef", "USD"),
                    })
        return facts
