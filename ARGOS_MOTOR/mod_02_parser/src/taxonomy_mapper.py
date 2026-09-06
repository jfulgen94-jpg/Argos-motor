"""
STATER MOTOR ARGOS — MOD_02: Taxonomy Mapper.
Mapea conceptos XBRL (IFRS, US-GAAP, PGC) a los campos canónicos de STATER
utilizando el diccionario configurado en config/taxonomy_dict.yaml.
"""
from pathlib import Path
from typing import Optional, Dict, Any
import yaml
import re

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "taxonomy_dict.yaml"


class TaxonomyMapper:
    """Mapeador canónico de conceptos contables transatlánticos."""

    def __init__(self, config_path: Optional[Path] = None):
        cfg = config_path or CONFIG_PATH
        self.raw_concept_to_canonical: Dict[str, str] = {}
        self.canonical_to_statement: Dict[str, str] = {}
        self._load_config(cfg)

    def _load_config(self, cfg_path: Path) -> None:
        if not cfg_path.exists():
            return
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            
        mappings = data.get("mappings", {})
        for canonical, details in mappings.items():
            self.canonical_to_statement[canonical] = details.get("statement", "OTHER")
            for tax_type in ["ifrs", "us_gaap", "pgc"]:
                for concept in details.get(tax_type, []):
                    # Guardar con prefijo y sin prefijo para máxima robustez
                    self.raw_concept_to_canonical[concept.lower()] = canonical
                    if ":" in concept:
                        clean_name = concept.split(":")[-1].lower()
                        self.raw_concept_to_canonical[clean_name] = canonical

    def map_concept(self, concept_name: str) -> Optional[str]:
        """
        Retorna el nombre canónico de STATER (ej: 'total_activo') dado un concepto XBRL.
        """
        clean = concept_name.strip().lower()
        if clean in self.raw_concept_to_canonical:
            return self.raw_concept_to_canonical[clean]
        
        # Intentar buscar sin prefijo (ej: ifrs-full:Assets -> assets)
        if ":" in clean:
            no_prefix = clean.split(":")[-1]
            if no_prefix in self.raw_concept_to_canonical:
                return self.raw_concept_to_canonical[no_prefix]
                
        return None
