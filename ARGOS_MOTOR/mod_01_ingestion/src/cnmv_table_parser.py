"""
STATER MOTOR ARGOS — MOD_01: CNMV Table Parser & Link Extractor.
Specialized parser for CNMV Periodic Financial Information (IPP / ESEF) tables.
Locates exact rows by issuer, fiscal year, and consolidation type, and categorizes
cell links by official column (ZIP/XBRI, PDF Audit, Official Record, Viewer Page).
"""
import re
from urllib.parse import urljoin
from typing import Dict, Any, List, Optional, Tuple

from mod_01_ingestion.src.models import CNMVTableCellLink


class CNMVTableParser:
    """Analizador especializado de tablas de informes financieros de la CNMV."""

    COLUMN_KEYWORDS = {
        "ZIP_XBRI": [re.compile(r"xbri|esef|zip|paquete\s+esef", re.IGNORECASE)],
        "PDF_AUDITORIA": [re.compile(r"informe\s+auditor[ií]a|cuentas\s+anuales|pdf|documento\s+pdf", re.IGNORECASE)],
        "TIPO_VISUALIZACION": [re.compile(r"tipo|ver\s+informe|visualizar|consulta|detalle", re.IGNORECASE)],
        "REGISTRO": [re.compile(r"n[ºo]\s*reg|registro|entrada", re.IGNORECASE)],
        "EJERCICIO": [re.compile(r"ejercicio|periodo|semestre|a[ñn]o", re.IGNORECASE)],
    }

    def __init__(self, base_url: str = "https://www.cnmv.es"):
        self.base_url = base_url

    def parse_table_headers(self, table_html: str) -> List[str]:
        """Extrae e identifica los nombres de las columnas de la cabecera <th>."""
        headers = []
        th_matches = re.findall(r'<th\b[^>]*>(.*?)</th>', table_html, re.IGNORECASE | re.DOTALL)
        for idx, raw_th in enumerate(th_matches):
            clean_text = re.sub(r'<[^>]+>', '', raw_th).strip()
            headers.append(clean_text or f"COL_{idx}")
        return headers

    def parse_financial_rows(
        self,
        html_content: str,
        page_url: str,
        target_year: Optional[int] = None,
        is_consolidated: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Analiza el HTML completo de la página de la CNMV y extrae todas las filas que
        coincidan con el ejercicio solicitado y el tipo de información (Consolidado/Individual).
        """
        results = []
        # Localizar bloques <table>
        table_matches = re.findall(r'<table\b[^>]*>(.*?)</table>', html_content, re.IGNORECASE | re.DOTALL)

        for table_html in table_matches:
            headers = self.parse_table_headers(table_html)
            row_matches = re.findall(r'<tr\b[^>]*>(.*?)</tr>', table_html, re.IGNORECASE | re.DOTALL)

            for row_html in row_matches:
                # Omitir filas que solo contienen <th>
                if "<td" not in row_html.lower():
                    continue

                cells = re.findall(r'<td\b[^>]*>(.*?)</td>', row_html, re.IGNORECASE | re.DOTALL)
                if not cells:
                    continue

                # Extraer texto de la fila completa para filtrado
                row_text = re.sub(r'<[^>]+>', ' ', row_html)

                # Filtrar por año si se especifica
                if target_year:
                    if str(target_year) not in row_text:
                        continue

                # Filtrar por tipo consolidado si procede
                if is_consolidated and "individual" in row_text.lower() and "consolidado" not in row_text.lower():
                    continue

                # Analizar enlaces celda por celda
                cell_links: List[CNMVTableCellLink] = []
                for col_idx, cell_html in enumerate(cells):
                    header_name = headers[col_idx] if col_idx < len(headers) else f"COL_{col_idx}"
                    extracted_in_cell = self._extract_links_from_cell(cell_html, header_name, col_idx, page_url)
                    cell_links.extend(extracted_in_cell)

                if cell_links:
                    # Clasificar enlaces prioritarios
                    zip_link = next((l for l in cell_links if l.inferred_type == "ZIP_XBRI"), None)
                    pdf_link = next((l for l in cell_links if l.inferred_type == "PDF_AUDIT"), None)
                    viewer_link = next((l for l in cell_links if l.inferred_type == "VIEWER_PAGE"), None)
                    reg_link = next((l for l in cell_links if l.inferred_type == "OFFICIAL_RECORD_PAGE"), None)

                    results.append({
                        "row_text": row_text.strip(),
                        "headers": headers,
                        "cell_links": [l.to_dict() for l in cell_links],
                        "priority_zip_link": zip_link.to_dict() if zip_link else None,
                        "priority_pdf_link": pdf_link.to_dict() if pdf_link else None,
                        "viewer_link": viewer_link.to_dict() if viewer_link else None,
                        "official_reg_link": reg_link.to_dict() if reg_link else None,
                    })

        return results

    def _extract_links_from_cell(
        self,
        cell_html: str,
        header_name: str,
        col_index: int,
        page_url: str
    ) -> List[CNMVTableCellLink]:
        """Extrae enlaces <a> de una celda específica y determina su tipo por columna y atributos."""
        links = []
        a_matches = re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', cell_html, re.IGNORECASE | re.DOTALL)

        for m in a_matches:
            raw_href = m.group(1).strip()
            visible_text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            resolved_url = urljoin(page_url, raw_href)

            inferred_type = self._infer_link_type(raw_href, visible_text, header_name)

            links.append(CNMVTableCellLink(
                visible_text=visible_text,
                href=raw_href,
                resolved_url=resolved_url,
                column_name=header_name,
                column_index=col_index,
                inferred_type=inferred_type,
                cell_html=cell_html.strip(),
                parent_page_url=page_url
            ))

        return links

    def _infer_link_type(self, href: str, visible_text: str, column_name: str) -> str:
        """Determina con precisión el tipo de enlace según URL, texto y columna."""
        href_lower = href.lower()
        text_lower = visible_text.lower()
        col_lower = column_name.lower()

        # 1. Columna o enlace ZIP / XBRI
        if href_lower.endswith(".zip") or href_lower.endswith(".xbri") or "xbri" in href_lower or "esef" in col_lower or "zip" in col_lower:
            return "ZIP_XBRI"

        # 2. Columna o enlace PDF de auditoría
        if href_lower.endswith(".pdf") or "pdf" in href_lower or "auditor" in col_lower or "auditor" in text_lower:
            return "PDF_AUDIT"

        # 3. Número de registro oficial
        if "reg" in col_lower or "registro" in col_lower or "nreg=" in href_lower or re.search(r"^\d{8,12}$", visible_text):
            return "OFFICIAL_RECORD_PAGE"

        # 4. Visualizador / Ver informe / Consulta
        if "ver" in text_lower or "visualiz" in col_lower or "consulta" in href_lower or "tipo" in col_lower:
            return "VIEWER_PAGE"

        return "UNKNOWN"
