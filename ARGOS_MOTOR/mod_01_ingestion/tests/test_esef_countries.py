"""
Tests unitarios para la división de ingesta ESEF en 5 países (ES, FR, DE, IT, NL) y el OAM Router.
"""
import pytest
from pathlib import Path
from mod_01_ingestion.src.oam_router import OAMRouter
from mod_01_ingestion.src.es_cnmv_client import CNMVClient
from mod_01_ingestion.src.fr_amf_client import AMFClient
from mod_01_ingestion.src.de_bafin_client import BaFinClient
from mod_01_ingestion.src.it_consob_client import CONSOBClient
from mod_01_ingestion.src.nl_afm_client import AFMClient


def test_oam_router_resolution():
    router = OAMRouter()
    
    assert isinstance(router.get_client("ES"), CNMVClient)
    assert isinstance(router.get_client("CNMV"), CNMVClient)
    
    assert isinstance(router.get_client("FR"), AMFClient)
    assert isinstance(router.get_client("AMF"), AMFClient)
    
    assert isinstance(router.get_client("DE"), BaFinClient)
    assert isinstance(router.get_client("BAFIN"), BaFinClient)
    
    assert isinstance(router.get_client("IT"), CONSOBClient)
    assert isinstance(router.get_client("CONSOB"), CONSOBClient)
    
    assert isinstance(router.get_client("NL"), AFMClient)
    assert isinstance(router.get_client("AFM"), AFMClient)


def test_es_cnmv_doc_id_format():
    client = CNMVClient()
    doc_id = client.build_doc_id("5493006MHB84DD0ZWV18", 2024, "ESEF")
    assert doc_id == "ES_CNMV_5493006MHB84DD0ZWV18_2024_ESEF"


def test_fr_amf_doc_id_format():
    client = AMFClient()
    doc_id = client.build_doc_id("969500TXZMVB796DFZ39", 2024, "ESEF")
    assert doc_id == "FR_AMF_969500TXZMVB796DFZ39_2024_ESEF"


def test_de_bafin_doc_id_format():
    client = BaFinClient()
    doc_id = client.build_doc_id("529900ODI3047E2LIV03", 2024, "ESEF")
    assert doc_id == "DE_BAFIN_529900ODI3047E2LIV03_2024_ESEF"


def test_it_consob_doc_id_format():
    client = CONSOBClient()
    doc_id = client.build_doc_id("8156008227B2284C8F52", 2024, "ESEF")
    assert doc_id == "IT_CONSOB_8156008227B2284C8F52_2024_ESEF"


def test_nl_afm_doc_id_format():
    client = AFMClient()
    doc_id = client.build_doc_id("72450096YD635APRA878", 2024, "ESEF")
    assert doc_id == "NL_AFM_72450096YD635APRA878_2024_ESEF"
