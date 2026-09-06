"""Unit tests for MOD_03 NLP & Forensic components."""
from mod_03_nlp_audit.src.iagc_extractor import IAGCExtractor
from mod_03_nlp_audit.src.greenwashing_detector import GreenwashingDetector


def test_iagc_extractor():
    extractor = IAGCExtractor()
    res = extractor.extract_board_metrics("Board composition text...")
    assert res["independent_directors_pct"] == 50.0
    assert res["women_directors_pct"] == 40.0


def test_greenwashing_detector():
    detector = GreenwashingDetector()
    res = detector.detect_inconsistencies(["We are 100% green"], actual_emissions_trend=0.15)
    assert res["greenwashing_flag"] is True
