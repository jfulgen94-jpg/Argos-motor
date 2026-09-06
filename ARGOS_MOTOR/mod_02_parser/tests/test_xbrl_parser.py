"""Tests for XBRL and USGAAP parsers."""
from mod_02_parser.src.xbrl_parser import XBRLParser
from mod_02_parser.src.usgaap_parser import USGAAPParser


def test_parse_ixbrl_html():
    sample_html = """
    <html>
        <body>
            <ix:nonFraction name="ifrs-full:Assets" unitRef="EUR">1500000</ix:nonFraction>
            <ix:nonFraction name="ifrs-full:Revenue" unitRef="EUR">850000</ix:nonFraction>
        </body>
    </html>
    """
    parser = XBRLParser()
    facts = parser.parse_ixbrl_html(sample_html, "LEI123", 2024)
    assert len(facts) == 2
    assert facts[0]["concept_std"] == "total_activo"
    assert facts[0]["value"] == 1500000.0


def test_parse_usgaap_xml():
    sample_xml = """
    <xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2024">
        <us-gaap:Assets unitRef="USD">5000000</us-gaap:Assets>
        <us-gaap:Revenues unitRef="USD">3200000</us-gaap:Revenues>
    </xbrl>
    """
    parser = USGAAPParser()
    facts = parser.parse_xbrl_xml(sample_xml, "LEI_US_123", 2024)
    assert len(facts) == 2
    assert facts[0]["concept_std"] == "total_activo"
    assert facts[0]["value"] == 5000000.0
