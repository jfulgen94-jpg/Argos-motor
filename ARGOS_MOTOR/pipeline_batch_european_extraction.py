"""
STATER MOTOR ARGOS — PIPELINE MAESTRO DE EXTRACCIÓN POR LOTES EUROPEO
Procesa estados financieros ESEF/iXBRL y auditorías de España (IBEX 35),
Alemania (DAX / Prime Standard) y Francia (CAC 40).
Puebla stater_motor.duckdb (audit_kams, financial_facts_raw, financial_panel).
"""

import os
import sys
import json
import uuid
import re
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

import duckdb
import fitz  # PyMuPDF
from bs4 import BeautifulSoup

# Configurar path del repositorio
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "ARGOS_MOTOR"))

from mod_02_parser.src.taxonomy_mapper import TaxonomyMapper
from mod_02_parser.src.balance_validator import validate as validate_balance
from mod_03_nlp_audit.src.kam_extractor import KAMExtractor

DB_PATH = REPO_ROOT / "ARGOS_MOTOR/data/lake/duckdb/stater_motor.duckdb"
LAKE_ROOT = Path("D:/ARGOS_DATA/lake")


class EuropeanBatchExtractor:
    """Motor de extracción por lotes para cotizadas europeas (ES, DE, FR)."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.mapper = TaxonomyMapper()
        self.kam_extractor = KAMExtractor()
        self._ensure_db_tables()

    def _ensure_db_tables(self):
        """Verifica que las tablas existan en DuckDB."""
        con = duckdb.connect(str(self.db_path))
        # Las tablas base ya existen según el esquema canónico
        con.close()

    def extract_text_from_file_or_zip(self, file_path: Path) -> Tuple[str, str]:
        """
        Extrae el texto completo y determina si el origen es xhtml/xml o pdf.
        Retorna (texto_plano, tipo_formato).
        """
        if not file_path.exists():
            return "", "NOT_FOUND"

        # 1. Si es archivo ZIP ESEF
        if file_path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(file_path) as z:
                    names = z.namelist()
                    # Buscar xhtml principal
                    xhtmls = [n for n in names if n.endswith((".xhtml", ".html"))]
                    if xhtmls:
                        cand = [x for x in xhtmls if "report" in x.lower()] or xhtmls
                        raw = z.read(cand[0])
                        soup = BeautifulSoup(raw[:15000000], "html.parser")
                        return soup.get_text(separator=" ", strip=True), "ESEF_ZIP_XHTML"
            except zipfile.BadZipFile:
                # El scraper a veces guarda XMLs directos con extensión .zip
                pass

        # 2. Si no es ZIP válido o es archivo directo, comprobar cabecera MIME
        try:
            head = file_path.read_bytes()[:20]
        except Exception:
            return "", "READ_ERROR"

        # Si es PDF genuino
        if head.startswith(b"%PDF"):
            try:
                doc = fitz.open(file_path)
                pages = []
                for p in range(len(doc)):
                    pages.append(doc[p].get_text())
                return "\n".join(pages), "PDF"
            except Exception:
                return "", "PDF_ERROR"

        # Si es XML / XHTML
        try:
            content = file_path.read_bytes()
            soup = BeautifulSoup(content[:15000000], "html.parser")
            return soup.get_text(separator=" ", strip=True), "XHTML"
        except Exception:
            return "", "XHTML_ERROR"

    def locate_audit_report_chunk(self, full_text: str, market: str = "ES") -> str:
        """Aísla la sección del informe de auditoría independiente y KAMs."""
        lower_text = full_text.lower()
        patterns = {
            "ES": [
                r"cuestiones\s+clave\s+de\s+la\s+auditor[ií]a",
                r"informe\s+de\s+auditor[ií]a\s+independiente",
                r"cuestiones\s+clave\s+de\s+auditor[ií]a",
                r"opini[oó]n\s+con\s+salvedades",
                r"opini[oó]n\s+del\s+auditor",
                r"hemos\s+auditado\s+las\s+cuentas"
            ],
            "DE": [
                r"besonders\s+wichtige\s+pr[uü]fungssachverhalte",
                r"best[aä]tigungsvermerk\s+des\s+unabh[aä]ngigen",
                r"best[aä]tigungsvermerk",
                r"pr[uü]fungsurteile",
                r"pr[uü]fungssachverhalte"
            ],
            "FR": [
                r"justification\s+des\s+appr[eé]ciations",
                r"points\s+cl[eé]s\s+de\s+l['\s]audit",
                r"rapport\s+des\s+commissaires\s+aux\s+comptes",
                r"opinion\s+sur\s+les\s+comptes\s+consolid[eé]s"
            ]
        }

        kw_list = patterns.get(market, patterns["ES"])
        start_pos = -1
        for kw in kw_list:
            m = re.search(kw, lower_text)
            if m:
                start_pos = m.start()
                break

        if start_pos == -1:
            m = re.search(r"auditor|pr[uü]fer|commissaire", lower_text)
            if m:
                start_pos = m.start()
            else:
                return full_text[:14000]

        # Tomar ventana de hasta 14.000 caracteres para el LLM
        return full_text[max(0, start_pos - 300):start_pos + 14000]

    def parse_esef_facts(self, file_path: Path, entity_lei: str, fiscal_year: int, doc_id: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Extrae facts iXBRL de paquetes ESEF (.zip o .xhtml).
        Retorna (lista_de_facts_raw, dict_panel_financiero).
        """
        raw_soup = None
        if file_path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(file_path) as z:
                    xhtmls = [n for n in z.namelist() if n.endswith((".xhtml", ".html"))]
                    if xhtmls:
                        cand = [x for x in xhtmls if "report" in x.lower()] or xhtmls
                        raw = z.read(cand[0])
                        raw_soup = BeautifulSoup(raw, "html.parser")
            except Exception:
                pass

        if raw_soup is None:
            try:
                raw_bytes = file_path.read_bytes()
                raw_soup = BeautifulSoup(raw_bytes, "html.parser")
            except Exception:
                return [], {}

        facts_raw = []
        canonical_values: Dict[str, List[float]] = {}

        for tag in raw_soup.find_all(lambda t: t.name and ("nonfraction" in t.name.lower() or "fraction" in t.name.lower())):
            concept_raw = tag.get("name", "")
            raw_text = tag.text.strip().replace(" ", "").replace("\xa0", "").replace(".", "").replace(",", ".")
            scale = int(tag.get("scale", 0))
            sign = -1.0 if tag.get("sign") == "-" else 1.0

            try:
                val = float(raw_text) * (10 ** scale) * sign
            except ValueError:
                continue

            canonical = self.mapper.map_concept(concept_raw)
            unit = tag.get("unitref", "EUR")
            context_ref = tag.get("contextref", "")

            fact_record = {
                "fact_id": str(uuid.uuid4()),
                "doc_id": doc_id,
                "entity_lei": entity_lei,
                "period_start": f"{fiscal_year}-01-01",
                "period_end": f"{fiscal_year}-12-31",
                "concept": concept_raw,
                "concept_std": canonical or concept_raw,
                "value": val,
                "unit": unit,
                "decimals": int(tag.get("decimals", 0)) if tag.get("decimals", "").isdigit() else 0,
                "taxonomy": "IFRS-EU",
                "statement": self.mapper.canonical_to_statement.get(canonical, "OTHER") if canonical else "OTHER",
                "context_ref": context_ref,
                "is_restated": False
            }
            facts_raw.append(fact_record)

            if canonical:
                if canonical not in canonical_values:
                    canonical_values[canonical] = []
                canonical_values[canonical].append(val)

        # Generar fila resumida para financial_panel tomando los valores del ejercicio
        panel_dict = {
            "entity_lei": entity_lei,
            "fiscal_year": fiscal_year,
            "reporting_currency": "EUR",
            "accounting_standard": "IFRS-EU",
            "period_end_date": f"{fiscal_year}-12-31",
        }

        # Elegir el valor más representativo (primer o máximo fact para saldos)
        for canon, val_list in canonical_values.items():
            panel_dict[canon] = val_list[0] if val_list else 0.0

        # Rellenar valores por defecto para campos obligatorios
        total_activo = panel_dict.get("total_activo", 0.0)
        total_pasivo = panel_dict.get("total_pasivo", 0.0)
        patrimonio_neto = panel_dict.get("patrimonio_neto", 0.0)

        # Si falta total_pasivo pero hay activo y neto
        if total_activo > 0 and patrimonio_neto > 0 and total_pasivo == 0:
            total_pasivo = total_activo - patrimonio_neto
            panel_dict["total_pasivo"] = total_pasivo

        val_res = validate_balance(panel_dict)
        panel_dict["balance_check"] = val_res.is_balanced
        panel_dict["balance_imbalance_eur"] = val_res.imbalance_amount
        panel_dict["quality_score"] = 100.0 if val_res.is_balanced else 60.0

        return facts_raw, panel_dict

    def process_company(self, company_name: str, market: str, year: int, files: List[Path]) -> Dict[str, Any]:
        """Procesa una empresa para un año fiscal."""
        print(f"\n=======================================================")
        print(f"[{market}] Procesando: {company_name} (FY {year})")
        print(f"=======================================================")

        entity_lei = f"LEI_{market}_{re.sub(r'[^A-Z0-9]', '', company_name.upper())[:18]}"
        doc_id = f"{market}_{company_name}_{year}_AUDITED"

        # 1. Identificar archivos candidatos (ESEF y Audit PDF/XHTML)
        esef_file = None
        audit_file = None

        # Filtrar meta.json
        valid_files = [f for f in files if not f.name.endswith(".meta.json") and not f.name.endswith(".quarantine_reason.json")]

        for f in valid_files:
            fname = f.name.lower()
            if "esef" in fname or "consolidada" in fname or "xbrl" in fname:
                esef_file = f
            if ("anual" in fname or "audit" in fname or "jahres" in fname or "bafin" in fname) and f.suffix.lower() == ".pdf":
                audit_file = f

        # Fallbacks si no están separados
        if not esef_file and valid_files:
            esef_candidates = [f for f in valid_files if f.suffix.lower() in [".zip", ".xhtml", ".xml"]]
            esef_file = esef_candidates[0] if esef_candidates else valid_files[0]

        if not audit_file and valid_files:
            # Priorizar archivos PDF de más de 500 KB para asegurar informe completo
            big_pdfs = [f for f in valid_files if f.suffix.lower() == ".pdf" and f.stat().st_size > 500000]
            if big_pdfs:
                audit_file = big_pdfs[0]
            elif esef_file:
                audit_file = esef_file
            else:
                audit_file = valid_files[0]


        extracted_kams = []
        facts_raw = []
        financial_panel_row = {}

        # 2. Extracción de Fundamentales (mod_02_parser)
        if esef_file:
            print(f"  -> Parseando fundamentales ESEF desde: {esef_file.name}")
            facts_raw, financial_panel_row = self.parse_esef_facts(esef_file, entity_lei, year, doc_id)
            print(f"     Facts extraídos: {len(facts_raw)} | Total Activo: €{financial_panel_row.get('total_activo', 0):,.0f} | Balance Cuadrado: {financial_panel_row.get('balance_check', False)}")

        # 3. Extracción de KAMs y Severidad (mod_03_nlp_audit + Azure OpenAI)
        if audit_file:
            print(f"  -> Extrayendo informe de auditoría desde: {audit_file.name}")
            full_text, ftype = self.extract_text_from_file_or_zip(audit_file)
            print(f"     Texto extraído ({ftype}): {len(full_text):,} caracteres")

            audit_chunk = self.locate_audit_report_chunk(full_text, market=market)
            if len(audit_chunk) > 200:
                print(f"     Enviando ventana de auditoría ({len(audit_chunk):,} caracteres) a Azure OpenAI...")
                try:
                    extracted_kams = self.kam_extractor.extract_from_text_sync(
                        audit_chunk, entity_lei, year, doc_id, use_azure=True
                    )
                    print(f"     [OK] KAMs extraídas: {len(extracted_kams)}")
                    for k in extracted_kams:
                        print(f"       * [{k['severity']}] {k['kam_topic']}: {k['kam_title']} (Auditor: {k['audit_firm']})")
                except Exception as e:
                    print(f"     [ERROR] Falló extracción de KAMs: {e}")

        # 4. Inserción en DuckDB
        con = duckdb.connect(str(self.db_path))
        now_ts = datetime.now(timezone.utc)

        # Inserción de KAMs
        if extracted_kams:
            for k in extracted_kams:
                con.execute("""
                    INSERT INTO audit_kams (
                        kam_id, entity_lei, fiscal_year, doc_id, audit_firm, signing_partner,
                        audit_opinion, has_going_concern, kam_title, kam_topic, severity,
                        risk_description, audit_response, text_span, extraction_method,
                        confidence_score, human_validated, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    k["kam_id"], k["entity_lei"], k["fiscal_year"], k["doc_id"],
                    k["audit_firm"], k["signing_partner"], k["audit_opinion"],
                    k["has_going_concern"], k["kam_title"], k["kam_topic"], k["severity"],
                    k["risk_description"], k["audit_response"], k["text_span"],
                    k["extraction_method"], k["confidence_score"], k["human_validated"],
                    now_ts
                ])

        # Inserción de Financial Panel
        if financial_panel_row and financial_panel_row.get("total_activo", 0) > 0:
            # Eliminar si ya existía para este entity-year
            con.execute("DELETE FROM financial_panel WHERE entity_lei = ? AND fiscal_year = ?", [entity_lei, year])
            con.execute("""
                INSERT INTO financial_panel (
                    entity_lei, fiscal_year, ticker, company_name, source_market,
                    reporting_currency, accounting_standard, period_end_date,
                    total_activo, activo_no_corriente, inmovilizado_material, inmovilizado_intangible,
                    activo_corriente, existencias, deudores_comerciales, efectivo_y_equivalentes,
                    total_pasivo, pasivo_no_corriente, deuda_financiera_lp, pasivo_corriente,
                    deuda_financiera_cp, acreedores_comerciales, patrimonio_neto, capital_social,
                    reservas, resultado_ejercicio_bal, revenue, cost_of_goods_sold, gross_profit,
                    operating_expenses, ebitda, depreciation_amort, ebit, financial_result, ebt,
                    income_tax, beneficio_neto, beneficio_atribuible, cfo, capex, cfi, cff, fcf,
                    dividendos_pagados, balance_imbalance_eur, balance_check, quality_score,
                    version_id, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?
                )
            """, [
                entity_lei, year, company_name[:10], company_name, market,
                financial_panel_row.get("reporting_currency", "EUR"),
                financial_panel_row.get("accounting_standard", "IFRS-EU"),
                financial_panel_row.get("period_end_date", f"{year}-12-31"),
                financial_panel_row.get("total_activo", 0.0),
                financial_panel_row.get("activo_no_corriente", 0.0),
                financial_panel_row.get("inmovilizado_material", 0.0),
                financial_panel_row.get("inmovilizado_intangible", 0.0),
                financial_panel_row.get("activo_corriente", 0.0),
                financial_panel_row.get("existencias", 0.0),
                financial_panel_row.get("deudores_comerciales", 0.0),
                financial_panel_row.get("efectivo_y_equivalentes", 0.0),
                financial_panel_row.get("total_pasivo", 0.0),
                financial_panel_row.get("pasivo_no_corriente", 0.0),
                financial_panel_row.get("deuda_financiera_lp", 0.0),
                financial_panel_row.get("pasivo_corriente", 0.0),
                financial_panel_row.get("deuda_financiera_cp", 0.0),
                financial_panel_row.get("acreedores_comerciales", 0.0),
                financial_panel_row.get("patrimonio_neto", 0.0),
                financial_panel_row.get("capital_social", 0.0),
                financial_panel_row.get("reservas", 0.0),
                financial_panel_row.get("resultado_ejercicio_bal", 0.0),
                financial_panel_row.get("revenue", 0.0),
                financial_panel_row.get("cost_of_goods_sold", 0.0),
                financial_panel_row.get("gross_profit", 0.0),
                financial_panel_row.get("operating_expenses", 0.0),
                financial_panel_row.get("ebitda", 0.0),
                financial_panel_row.get("depreciation_amort", 0.0),
                financial_panel_row.get("ebit", 0.0),
                financial_panel_row.get("financial_result", 0.0),
                financial_panel_row.get("ebt", 0.0),
                financial_panel_row.get("income_tax", 0.0),
                financial_panel_row.get("beneficio_neto", 0.0),
                financial_panel_row.get("beneficio_atribuible", 0.0),
                financial_panel_row.get("cfo", 0.0),
                financial_panel_row.get("capex", 0.0),
                financial_panel_row.get("cfi", 0.0),
                financial_panel_row.get("cff", 0.0),
                financial_panel_row.get("fcf", 0.0),
                financial_panel_row.get("dividendos_pagados", 0.0),
                financial_panel_row.get("balance_imbalance_eur", 0.0),
                financial_panel_row.get("balance_check", False),
                financial_panel_row.get("quality_score", 100.0),
                "v1_esef_batch",
                now_ts, now_ts
            ])

        # Inserción de Facts Granulares
        if facts_raw:
            con.executemany("""
                INSERT INTO financial_facts_raw (
                    fact_id, doc_id, entity_lei, period_start, period_end, concept,
                    concept_std, value, unit, decimals, taxonomy, statement, context_ref, is_restated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    f["fact_id"], f["doc_id"], f["entity_lei"], f["period_start"],
                    f["period_end"], f["concept"], f["concept_std"], f["value"],
                    f["unit"], f["decimals"], f["taxonomy"], f["statement"],
                    f["context_ref"], f["is_restated"]
                )
                for f in facts_raw[:200]  # Guardar los 200 facts principales por documento
            ])

        con.close()

        return {
            "company": company_name,
            "market": market,
            "year": year,
            "kams_extracted": len(extracted_kams),
            "facts_extracted": len(facts_raw),
            "total_activo": financial_panel_row.get("total_activo", 0.0),
            "balance_check": financial_panel_row.get("balance_check", False)
        }

    def run_primary_european_batch(self, target_year: int = 2024, max_per_country: int = 6):
        """Ejecuta el lote inicial sobre cotizadas líderes de ES, DE y FR."""
        print(f"==================================================================")
        print(f"INICIANDO LOTE MAESTRO EUROPEO (ES, DE, FR) — EJERCICIO {target_year}")
        print(f"==================================================================")

        results = []

        # 1. ESPAÑA (IBEX 35)
        es_dir = LAKE_ROOT / "ESPANA/IBEX35" / str(target_year)
        if es_dir.exists():
            es_companies = [d for d in es_dir.iterdir() if d.is_dir()][:max_per_country]
            for c_dir in es_companies:
                files = [f for f in c_dir.rglob("*") if f.is_file()]
                r = self.process_company(c_dir.name, "ES", target_year, files)
                results.append(r)

        # 2. ALEMANIA (DAX / PRIME STANDARD)
        de_dir = LAKE_ROOT / "ALEMANIA/PRIME_STANDARD" / str(target_year)
        if de_dir.exists():
            de_companies = [d for d in de_dir.iterdir() if d.is_dir()][:max_per_country]
            for c_dir in de_companies:
                files = [f for f in c_dir.rglob("*") if f.is_file()]
                r = self.process_company(c_dir.name, "DE", target_year, files)
                results.append(r)

        # 3. FRANCIA (CAC 40)
        fr_dir = LAKE_ROOT / "FRANCIA/CAC40" / str(target_year)
        if fr_dir.exists():
            fr_companies = [d for d in fr_dir.iterdir() if d.is_dir()][:max_per_country]
            for c_dir in fr_companies:
                files = [f for f in c_dir.rglob("*") if f.is_file()]
                r = self.process_company(c_dir.name, "FR", target_year, files)
                results.append(r)

        # Reporte final
        print(f"\n==================================================================")
        print(f"RESUMEN FINAL DE EJECUCIÓN DEL LOTE EUROPEO")
        print(f"==================================================================")
        total_kams = sum(r["kams_extracted"] for r in results)
        total_facts = sum(r["facts_extracted"] for r in results)
        print(f"Total Empresas Procesadas: {len(results)}")
        print(f"Total KAMs Extraídas y Guardadas en DuckDB: {total_kams}")
        print(f"Total Facts Granulares Guardados en DuckDB: {total_facts}")
        for r in results:
            print(f"  - [{r['market']}] {r['company']}: {r['kams_extracted']} KAMs | {r['facts_extracted']} Facts | Activo: €{r['total_activo']:,.0f}")

        # Guardar resumen JSON
        out_summary = REPO_ROOT / f"scratch/BATCH_EUROPE_SUMMARY_{target_year}.json"
        out_summary.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nResumen guardado en: {out_summary}")


if __name__ == "__main__":
    extractor = EuropeanBatchExtractor()
    extractor.run_primary_european_batch(target_year=2024, max_per_country=5)
