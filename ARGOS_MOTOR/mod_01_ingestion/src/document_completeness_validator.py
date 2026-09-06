"""
STATER MOTOR ARGOS — MOD_01: Forensic Document Completeness & Integrity Validator.
Performs multi-signal forensic verification on PDF, XHTML/iXBRL, and ZIP packages.
Strictly distinguishes complete audited filings from cover pages, viewer pages,
synthetic templates (fixtures), error responses, and partial resources.
"""
import re
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from mod_01_ingestion.src.models import CompletenessStatus


class DocumentCompletenessValidator:
    """Validador forense multifactorial de completitud documental."""

    # Palabras clave de estados contables indispensables
    ACCOUNTING_SECTIONS_ES = [
        re.compile(r"balance\s+(?:consolidado|de\s+situaci[oó]n)", re.IGNORECASE),
        re.compile(r"cuenta\s+de\s+(?:p[eé]rdidas\s+y\s+ganancias|resultados)", re.IGNORECASE),
        re.compile(r"estado\s+de\s+flujos\s+de\s+efectivo", re.IGNORECASE),
        re.compile(r"memoria\s+consolidada|notas\s+a\s+las\s+cuentas", re.IGNORECASE),
        re.compile(r"informe\s+de\s+auditor[ií]a|dictamen\s+de\s+auditor[ií]a", re.IGNORECASE),
    ]

    ACCOUNTING_SECTIONS_EN = [
        re.compile(r"consolidated\s+balance\s+sheets?", re.IGNORECASE),
        re.compile(r"consolidated\s+statements?\s+of\s+(?:income|operations|profit\s+and\s+loss)", re.IGNORECASE),
        re.compile(r"consolidated\s+statements?\s+of\s+cash\s+flows?", re.IGNORECASE),
        re.compile(r"notes\s+to\s+(?:consolidated\s+)?financial\s+statements?", re.IGNORECASE),
        re.compile(r"report\s+of\s+independent\s+registered\s+public\s+accounting\s+firm|auditor'?s\s+report", re.IGNORECASE),
    ]

    ERROR_PAGE_PATTERNS = [
        re.compile(r"<title>.*(error|404|not found|forbidden|403|500|exception|sesi[oó]n\s+caducada).*</title>", re.IGNORECASE),
        re.compile(r"<h1>.*(error|no encontrado|acceso denegado|internal server error).*</h1>", re.IGNORECASE),
        re.compile(r"(p[aá]gina\s+no\s+encontrada|documento\s+no\s+disponible|sesi[oó]n\s+finalizada)", re.IGNORECASE),
        re.compile(r"(request\s+rejected|access\s+denied|incident\s+id:)", re.IGNORECASE),
    ]

    VIEWER_PAGE_PATTERNS = [
        re.compile(r"iframe\s+id=[\"']pdfViewer|viewer\.html\?file=|pdfjs|pdf_viewer", re.IGNORECASE),
        re.compile(r"portal/consultas/ee/informacionfinanciera|consulta-ipr\.aspx", re.IGNORECASE),
        re.compile(r"visualizador\s+de\s+informes|visor\s+de\s+documentos", re.IGNORECASE),
    ]

    COVER_PAGE_PATTERNS = [
        re.compile(r"^(?:car[aá]tula|portada|ficha\s+de\s+publicaci[oó]n|resumen\s+de\s+registro)$", re.IGNORECASE),
        re.compile(r"documento\s+de\s+registro\s+de\s+entrada|anotaci[oó]n\s+de\s+registro", re.IGNORECASE),
    ]

    SYNTHETIC_FIXTURE_PATTERNS = [
        re.compile(r"CNMV\s+/\s+ESEF\s+iXBRL\s+OFICIAL\s+—\s+CUENTAS\s+ANUALES\s+AUDITADAS", re.IGNORECASE),
        re.compile(r"CNMV\s+OFICIAL\s+—\s+INFORME\s+DE\s+GESTI[OÓ]N\s+CONSOLIDADO", re.IGNORECASE),
        re.compile(r"CNMV\s+OFICIAL\s+—\s+INFORME\s+ANUAL\s+DE\s+GOBIERNO\s+CORPORATIVO", re.IGNORECASE),
        re.compile(r"CNMV\s+OFICIAL\s+—\s+INFORME\s+ANUAL\s+DE\s+REMUNERACIONES", re.IGNORECASE),
        re.compile(r"Estado\s+de\s+Informaci[oó]n\s+No\s+Financiera\s*/\s*CSRD\s*-", re.IGNORECASE),
        re.compile(r"ARGOS_MOTOR\s+TEST\s+FIXTURE|MOCK_SYNTHETIC", re.IGNORECASE),
        # Texto de relleno genérico ("Lorem ipsum...") usado por generadores de prueba/demo.
        # Detecta específicamente la repetición (>=3 veces), no una única aparición aislada,
        # para no penalizar un documento real que cite la expresión de forma incidental.
        re.compile(r"(?:lorem\s+ipsum\s+dolor\s+sit\s+amet[\.\s]*){3,}", re.IGNORECASE),
    ]

    EXPECTED_DOC_PATTERNS = {
        "CCAA_AUDITED": [
            re.compile(r"cuentas\s+anuales\s+consolidadas", re.IGNORECASE),
            re.compile(r"informe\s+de\s+auditor[ií]a|dictamen\s+de\s+auditor[ií]a", re.IGNORECASE),
        ],
        "INFORME_GESTION": [
            re.compile(r"informe\s+de\s+gesti[oó]n", re.IGNORECASE),
            re.compile(r"evoluci[oó]n\s+de\s+los\s+negocios", re.IGNORECASE),
        ],
        "EINF_CSRD": [
            re.compile(r"estado\s+de\s+informaci[oó]n\s+no\s+financiera", re.IGNORECASE),
            re.compile(r"\bcsrd\b|\besrs\b|sostenibilidad", re.IGNORECASE),
        ],
        "IAGC": [
            re.compile(r"informe\s+anual\s+de\s+gobierno\s+corporativo", re.IGNORECASE),
            re.compile(r"\biagc\b", re.IGNORECASE),
        ],
        "IARC": [
            re.compile(r"informe\s+anual\s+(?:sobre\s+)?remuneraciones", re.IGNORECASE),
            re.compile(r"\biarc\b", re.IGNORECASE),
        ],
    }

    AUXILIARY_DOC_TYPES = {"INFORME_GESTION", "EINF_CSRD", "IAGC", "IARC"}

    def validate_document(self, file_path: Path, expected_doc_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Analiza forensemente un archivo documental en disco y determina su estado de completitud y autenticidad.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            return {
                "completeness_status": CompletenessStatus.INVALID_FORMAT.value,
                "is_complete": False,
                "should_quarantine": True,
                "reasons": ["El archivo no existe en disco."],
                "metrics": {}
            }

        size_bytes = file_path.stat().st_size
        if size_bytes == 0:
            return {
                "completeness_status": CompletenessStatus.INVALID_FORMAT.value,
                "is_complete": False,
                "should_quarantine": True,
                "reasons": ["El archivo tiene 0 bytes (vacío)."],
                "metrics": {"file_size_bytes": 0}
            }

        # Leer bytes iniciales para identificar el formato y firma de contenido
        with open(file_path, "rb") as f:
            header_sample = f.read(4096)

        # 1. Validación de archivos ZIP
        if header_sample.startswith(b"PK\x03\x04"):
            return self._validate_zip(file_path)

        # 2. Validación de archivos PDF
        if header_sample.startswith(b"%PDF-"):
            return self._validate_pdf(file_path, expected_doc_type=expected_doc_type)

        # 3. Validación de archivos XHTML / HTML / XML
        if b"<html" in header_sample.lower() or b"<?xml" in header_sample or b"<!doctype html" in header_sample.lower():
            return self._validate_xhtml_html(file_path, expected_doc_type=expected_doc_type)

        # 4. Formato desconocido
        return {
            "completeness_status": CompletenessStatus.UNKNOWN_REQUIRES_REVIEW.value,
            "is_complete": False,
            "should_quarantine": True,
            "reasons": [f"Formato no reconocido para análisis automático ({file_path.suffix})."],
            "metrics": {"file_size_bytes": size_bytes}
        }

    def _count_expected_doc_matches(self, content: str, expected_doc_type: Optional[str]) -> int:
        """Cuenta coincidencias textuales con la tipología documental esperada."""
        if not expected_doc_type:
            return 0
        patterns = self.EXPECTED_DOC_PATTERNS.get(expected_doc_type.upper(), [])
        return sum(1 for pat in patterns if pat.search(content))

    def _validate_xhtml_html(self, file_path: Path, expected_doc_type: Optional[str] = None) -> Dict[str, Any]:
        """Valida completitud de documentos XHTML e Inline XBRL (iXBRL)."""
        reasons = []
        metrics = {}
        size_bytes = file_path.stat().st_size
        metrics["file_size_bytes"] = size_bytes

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as ex:
            return {
                "completeness_status": CompletenessStatus.INVALID_FORMAT.value,
                "is_complete": False,
                "should_quarantine": True,
                "reasons": [f"Error de lectura/decodificación: {str(ex)}"],
                "metrics": metrics
            }

        metrics["char_count"] = len(content)

        # 1. Detección de error HTTP guardado como HTML
        for pat in self.ERROR_PAGE_PATTERNS:
            m = pat.search(content)
            if m:
                return {
                    "completeness_status": CompletenessStatus.ERROR_RESPONSE.value,
                    "is_complete": False,
                    "should_quarantine": True,
                    "reasons": [f"Contenido detectado como respuesta de error del servidor: '{m.group(0)[:80]}'"],
                    "metrics": metrics
                }

        # 2. Detección de página de visualización / iframe de consulta
        for pat in self.VIEWER_PAGE_PATTERNS:
            m = pat.search(content)
            if m:
                return {
                    "completeness_status": CompletenessStatus.VIEWER_PAGE.value,
                    "is_complete": False,
                    "should_quarantine": True,
                    "reasons": [f"Página de visualización / consulta detectada: '{m.group(0)[:80]}'."],
                    "metrics": metrics
                }

        # 3. Detección de plantilla sintética (fixture local de prueba)
        for pat in self.SYNTHETIC_FIXTURE_PATTERNS:
            if pat.search(content) and size_bytes < 20_000:
                return {
                    "completeness_status": CompletenessStatus.SYNTHETIC_FIXTURE.value,
                    "is_complete": False,
                    "should_quarantine": True,
                    "reasons": ["Plantilla sintética generada por código (fixture de testing de escaso tamaño)."],
                    "metrics": metrics
                }

        # 4. Detección de carátula o ficha de registro
        for pat in self.COVER_PAGE_PATTERNS:
            if pat.search(content[:2000]):
                reasons.append("Detectado patrón de carátula o ficha de registro en el encabezado.")

        # Métricas de iXBRL
        has_ix_ns = bool(re.search(r'xmlns:ix=["\']http://www\.xbrl\.org/2013/inlineXBRL["\']', content, re.IGNORECASE))
        has_ifrs_ns = bool(re.search(r'xmlns:(?:ifrs-full|us-gaap|dei)=', content, re.IGNORECASE))
        non_fraction_facts = len(re.findall(r'<ix:nonFraction\b', content, re.IGNORECASE))
        non_numeric_facts = len(re.findall(r'<ix:nonNumeric\b', content, re.IGNORECASE))
        contexts_count = len(re.findall(r'<(?:xbrli:)?context\b', content, re.IGNORECASE))
        units_count = len(re.findall(r'<(?:xbrli:)?unit\b', content, re.IGNORECASE))
        tables_count = len(re.findall(r'<table\b', content, re.IGNORECASE))

        total_facts = non_fraction_facts + non_numeric_facts
        expected_doc_matches = self._count_expected_doc_matches(content, expected_doc_type)
        metrics.update({
            "has_ix_namespace": has_ix_ns,
            "has_taxonomy_namespace": has_ifrs_ns,
            "non_fraction_facts": non_fraction_facts,
            "non_numeric_facts": non_numeric_facts,
            "total_facts": total_facts,
            "contexts_count": contexts_count,
            "units_count": units_count,
            "tables_count": tables_count,
            "expected_doc_type_matches": expected_doc_matches,
        })

        # Búsqueda de secciones contables en texto
        found_sections = 0
        for pat in self.ACCOUNTING_SECTIONS_ES + self.ACCOUNTING_SECTIONS_EN:
            if pat.search(content):
                found_sections += 1
        metrics["accounting_sections_found"] = found_sections

        if expected_doc_type and expected_doc_type.upper() in self.AUXILIARY_DOC_TYPES and expected_doc_matches > 0:
            if size_bytes >= 20_000 or len(content) >= 10_000 or tables_count > 0 or total_facts > 0:
                return {
                    "completeness_status": CompletenessStatus.COMPLETE_CANDIDATE.value,
                    "is_complete": True,
                    "should_quarantine": False,
                    "reasons": [f"Documento {expected_doc_type} coherente con su tipología y extensión documental."],
                    "metrics": metrics
                }
            return {
                "completeness_status": CompletenessStatus.PARTIAL.value,
                "is_complete": False,
                "should_quarantine": False,
                "reasons": [f"Documento {expected_doc_type} reconocido por su tipología, pero con extensión reducida; requiere revisión manual."],
                "metrics": metrics
            }

        # Clasificación estricta por completitud
        if (total_facts >= 10 or (has_ix_ns and total_facts >= 3)) and (size_bytes > 500 or found_sections >= 1):
            if reasons:
                status = CompletenessStatus.XHTML_PARTIAL.value
                is_complete = False
                should_quarantine = False
            else:
                status = CompletenessStatus.COMPLETE_CANDIDATE.value
                is_complete = True
                should_quarantine = False
                reasons.append(f"Documento XHTML completo con {total_facts} facts XBRL, tablas contables y secciones auditadas.")
        elif total_facts == 0 and found_sections == 0 and len(content) < 10_000:
            status = CompletenessStatus.COVER_PAGE_OR_INDEX.value
            is_complete = False
            should_quarantine = True
            reasons.append("Documento HTML de escaso tamaño sin facts XBRL ni secciones contables (carátula/resumen).")
        else:
            status = CompletenessStatus.XHTML_PARTIAL.value
            is_complete = False
            should_quarantine = False
            reasons.append("Documento XHTML con contenido textual pero con facts o secciones contables insuficientes.")

        return {
            "completeness_status": status,
            "is_complete": is_complete,
            "should_quarantine": should_quarantine,
            "reasons": reasons,
            "metrics": metrics
        }

    def _validate_pdf(self, file_path: Path, expected_doc_type: Optional[str] = None) -> Dict[str, Any]:
        """Valida completitud de documentos PDF."""
        reasons = []
        metrics = {}
        size_bytes = file_path.stat().st_size
        metrics["file_size_bytes"] = size_bytes

        try:
            with open(file_path, "rb") as f:
                pdf_bytes = f.read()
        except Exception as ex:
            return {
                "completeness_status": CompletenessStatus.INVALID_FORMAT.value,
                "is_complete": False,
                "should_quarantine": True,
                "reasons": [f"Error al leer archivo PDF: {str(ex)}"],
                "metrics": metrics
            }

        # Conteo de páginas buscando objetos /Type /Page
        page_matches = len(re.findall(rb"/Type\s*/Page\b", pdf_bytes))
        metrics["estimated_pages"] = page_matches

        # Búsqueda de secciones contables en el texto
        text_sample = pdf_bytes.decode("latin-1", errors="ignore")
        found_sections = 0
        for pat in self.ACCOUNTING_SECTIONS_ES + self.ACCOUNTING_SECTIONS_EN:
            if pat.search(text_sample):
                found_sections += 1
        metrics["accounting_sections_found"] = found_sections
        expected_doc_matches = self._count_expected_doc_matches(text_sample, expected_doc_type)
        metrics["expected_doc_type_matches"] = expected_doc_matches

        # Reglas de clasificación PDF
        if page_matches == 1:
            status = CompletenessStatus.COVER_PAGE_OR_INDEX.value
            is_complete = False
            should_quarantine = True
            reasons.append("PDF de 1 sola página: identificado como carátula o justificante de registro.")
        elif expected_doc_type and expected_doc_type.upper() in self.AUXILIARY_DOC_TYPES and expected_doc_matches > 0:
            if page_matches >= 3 or size_bytes > 200_000:
                status = CompletenessStatus.COMPLETE_CANDIDATE.value
                is_complete = True
                should_quarantine = False
                reasons.append(f"PDF {expected_doc_type} multipágina coherente con su tipología ({size_bytes} bytes).")
            else:
                status = CompletenessStatus.PARTIAL.value
                is_complete = False
                should_quarantine = False
                reasons.append(f"PDF {expected_doc_type} reconocido por su tipología, pero con extensión reducida; requiere revisión manual.")
        elif page_matches >= 10 or (page_matches >= 3 and found_sections >= 2) or size_bytes > 500_000:
            status = CompletenessStatus.COMPLETE_CANDIDATE.value
            is_complete = True
            should_quarantine = False
            reasons.append(f"PDF multipágina ({page_matches} págs.) con secciones contables identificadas ({size_bytes} bytes).")
        elif page_matches > 1 and found_sections == 0:
            status = CompletenessStatus.PARTIAL.value
            is_complete = False
            should_quarantine = False
            reasons.append(f"PDF de {page_matches} págs. sin secciones contables explícitas reconocidas.")
        else:
            status = CompletenessStatus.UNKNOWN_REQUIRES_REVIEW.value
            is_complete = False
            should_quarantine = False
            reasons.append("PDF requiere revisión manual de estructura.")

        return {
            "completeness_status": status,
            "is_complete": is_complete,
            "should_quarantine": should_quarantine,
            "reasons": reasons,
            "metrics": metrics
        }

    def _validate_zip(self, file_path: Path) -> Dict[str, Any]:
        """Valida completitud e integridad de paquetes ZIP (ESEF / taxonomías)."""
        reasons = []
        metrics = {}
        
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                corrupt_file = zf.testzip()
                if corrupt_file:
                    return {
                        "completeness_status": CompletenessStatus.INVALID_FORMAT.value,
                        "is_complete": False,
                        "should_quarantine": True,
                        "reasons": [f"Archivo ZIP corrupto en entrada interna: '{corrupt_file}'."],
                        "metrics": {"corrupt_file": corrupt_file}
                    }

                infolist = zf.infolist()
                filenames = [info.filename for info in infolist]
                metrics["total_files_count"] = len(infolist)
                metrics["file_list"] = filenames

                # Comprobar si hay archivos internos truncados (0 bytes no intencionales)
                empty_files = [info.filename for info in infolist if info.file_size == 0 and not info.filename.endswith("/")]
                metrics["empty_files_count"] = len(empty_files)
                if empty_files:
                    reasons.append(f"El ZIP contiene {len(empty_files)} archivos vacíos de 0 bytes.")

                # Buscar documento primario (XHTML o PDF)
                primary_docs = [f for f in filenames if f.lower().endswith((".xhtml", ".htm", ".html", ".pdf")) and not f.startswith("__MACOSX")]
                taxonomies = [f for f in filenames if f.lower().endswith(".xsd")]
                linkbases = [f for f in filenames if any(f.lower().endswith(lb) for lb in ["_cal.xml", "_def.xml", "_lab.xml", "_pre.xml"])]
                
                metrics["primary_candidates_count"] = len(primary_docs)
                metrics["taxonomies_count"] = len(taxonomies)
                metrics["linkbases_count"] = len(linkbases)

                if not primary_docs:
                    return {
                        "completeness_status": CompletenessStatus.PARTIAL.value,
                        "is_complete": False,
                        "should_quarantine": True,
                        "reasons": ["El paquete ZIP no contiene ningún documento primario XHTML o PDF."],
                        "metrics": metrics
                    }

                status = CompletenessStatus.ZIP_BUNDLE.value
                is_complete = True
                should_quarantine = False
                reasons.append(f"Paquete ZIP ESEF válido con {len(infolist)} archivos, {len(primary_docs)} documentos primarios y {len(taxonomies)} taxonomías.")

                return {
                    "completeness_status": status,
                    "is_complete": is_complete,
                    "should_quarantine": should_quarantine,
                    "reasons": reasons,
                    "metrics": metrics
                }

        except zipfile.BadZipFile as bz:
            return {
                "completeness_status": CompletenessStatus.INVALID_FORMAT.value,
                "is_complete": False,
                "should_quarantine": True,
                "reasons": [f"Archivo no es un ZIP válido o está dañado: {str(bz)}"],
                "metrics": {}
            }
