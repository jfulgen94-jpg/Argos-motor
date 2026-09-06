"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Auditor Forense Retroactivo del Data Lake (Forensic Dataset Auditor).

Inspecciona de forma exhaustiva y en modo de SOLO LECTURA toda la jerarquía
de data/raw/ES_CNMV/ (y data/raw/landing_raw/) para certificar y catalogar cada
archivo existente según la taxonomía forense institucional cerrada.

Taxonomía Cerrada:
- VALID_ORIGINAL_SEALED
- VALID_COMPARATIVE_DECLARED
- WRONG_ENTITY_MISMATCH_WITH_FOLDER
- WRONG_YEAR_UNDECLARED_SUBSTITUTION
- SYNTHETIC_FABRICATED
- EMPTY_SKELETON_OR_VIEWER
- TRUNCATED_OR_CORRUPT_ZIP
- UNSEALED_OR_TAMPERED
- DUPLICATE_CONFLICTING_HASH
- UNRESOLVED_REQUIRES_MANUAL_REVIEW
"""

import sys
import os
import json
import hashlib
import re
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mod_01_ingestion.src.entity_resolver import EntityResolver, compute_comprehensive_similarity, normalize_cif
from mod_01_ingestion.src.ai_pre_validation_guard import AIPreValidationGuard, SYNTHETIC_SIGNATURES
from mod_01_ingestion.src.document_completeness_validator import DocumentCompletenessValidator


def calc_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1048576):
            sha.update(chunk)
    return sha.hexdigest()


class ForensicDatasetAuditor:
    """Auditor Forense de Solo Lectura para el Data Lake existente."""

    def __init__(self, base_dir: Path = Path("data/raw/ES_CNMV")):
        self.base_dir = base_dir
        self.resolver = EntityResolver()
        self.guard = AIPreValidationGuard(self.resolver)
        self.completeness_validator = DocumentCompletenessValidator()

    def run_full_audit(self, output_dir: Optional[Path] = None) -> Dict[str, Any]:
        """Ejecuta la auditoría completa sobre la estructura en disco."""
        target_out = output_dir or self.base_dir
        target_out.mkdir(parents=True, exist_ok=True)

        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        json_report_path = target_out / f"FORENSIC_AUDIT_REPORT_{timestamp_str}.json"
        summary_md_path = target_out / f"FORENSIC_AUDIT_SUMMARY_{timestamp_str}.md"
        summary_latest_path = target_out / "FORENSIC_AUDIT_SUMMARY.md"

        print("=" * 80)
        print("🔍 INICIANDO AUDITORÍA FORENSE RETROACTIVA DEL DATA LAKE (SOLO LECTURA)")
        print(f"Directorio Base: {self.base_dir}")
        print("=" * 80)

        records: List[Dict[str, Any]] = []
        counts_by_taxonomy: Dict[str, int] = defaultdict(int)
        counts_by_year: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        files_by_hash: Dict[str, List[Path]] = defaultdict(list)

        # 1. Recorrer archivos de filings primarios (.zip, .pdf, .xhtml, .html) excluyendo directorios internos 'extracted'
        valid_extensions = {".zip", ".pdf", ".xhtml", ".html", ".htm"}
        all_files = [
            p for p in self.base_dir.rglob("*.*") 
            if p.is_file() and p.suffix.lower() in valid_extensions and "extracted" not in p.parts
        ]
        print(f"Total de documentos primarios detectados para auditoría: {len(all_files)}", flush=True)

        for idx, file_path in enumerate(all_files, 1):
            record = self._audit_single_file(file_path)
            records.append(record)

            tax = record["taxonomy"]
            year_str = str(record["folder_year"] or "UNKNOWN")
            counts_by_taxonomy[tax] += 1
            counts_by_year[year_str][tax] += 1
            files_by_hash[record["actual_sha256"]].append(file_path)

            if idx % 20 == 0 or idx == len(all_files):
                print(f"  [{idx}/{len(all_files)}] Auditados... Último: {file_path.name[:35]} -> {tax}", flush=True)

        # Detectar duplicados con hash conflictivo
        for rec in records:
            same_hash_files = files_by_hash.get(rec["actual_sha256"], [])
            if len(same_hash_files) > 1:
                # Si el mismo archivo con mismo hash aparece bajo carpetas de empresas distintas
                distinct_tickers = {self._parse_folder_info(p)[0] for p in same_hash_files}
                if len(distinct_tickers) > 1 and rec["taxonomy"] == "VALID_ORIGINAL_SEALED":
                    rec["taxonomy"] = "DUPLICATE_CONFLICTING_HASH"
                    rec["reasons"].append(f"Mismo Hash SHA-256 duplicado en tickers conflictivos: {distinct_tickers}")
                    counts_by_taxonomy["DUPLICATE_CONFLICTING_HASH"] += 1
                    counts_by_taxonomy["VALID_ORIGINAL_SEALED"] -= 1

        # 2. Generar Reporte JSON
        full_report = {
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "base_directory": str(self.base_dir),
            "total_files_audited": len(records),
            "summary_by_taxonomy": dict(counts_by_taxonomy),
            "summary_by_year": {k: dict(v) for k, v in counts_by_year.items()},
            "records": records
        }

        with open(json_report_path, "w", encoding="utf-8") as f:
            json.dump(full_report, f, indent=2, ensure_ascii=False)

        # 3. Generar Resumen Markdown
        summary_md = self._generate_markdown_summary(full_report)
        with open(summary_md_path, "w", encoding="utf-8") as f:
            f.write(summary_md)
        with open(summary_latest_path, "w", encoding="utf-8") as f:
            f.write(summary_md)

        print("\n" + "=" * 80)
        print("✅ AUDITORÍA FORENSE COMPLETADA CON ÉXITO")
        print(f"  📄 Reporte JSON: {json_report_path}")
        print(f"  📊 Resumen MD:   {summary_md_path}")
        print("=" * 80)

        return full_report

    def _audit_single_file(self, file_path: Path) -> Dict[str, Any]:
        """Audita un único archivo contra las 6 reglas forenses."""
        folder_ticker, folder_name, folder_year = self._parse_folder_info(file_path)
        actual_sha256 = calc_sha256(file_path)
        file_size = file_path.stat().st_size
        reasons: List[str] = []

        # 1. Comprobar Manifiesto / Integridad de Sellado
        is_sealed, manifest_sha = self._check_manifest_sealing(file_path, actual_sha256)
        if not is_sealed:
            reasons.append(f"Falta manifiesto o el SHA256 calculado ({actual_sha256[:12]}...) no coincide con el registrado ({manifest_sha[:12] if manifest_sha else 'None'}).")

        # 2. Comprobar si es archivo corrupto o truncado
        if file_size < 1000:
            return self._build_record(file_path, folder_ticker, folder_name, folder_year, actual_sha256,
                                      "EMPTY_SKELETON_OR_VIEWER", ["Tamaño inferior a 1 KB."])

        # 3. Comprobar si es ZIP corrupto
        if file_path.suffix.lower() == ".zip":
            try:
                with open(file_path, "rb") as f:
                    magic = f.read(4)
                if magic != b"PK\x03\x04":
                    return self._build_record(file_path, folder_ticker, folder_name, folder_year, actual_sha256,
                                              "TRUNCATED_OR_CORRUPT_ZIP", ["Magic bytes no corresponden a un ZIP válido."])
            except Exception as e:
                return self._build_record(file_path, folder_ticker, folder_name, folder_year, actual_sha256,
                                          "TRUNCATED_OR_CORRUPT_ZIP", [f"Error leyendo ZIP: {e}"])

        # 4. Detección de Fabricación Sintética
        is_synthetic, synth_sig = self.guard._check_synthetic_fabrication(file_path)
        if is_synthetic:
            return self._build_record(file_path, folder_ticker, folder_name, folder_year, actual_sha256,
                                      "SYNTHETIC_FABRICATED", [f"Huella sintética detectada: '{synth_sig}'."])

        # 5. Extraer texto para validación de Identidad y Ejercicio
        header_text = self.guard._extract_header_text(file_path)
        detected_cif = self.guard._extract_cif_from_text(header_text)
        detected_year = self.guard._extract_fiscal_year_from_text(header_text, file_path)
        detected_name = self.guard._extract_company_name_from_text(header_text)

        # Fallback extracción de año desde nombre de archivo oficial ESEF (ej. ...-20241231-... o ...-2021-12-31-...)
        if not detected_year:
            match_yr = re.search(r'[-_](20[12][0-9])(?:1231|[-_0-9]|\.)', file_path.name)
            if match_yr:
                detected_year = int(match_yr.group(1))

        # 6. Validar Identidad contra la carpeta (por CIF y por LEI oficial en filename)
        expected_entity = self.resolver.get_by_ticker(folder_ticker) if folder_ticker else None
        if expected_entity:
            exp_cif = expected_entity.get("cif_nif", "")
            exp_name = expected_entity.get("name_legal", "")
            exp_lei = expected_entity.get("lei", "")

            # A. Comprobación por LEI en nombre de archivo
            match_lei = re.search(r'\b([A-Z0-9]{20})\b', file_path.name)
            if match_lei and exp_lei and match_lei.group(1).upper() != exp_lei.upper():
                file_lei = match_lei.group(1).upper()
                lei_owner = self.resolver.get_by_lei(file_lei)
                owner_name = lei_owner.get("name_legal") if lei_owner else f"Entidad LEI {file_lei[:8]}"
                owner_ticker = lei_owner.get("ticker") if lei_owner else None

                return self._build_record(
                    file_path, folder_ticker, folder_name, folder_year, actual_sha256,
                    "WRONG_ENTITY_MISMATCH_WITH_FOLDER",
                    [f"MISMATCH LEI: Carpeta '{folder_ticker}' ({exp_name}) contiene archivo de '{owner_name}' (LEI {file_lei})."],
                    detected_ticker=owner_ticker,
                    detected_year=detected_year,
                    detected_name=owner_name
                )

            # B. Comprobación por CIF detectado en cabecera
            if detected_cif and exp_cif and normalize_cif(detected_cif) != normalize_cif(exp_cif):
                return self._build_record(
                    file_path, folder_ticker, folder_name, folder_year, actual_sha256,
                    "WRONG_ENTITY_MISMATCH_WITH_FOLDER",
                    [f"MISMATCH CIF: Carpeta '{folder_ticker}' ({exp_name}) contiene CIF '{detected_cif}'."],
                    detected_ticker=None,
                    detected_year=detected_year,
                    detected_name=detected_name
                )

        # 7. Validar Ejercicio Fiscal
        if folder_year and detected_year and detected_year != folder_year:
            # Comprobar si tiene flag de comparativo declarado
            has_declared_prov = "COMPARATIVE_EXTRACTED" in header_text or "_comparativo" in file_path.name
            if has_declared_prov:
                return self._build_record(file_path, folder_ticker, folder_name, folder_year, actual_sha256,
                                          "VALID_COMPARATIVE_DECLARED",
                                          [f"Cifras comparativas de {detected_year} declaradas para {folder_year}."],
                                          detected_year=detected_year)
            else:
                return self._build_record(
                    file_path, folder_ticker, folder_name, folder_year, actual_sha256,
                    "WRONG_YEAR_UNDECLARED_SUBSTITUTION",
                    [f"SUSTITUCIÓN NO DECLARADA: Carpeta de {folder_year} contiene informe auditado de {detected_year}."],
                    detected_year=detected_year
                )

        # 8. Si no hay sello previo pero el contenido es íntegro
        if not is_sealed:
            return self._build_record(file_path, folder_ticker, folder_name, folder_year, actual_sha256,
                                      "UNSEALED_OR_TAMPERED", reasons, detected_year=detected_year)

        # 9. Por defecto: Válido y sellado
        return self._build_record(file_path, folder_ticker, folder_name, folder_year, actual_sha256,
                                  "VALID_ORIGINAL_SEALED", ["Documento íntegro, sellado y verificado."],
                                  detected_year=detected_year)

    def _parse_folder_info(self, path: Path) -> Tuple[Optional[str], Optional[str], Optional[int]]:
        """Extrae Ticker, Nombre y Año de la jerarquía de directorios."""
        parts = path.parts
        folder_year = None
        folder_ticker = None
        folder_name = None

        for part in parts:
            if re.match(r'^(201[9]|202[0-9])$', part):
                folder_year = int(part)
            elif "_" in part and ("SA" in part or "SE" in part or "SOCIMI" in part or len(part.split("_")[0]) <= 6):
                folder_ticker = part.split("_")[0].upper()
                folder_name = part

        return folder_ticker, folder_name, folder_year

    def _check_manifest_sealing(self, file_path: Path, actual_sha: str) -> Tuple[bool, Optional[str]]:
        """Busca el manifest.json o .meta.json asociado y comprueba el hash."""
        parent = file_path.parent
        candidates = list(parent.glob("*manifest*.json")) + list(parent.glob("*.meta.json")) + list(parent.parent.glob("*manifest*.json"))
        
        for cand in candidates:
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Buscar en campos sha256 o en lista files
                if data.get("sha256") == actual_sha:
                    return True, data.get("sha256")
                for item in data.get("files", []):
                    if item.get("sha256") == actual_sha:
                        return True, item.get("sha256")
            except Exception:
                pass

        return False, None

    def _build_record(
        self,
        file_path: Path,
        folder_ticker: Optional[str],
        folder_name: Optional[str],
        folder_year: Optional[int],
        actual_sha256: str,
        taxonomy: str,
        reasons: List[str],
        detected_ticker: Optional[str] = None,
        detected_year: Optional[int] = None,
        detected_name: Optional[str] = None
    ) -> Dict[str, Any]:
        return {
            "file_path": str(file_path.as_posix()),
            "file_name": file_path.name,
            "folder_ticker": folder_ticker,
            "folder_name": folder_name,
            "folder_year": folder_year,
            "actual_sha256": actual_sha256,
            "file_size_bytes": file_path.stat().st_size,
            "taxonomy": taxonomy,
            "detected_ticker": detected_ticker,
            "detected_year": detected_year,
            "detected_name": detected_name,
            "reasons": reasons,
            "audited_at": datetime.now(timezone.utc).isoformat()
        }

    def _generate_markdown_summary(self, report: Dict[str, Any]) -> str:
        """Genera el resumen estructurado en Markdown con tablas por año y taxonomía."""
        tax_summary = report.get("summary_by_taxonomy", {})
        year_summary = report.get("summary_by_year", {})
        total = report.get("total_files_audited", 0)

        lines = [
            "# INFORME RESUMEN DE AUDITORÍA FORENSE DEL DATA LAKE",
            f"**Fecha de Auditoría**: {report.get('audited_at')}",
            f"**Total Archivos Auditados**: {total}",
            f"**Directorio Inspeccionado**: `{report.get('base_directory')}`",
            "",
            "---",
            "",
            "## 1. DISTRIBUCIÓN POR TAXONOMÍA FORENSE",
            "",
            "| Taxonomía Forense | Total Archivos | Porcentaje | Severidad |",
            "|---|---|---|---|",
        ]

        severity_map = {
            "VALID_ORIGINAL_SEALED": "🟢 Válido",
            "VALID_COMPARATIVE_DECLARED": "🔵 Declarado",
            "WRONG_ENTITY_MISMATCH_WITH_FOLDER": "🔴 Crítico (Error Entidad)",
            "WRONG_YEAR_UNDECLARED_SUBSTITUTION": "🟠 Alto (Error Ejercicio)",
            "SYNTHETIC_FABRICATED": "🔴 Crítico (Datos Ficticios)",
            "EMPTY_SKELETON_OR_VIEWER": "🟡 Medio (Skeleton/HTML)",
            "TRUNCATED_OR_CORRUPT_ZIP": "🟡 Medio (Corrupto)",
            "UNSEALED_OR_TAMPERED": "🟡 Medio (Sin Manifiesto)",
            "DUPLICATE_CONFLICTING_HASH": "🟠 Alto (Duplicado)",
            "UNRESOLVED_REQUIRES_MANUAL_REVIEW": "⚪ Revisión Manual"
        }

        for tax, count in sorted(tax_summary.items(), key=lambda x: x[1], reverse=True):
            pct = (count / total * 100) if total > 0 else 0
            sev = severity_map.get(tax, "⚪ Info")
            lines.append(f"| `{tax}` | {count} | {pct:.1f}% | {sev} |")

        lines.extend([
            "",
            "---",
            "",
            "## 2. MATRIZ DE TAXONOMÍA POR EJERCICIO FISCAL",
            "",
            "| Ejercicio | Total Archivos | Válidos Originales | Error Entidad | Error Año | Sintéticos | Skeletons/Corruptos |",
            "|---|---|---|---|---|---|---|",
        ])

        for yr in sorted(year_summary.keys()):
            yd = year_summary[yr]
            yr_total = sum(yd.values())
            v_orig = yd.get("VALID_ORIGINAL_SEALED", 0)
            w_ent = yd.get("WRONG_ENTITY_MISMATCH_WITH_FOLDER", 0)
            w_yr = yd.get("WRONG_YEAR_UNDECLARED_SUBSTITUTION", 0)
            synth = yd.get("SYNTHETIC_FABRICATED", 0)
            skel = yd.get("EMPTY_SKELETON_OR_VIEWER", 0) + yd.get("TRUNCATED_OR_CORRUPT_ZIP", 0)
            lines.append(f"| **{yr}** | {yr_total} | {v_orig} | {w_ent} | {w_yr} | {synth} | {skel} |")

        return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auditor Forense del Data Lake STATER (Solo Lectura)")
    parser.add_argument("--scope", default="data/raw/ES_CNMV", help="Ruta de escaneo (default: data/raw/ES_CNMV)")
    args = parser.parse_args()

    auditor = ForensicDatasetAuditor(base_dir=Path(args.scope))
    auditor.run_full_audit()
