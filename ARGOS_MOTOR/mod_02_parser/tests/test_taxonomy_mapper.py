"""
Tests unitarios para MOD_02: Taxonomy Mapper.
Verifica que conceptos IFRS, US-GAAP y PGC se normalizan correctamente.
"""
import pytest
from mod_02_parser.src.taxonomy_mapper import TaxonomyMapper


def test_taxonomy_mapper_mappings():
    mapper = TaxonomyMapper()
    
    # IFRS
    assert mapper.map_concept("ifrs-full:Assets") == "total_activo"
    assert mapper.map_concept("ifrs-full:Revenue") == "revenue"
    assert mapper.map_concept("ifrs-full:ProfitLoss") == "beneficio_neto"
    assert mapper.map_concept("ifrs-full:NoncurrentAssets") == "activo_no_corriente"
    
    # US-GAAP
    assert mapper.map_concept("us-gaap:Assets") == "total_activo"
    assert mapper.map_concept("us-gaap:Revenues") == "revenue"
    assert mapper.map_concept("us-gaap:NetIncomeLoss") == "beneficio_neto"
    assert mapper.map_concept("us-gaap:StockholdersEquity") == "patrimonio_neto"
    assert mapper.map_concept("us-gaap:CashAndCashEquivalentsAtCarryingValue") == "efectivo_y_equivalentes"
    
    # PGC 2007 (España)
    assert mapper.map_concept("pgc:TotalActivo") == "total_activo"
    assert mapper.map_concept("pgc:ImporteNetoDeLaCifraDeNegocios") == "revenue"
    
    # Concepto no mapeado
    assert mapper.map_concept("custom_tag:unknown_metric") is None
