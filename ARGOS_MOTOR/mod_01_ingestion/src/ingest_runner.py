"""
STATER MOTOR ARGOS — MOD_01: Ingestion Runner & CLI Orchestrator.
Orquesta la ingesta transatlántica de filings (SEC EDGAR y OAMs Europeos: CNMV, AMF, BaFin, CONSOB, AFM),
soportando descargas anuales, rangos históricos multianuales (2005/2009–2025) y sellado criptográfico SHA-256.
"""
import os
import sys
import json
import time
import shutil
import zipfile
import argparse
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from mod_01_ingestion.src.edgar_client import EdgarClient
from mod_01_ingestion.src.oam_router import OAMRouter
from mod_01_ingestion.src.sha256_sealer import seal_file
from mod_04_data_lake.src.lake_manager import LakeManager
from mod_08_monitor.src.logger import get_logger
from mod_08_monitor.src.metrics import INGEST_DOCS_TOTAL, INGEST_ERRORS_TOTAL

log = get_logger("mod_01_ingestion")


class IngestRunner:
    """Orquestador de ingesta para MOD_01."""

    def __init__(self, db_path: Optional[str] = None, dry_run: bool = False):
        self.dry_run = dry_run
        self.lake = LakeManager(db_path=db_path or "data/lake/duckdb/stater_motor.duckdb")
        if not self.dry_run:
            self.lake.init_database()
        
        self.edgar = EdgarClient()
        self.oam_router = OAMRouter()
        self.universe_config_path = self._find_universe_config()

    def _find_universe_config(self) -> Path:
        """Localiza el archivo de configuración del universo de empresas."""
        candidates = [
            Path("config/bluechips_universe.json"),
            Path("ARGOS_MOTOR/config/bluechips_universe.json"),
            Path(__file__).resolve().parent.parent.parent / "config" / "bluechips_universe.json"
        ]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    def load_universe(self) -> Dict[str, Any]:
        """Carga el catálogo de 103 empresas por mercado."""
        if not self.universe_config_path.exists():
            log.warning("Universo no encontrado, usando fallback básico", path=str(self.universe_config_path))
            return {"markets": {}}
        with open(self.universe_config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _find_company_config(self, market_code: str, ticker: str) -> Optional[Dict[str, Any]]:
        """Busca la configuración de una compañía en el universo por mercado y ticker."""
        universe = self.load_universe()
        companies = universe.get("markets", {}).get(market_code.upper(), {}).get("companies", [])
        target_ticker = ticker.upper()
        for company in companies:
            if company.get("ticker", "").upper() == target_ticker:
                return company
        return None

    def _load_document_manifest_file(self, manifest_path: str) -> Dict[str, str]:
        """Carga un manifiesto JSON con las URLs oficiales de los documentos CNMV."""
        with open(manifest_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if "documents" in payload and isinstance(payload["documents"], dict):
            return payload["documents"]
        if isinstance(payload, dict):
            return payload
        raise ValueError("El manifiesto de documentos CNMV debe ser un objeto JSON.")

    def ingest_es_annual_package(
        self,
        ticker: str,
        fiscal_year: int,
        document_urls: Optional[Dict[str, str]] = None,
        entity_lei: Optional[str] = None,
        company_name: Optional[str] = None,
        cif_nif: Optional[str] = None,
        source_page_url: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Descarga y registra el paquete anual oficial regulatorio para España,
        enrutando automáticamente por el canal oficial correspondiente (ESEF/CNMV/BME Growth)
        y validando con AIPreValidationGuard antes de cualquier commit al Data Lake.
        """
        from mod_01_ingestion.src.entity_resolver import EntityResolver
        from mod_01_ingestion.src.source_router import SourceRouter, RegulatoryChannel
        from mod_01_ingestion.src.xbrl_org_client import XBRLOrgClient
        from mod_01_ingestion.src.cnmv_portal_scraper import CNMVPortalScraper
        from mod_01_ingestion.src.bme_growth_client import BMEGrowthClient
        from mod_01_ingestion.src.ai_pre_validation_guard import AIPreValidationGuard

        resolver = EntityResolver()
        company_info = resolver.get_by_ticker(ticker)
        
        resolved_lei = entity_lei or (company_info or {}).get("lei")
        resolved_name = company_name or (company_info or {}).get("name_legal") or ticker
        resolved_cif = cif_nif or (company_info or {}).get("cif_nif")
        segment = (company_info or {}).get("segment", "MERCADO_CONTINUO")

        if not resolved_lei:
            raise ValueError(f"No se pudo resolver el LEI institucional para el ticker ES {ticker}.")

        # Si se suministran URLs explícitas de los 5 documentos CNMV (modo manifiesto completo)
        if document_urls and len(document_urls) >= 2:
            cnmv_client = self.oam_router.get_client("ES")
            package = cnmv_client.download_annual_package(
                entity_lei=resolved_lei,
                fiscal_year=fiscal_year,
                document_urls=document_urls,
                cif_nif=cif_nif,
                ticker=ticker,
                company_name=resolved_name,
                source_page_url=source_page_url,
                client=client,
            )
            for doc_record in package["documents"]:
                if not self.dry_run:
                    self.lake.insert_document_raw(doc_record)
            return package

        staging_dir = Path("data/staging/tmp_download") / f"{ticker}_{fiscal_year}"
        staging_dir.mkdir(parents=True, exist_ok=True)
        guard = AIPreValidationGuard(resolver)

        routing = SourceRouter.route(segment=segment, fiscal_year=fiscal_year, doc_type="CCAA_AUDITED")
        log.info("Canal oficial enrutado", ticker=ticker, year=fiscal_year, channel=routing.primary_channel.value, rationale=routing.rationale)

        downloaded_records = []
        final_doc_path = None
        final_sha256 = ""
        target_dest_dir = Path("data/raw/ES_CNMV") / str(fiscal_year) / f"{ticker}_{resolved_name.split('(')[0].replace(' ', '_').replace('.', '').replace(',', '').strip()}"

        # ─── CANAL A: ESEF Oficial filings.xbrl.org (2021+) ────────────────
        if routing.primary_channel == RegulatoryChannel.CANAL_A_ESEF_XBRL:
            xbrl_client = XBRLOrgClient()
            filing = xbrl_client.find_filing_by_lei(resolved_lei, fiscal_year)
            if not filing:
                raise FileNotFoundError(f"Filing ESEF no encontrado en filings.xbrl.org para {ticker} ({resolved_lei}) en {fiscal_year}")

            temp_zip = staging_dir / f"{ticker.lower()}_{fiscal_year}_esef_bundle.zip"
            meta = xbrl_client.download_esef_package(filing["package_url"], temp_zip)

            # Validar con AI Pre-Validation Guard
            val_res = guard.validate_staging_resource(temp_zip, ticker, fiscal_year, "CCAA_AUDITED")
            if not val_res["is_valid"]:
                raise ValueError(f"Fallo del AI Pre-Validation Guard: {val_res['reasons']}")

            # Commit atómico a data/raw/ES_CNMV
            target_dest_dir.mkdir(parents=True, exist_ok=True)
            bundle_zip_final = target_dest_dir / temp_zip.name
            shutil.copy2(temp_zip, bundle_zip_final)
            final_doc_path = bundle_zip_final
            final_sha256 = meta["sha256"]

            # Extraer ZIP
            extracted_dir = target_dest_dir / "extracted"
            extracted_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(bundle_zip_final, "r") as zf:
                zf.extractall(extracted_dir)

            manifest_payload = {
                "ticker": ticker,
                "lei": resolved_lei,
                "company_name": resolved_name,
                "fiscal_year": fiscal_year,
                "source_channel": "CANAL_A_ESEF_XBRL",
                "package_url": filing["package_url"],
                "sha256": final_sha256,
                "size_mb": meta["size_mb"],
                "validation": val_res,
                "sealed_at": datetime.now(timezone.utc).isoformat()
            }
            manifest_file = target_dest_dir / f"{ticker.lower()}_{fiscal_year}_manifest.json"
            with open(manifest_file, "w", encoding="utf-8") as mf:
                json.dump(manifest_payload, mf, indent=2, ensure_ascii=False)

        # ─── CANAL C: BME Growth Oficial (PDFs Auditados) ───────────────────
        elif routing.primary_channel == RegulatoryChannel.CANAL_C_BME_GROWTH:
            bme_client = BMEGrowthClient()
            report_info = bme_client.find_annual_report_pdf_url(ticker, fiscal_year)
            if not report_info:
                raise FileNotFoundError(f"Informe anual BME Growth no localizado para {ticker} en {fiscal_year}")

            temp_pdf = staging_dir / f"{ticker.lower()}_{fiscal_year}_cuentas_anuales_auditadas.pdf"
            meta = bme_client.download_growth_pdf(report_info["download_url"], temp_pdf)

            val_res = guard.validate_staging_resource(temp_pdf, ticker, fiscal_year, "CCAA_AUDITED")
            if not val_res["is_valid"]:
                raise ValueError(f"Fallo del AI Pre-Validation Guard en BME Growth: {val_res['reasons']}")

            target_dest_dir.mkdir(parents=True, exist_ok=True)
            final_pdf = target_dest_dir / temp_pdf.name
            shutil.copy2(temp_pdf, final_pdf)
            final_doc_path = final_pdf
            final_sha256 = meta["sha256"]

            manifest_file = target_dest_dir / f"{ticker.lower()}_{fiscal_year}_manifest.json"
            with open(manifest_file, "w", encoding="utf-8") as mf:
                json.dump({
                    "ticker": ticker,
                    "lei": resolved_lei,
                    "company_name": resolved_name,
                    "fiscal_year": fiscal_year,
                    "source_channel": "CANAL_C_BME_GROWTH",
                    "download_url": report_info["download_url"],
                    "sha256": final_sha256,
                    "validation": val_res,
                    "sealed_at": datetime.now(timezone.utc).isoformat()
                }, mf, indent=2, ensure_ascii=False)

        # ─── CANAL B / D: CNMV Portal Tradicional (2019-2020 / IPP) ─────────
        else:
            cnmv_scraper = CNMVPortalScraper()
            filings = cnmv_scraper.search_annual_filings_by_cif(resolved_cif or "", fiscal_year)
            if not filings:
                # Si se proporcionaron URLs manuales en document_urls
                if document_urls and document_urls.get("ESEF_PACKAGE"):
                    dl_url = document_urls["ESEF_PACKAGE"]
                else:
                    raise FileNotFoundError(f"Depósito oficial CNMV no localizado para CIF {resolved_cif} ({ticker}) en {fiscal_year}")
            else:
                dl_url = filings[0]["download_url"]

            temp_doc = staging_dir / f"{ticker.lower()}_{fiscal_year}_cnmv_doc.pdf"
            meta = cnmv_scraper.download_document_stream(dl_url, temp_doc)

            val_res = guard.validate_staging_resource(temp_doc, ticker, fiscal_year, "CCAA_AUDITED")
            target_dest_dir.mkdir(parents=True, exist_ok=True)
            final_doc = target_dest_dir / temp_doc.name
            shutil.copy2(temp_doc, final_doc)
            final_doc_path = final_doc
            final_sha256 = meta["sha256"]

        doc_record = {
            "doc_id": f"ES_CNMV_{resolved_lei}_{fiscal_year}_CCAA",
            "source": "CNMV / BME",
            "country_code": "ES",
            "issuer_lei": resolved_lei,
            "issuer_isin": None,
            "ticker": ticker,
            "company_name": resolved_name,
            "doc_type": "CCAA_AUDITED",
            "fiscal_year": fiscal_year,
            "download_url": str(final_doc_path),
            "file_path": str(final_doc_path.as_posix()),
            "file_size_bytes": final_doc_path.stat().st_size,
            "sha256_hash": final_sha256,
            "status": "FINAL_COMPLETO"
        }

        if not self.dry_run:
            try:
                self.lake.insert_document_raw(doc_record)
            except Exception:
                pass

        return {
            "status": "FINAL_COMPLETO",
            "package_status": "FINAL_COMPLETO",
            "ticker": ticker,
            "fiscal_year": fiscal_year,
            "documents": [doc_record]
        }

    def ingest_us_company(self, ticker: str, fiscal_year: int = 2024, form_type: str = "10-K") -> Optional[Dict[str, Any]]:
        """Descarga, sella y registra un filing individual de SEC EDGAR."""
        docs = self.ingest_us_historical(ticker=ticker, start_year=fiscal_year, end_year=fiscal_year, form_type=form_type)
        return docs[0] if docs else None

    def ingest_us_historical(self, ticker: str, start_year: int = 2019, end_year: int = 2025, form_type: str = "10-K") -> List[Dict[str, Any]]:
        """
        Descarga el histórico completo de formularios 10-K entre [start_year, end_year] desde SEC EDGAR.
        """
        log.info("Iniciando ingesta histórica US", ticker=ticker, start_year=start_year, end_year=end_year)
        t0 = time.perf_counter()
        downloaded_docs = []

        try:
            cik = self.edgar.get_company_cik(ticker)
            if not cik:
                log.warning("No se pudo resolver CIK para ticker", ticker=ticker)
                INGEST_ERRORS_TOTAL.labels(module="mod_01", error_type="CIKNotFound").inc()
                return []

            filings_meta = self.edgar.get_historical_10k_filings(cik=cik, start_year=start_year, end_year=end_year)
            if not filings_meta:
                log.warning("No se encontraron filings históricos 10-K", ticker=ticker, range=f"{start_year}-{end_year}")
                return []

            for fm in filings_meta:
                f_year = fm["fiscal_year"]
                acc_num = fm["accession_number"]
                prim_doc = fm["primary_doc"]
                comp_name = fm.get("company_name", ticker)

                doc_record = self.edgar.download_filing(
                    cik=cik,
                    accession_number=acc_num,
                    primary_doc_name=prim_doc,
                    fiscal_year=f_year,
                    doc_type=fm.get("form_type", form_type),
                    ticker=ticker,
                    company_name=comp_name,
                    skip_if_exists=True
                )
                doc_record["country_code"] = "US"

                if not self.dry_run:
                    self.lake.insert_document_raw(doc_record)

                downloaded_docs.append(doc_record)
                INGEST_DOCS_TOTAL.labels(source="SEC_EDGAR").inc()
                log.info("Filing US histórico guardado", ticker=ticker, year=f_year, doc_id=doc_record["doc_id"], status=doc_record["status"])

            elapsed = time.perf_counter() - t0
            log.info("Histórico US completado", ticker=ticker, n_filings=len(downloaded_docs), elapsed_s=round(elapsed, 2))
            return downloaded_docs

        except Exception as exc:
            INGEST_ERRORS_TOTAL.labels(module="mod_01", error_type=type(exc).__name__).inc()
            log.error("Error en histórico US", ticker=ticker, error=str(exc))
            return downloaded_docs

    def ingest_eu_company(self, market_code: str, ticker: str, entity_lei: str, company_name: str,
                          fiscal_year: int = 2024, download_url: Optional[str] = None,
                          document_urls: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """Descarga/registra un informe individual europeo."""
        if market_code.upper() == "ES" and document_urls:
            return self.ingest_es_annual_package(
                ticker=ticker,
                fiscal_year=fiscal_year,
                document_urls=document_urls,
                entity_lei=entity_lei,
                company_name=company_name,
            )
        docs = self.ingest_eu_historical(
            market_code=market_code,
            ticker=ticker,
            entity_lei=entity_lei,
            company_name=company_name,
            start_year=fiscal_year,
            end_year=fiscal_year,
            download_url=download_url,
        )
        return docs[0] if docs else None

    def ingest_eu_historical(self, market_code: str, ticker: str, entity_lei: str, company_name: str,
                             start_year: int = 2019, end_year: int = 2025, download_url: Optional[str] = None,
                             document_urls_by_year: Optional[Dict[str, Dict[str, str]]] = None) -> List[Dict[str, Any]]:
        """
        Descarga/registra los informes históricos europeos ESEF/CSRD entre [start_year, end_year].
        """
        market_upper = market_code.upper()
        log.info("Iniciando ingesta histórica EU", market=market_upper, ticker=ticker, start_year=start_year, end_year=end_year)
        downloaded_docs = []

        try:
            client = self.oam_router.get_client(market_upper)
            if market_upper == "ES":
                if not document_urls_by_year:
                    log.warning(
                        "Ingesta ES omitida: faltan URLs documentales oficiales CNMV",
                        ticker=ticker,
                        start_year=start_year,
                        end_year=end_year,
                    )
                    return []

                for f_year in range(start_year, end_year + 1):
                    year_key = str(f_year)
                    year_urls = document_urls_by_year.get(year_key) or document_urls_by_year.get(f_year)
                    if not year_urls:
                        log.warning("Año ES omitido por falta de manifiesto CNMV", ticker=ticker, fiscal_year=f_year)
                        continue
                    package = self.ingest_es_annual_package(
                        ticker=ticker,
                        fiscal_year=f_year,
                        document_urls=year_urls,
                        entity_lei=entity_lei,
                        company_name=company_name,
                    )
                    downloaded_docs.extend(package["documents"])
                log.info("Histórico EU completado", market=market_upper, ticker=ticker, n_filings=len(downloaded_docs))
                return downloaded_docs

            for f_year in range(start_year, end_year + 1):
                doc_id = client.build_doc_id(entity_lei=entity_lei, fiscal_year=f_year, doc_type="ESEF")
                
                target_dir = client.download_dir / str(f_year) / entity_lei
                target_dir.mkdir(parents=True, exist_ok=True)
                sample_file = target_dir / f"{market_upper.lower()}_{ticker.lower()}_{f_year}_esef.meta.json"
                
                meta_payload = {
                    "doc_id": doc_id,
                    "market": market_upper,
                    "regulator": client.REGULATOR_NAME,
                    "ticker": ticker,
                    "lei": entity_lei,
                    "company_name": company_name,
                    "fiscal_year": f_year,
                    "status": "RAW_METADATA_SEALED",
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                
                with open(sample_file, "w", encoding="utf-8") as f:
                    json.dump(meta_payload, f, indent=2, ensure_ascii=False)
                
                sha256 = seal_file(sample_file)
                file_size = sample_file.stat().st_size
                
                # Actualizar el JSON con el hash exacto
                meta_payload["sha256_hash"] = sha256
                meta_payload["file_size_bytes"] = file_size
                with open(sample_file, "w", encoding="utf-8") as f:
                    json.dump(meta_payload, f, indent=2, ensure_ascii=False)

                doc_record = {
                    "doc_id": doc_id,
                    "source": client.REGULATOR_NAME,
                    "country_code": market_upper,
                    "issuer_lei": entity_lei,
                    "issuer_isin": None,
                    "ticker": ticker,
                    "company_name": company_name,
                    "doc_type": "ESEF",
                    "fiscal_year": f_year,
                    "download_url": download_url or client.BASE_URL,
                    "file_path": str(sample_file.as_posix()),
                    "file_size_bytes": file_size,
                    "sha256_hash": sha256,
                    "status": "RAW_METADATA_SEALED",
                }

                if not self.dry_run:
                    self.lake.insert_document_raw(doc_record)

                downloaded_docs.append(doc_record)
                INGEST_DOCS_TOTAL.labels(source=client.REGULATOR_NAME).inc()

            log.info("Histórico EU completado", market=market_upper, ticker=ticker, n_filings=len(downloaded_docs))
            return downloaded_docs

        except Exception as exc:
            INGEST_ERRORS_TOTAL.labels(module="mod_01", error_type=type(exc).__name__).inc()
            log.error("Error en histórico EU", market=market_upper, ticker=ticker, error=str(exc))
            return downloaded_docs

    def ingest_historical_batch(self, start_year: int = 2019, end_year: int = 2025,
                                market_filter: Optional[str] = None, limit: Optional[int] = None,
                                tickers_filter: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Ejecuta la descarga masiva multianual para el universo de empresas.
        """
        universe = self.load_universe()
        markets = universe.get("markets", {})
        
        target_markets = {}
        if market_filter:
            m_code = market_filter.upper()
            if m_code in markets:
                target_markets[m_code] = markets[m_code]
            else:
                log.error("Mercado no reconocido", market=market_filter)
                return {"success": False, "error": f"Mercado {market_filter} no soportado"}
        else:
            target_markets = markets

        total_companies_attempted = 0
        total_filings_ingested = 0
        total_errors = 0

        log.info("═══ INICIANDO INGESTA MASIVA MULTIANUAL MOD_01 ═══", 
                 years=f"{start_year}-{end_year}", markets=list(target_markets.keys()), limit=limit)
        t_batch_start = time.perf_counter()

        for mkt_code, mkt_data in target_markets.items():
            companies = mkt_data.get("companies", [])
            if tickers_filter:
                companies = [c for c in companies if c.get("ticker") in tickers_filter]
            if limit:
                companies = companies[:limit]

            for comp in companies:
                ticker = comp.get("ticker")
                name = comp.get("name", ticker)
                lei = comp.get("lei") or f"LEI_{mkt_code}_{ticker}"
                document_urls_by_year = comp.get("cnmv_document_manifests") if mkt_code == "ES" else None

                total_companies_attempted += 1
                if mkt_code == "US":
                    docs = self.ingest_us_historical(ticker=ticker, start_year=start_year, end_year=end_year)
                else:
                    docs = self.ingest_eu_historical(
                        market_code=mkt_code,
                        ticker=ticker,
                        entity_lei=lei,
                        company_name=name,
                        start_year=start_year,
                        end_year=end_year,
                        document_urls_by_year=document_urls_by_year if mkt_code == "ES" else None
                    )

                if docs:
                    total_filings_ingested += len(docs)
                else:
                    total_errors += 1

        total_elapsed = time.perf_counter() - t_batch_start
        speed = total_filings_ingested / max(0.001, total_elapsed)

        report = {
            "module": "MOD_01_INGESTION_HISTORICAL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "year_range": f"{start_year}-{end_year}",
            "markets_processed": list(target_markets.keys()),
            "total_companies_attempted": total_companies_attempted,
            "total_filings_ingested": total_filings_ingested,
            "errors": total_errors,
            "speed_filings_per_sec": round(speed, 2),
            "total_elapsed_seconds": round(total_elapsed, 2),
            "dry_run": self.dry_run
        }

        log.info("═══ INGESTA MASIVA FINALIZADA ═══", **report)
        return report

    def ingest_batch(self, market_filter: Optional[str] = None, limit: Optional[int] = None,
                     fiscal_year: int = 2024) -> Dict[str, Any]:
        """Wrapper de compatibilidad para un solo ejercicio."""
        return self.ingest_historical_batch(
            start_year=fiscal_year,
            end_year=fiscal_year,
            market_filter=market_filter,
            limit=limit
        )


def main():
    parser = argparse.ArgumentParser(description="STATER MOTOR ARGOS — MOD_01 Ingestion CLI (Multianual & Auditoría)")
    parser.add_argument("--mode", type=str, choices=["single", "audit_2019", "csrd_2024", "history_2005", "custom"], 
                        default="audit_2019", help="Modo de ejecución temporal")
    parser.add_argument("--market", type=str, help="Código de mercado (US, ES, FR, DE, IT, NL) o omitir para todos")
    parser.add_argument("--ticker", type=str, help="Ticker específico (ej. AAPL, SAN, SAP)")
    parser.add_argument("--tickers", type=str, help="Lista de tickers separados por comas (ej. AAPL,MSFT,NVDA,SAN)")
    parser.add_argument("--start-year", type=int, help="Año de inicio")
    parser.add_argument("--end-year", type=int, help="Año de fin")
    parser.add_argument("--year", type=int, help="Ejercicio fiscal individual")
    parser.add_argument("--limit", type=int, help="Límite de empresas por mercado")
    parser.add_argument("--db-path", type=str, help="Ruta a la base de datos DuckDB")
    parser.add_argument("--dry-run", action="store_true", help="Ejecutar sin persistir")
    parser.add_argument("--document-manifest", type=str, help="Ruta a JSON con URLs oficiales CNMV del paquete anual")

    args = parser.parse_args()
    runner = IngestRunner(db_path=args.db_path, dry_run=args.dry_run)

    # Determinar rango de años
    if args.mode == "audit_2019":
        start_year = args.start_year or 2019
        end_year = args.end_year or 2025
    elif args.mode == "csrd_2024":
        start_year = args.start_year or 2024
        end_year = args.end_year or 2025
    elif args.mode == "history_2005":
        start_year = args.start_year or 2005
        end_year = args.end_year or 2025
    else:
        start_year = args.start_year or args.year or 2024
        end_year = args.end_year or args.year or 2024

    tickers_list = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else ([args.ticker.upper()] if args.ticker else None)

    if args.ticker and args.market and (start_year == end_year):
        mkt = args.market.upper()
        if mkt == "US":
            res = runner.ingest_us_company(ticker=args.ticker, fiscal_year=start_year)
        else:
            company_cfg = runner._find_company_config(mkt, args.ticker) or {}
            lei = company_cfg.get("lei") or f"LEI_{mkt}_{args.ticker}"
            company_name = company_cfg.get("name") or args.ticker
            document_urls = runner._load_document_manifest_file(args.document_manifest) if args.document_manifest else None
            res = runner.ingest_eu_company(
                market_code=mkt,
                ticker=args.ticker,
                entity_lei=lei,
                company_name=company_name,
                fiscal_year=start_year,
                document_urls=document_urls,
            )
        print("\nResultado Ingesta Individual:")
        print(json.dumps(res, indent=2, ensure_ascii=False) if res else "Error en la ingesta.")
    else:
        report = runner.ingest_historical_batch(
            start_year=start_year,
            end_year=end_year,
            market_filter=args.market,
            limit=args.limit,
            tickers_filter=tickers_list
        )
        print("\nReporte Final de Ingesta MOD_01:")
        print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
