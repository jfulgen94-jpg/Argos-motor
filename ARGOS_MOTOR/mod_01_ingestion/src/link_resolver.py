"""
STATER MOTOR ARGOS — MOD_01: Link and Resource Resolver.
Follows HTTP redirects, resolves relative URLs, classifies candidate resources,
and distinguishes between document files, navigation indices, and error responses.
"""
import re
import mimetypes
from urllib.parse import urljoin, urlparse, unquote
from typing import Dict, Any, List, Optional, Tuple, Set
import httpx


class LinkResolver:
    """Resolvedor inteligente de recursos y enlaces regulatorios."""

    # Extensiones y patrones por tipo de recurso
    RESOURCE_EXTENSIONS = {
        "ZIP": [".zip", ".tar.gz", ".tgz"],
        "PDF": [".pdf"],
        "XHTML": [".xhtml", ".html", ".htm"],
        "XML": [".xml"],
        "TAXONOMY_SCHEMA": [".xsd"],
        "LINKBASE": ["_cal.xml", "_def.xml", "_lab.xml", "_pre.xml", "_ref.xml"],
        "IMAGE": [".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"],
    }

    NAVIGATION_PATTERNS = [
        re.compile(r"search|consulta|resultado|browse|index|list|default\.aspx|home|portal", re.IGNORECASE),
        re.compile(r"view_document\.aspx\?id=", re.IGNORECASE),
        re.compile(r"sec\.gov/cgi-bin/browse-edgar", re.IGNORECASE),
    ]

    ERROR_PAGE_PATTERNS = [
        re.compile(r"<title>.*(error|404|not found|forbidden|403|500|exception|sesión caducada).*</title>", re.IGNORECASE),
        re.compile(r"<h1>.*(error|no encontrado|acceso denegado|internal server error).*</h1>", re.IGNORECASE),
        re.compile(r"(página no encontrada|documento no disponible|sesión finalizada)", re.IGNORECASE),
    ]

    def __init__(self, headers: Optional[Dict[str, str]] = None, timeout: float = 30.0):
        self.headers = headers or {"User-Agent": "STATER Regulatory Engine/1.0 (dev@stater.es)"}
        self.timeout = timeout

    def resolve_url(self, base_url: str, relative_or_absolute_url: str) -> str:
        """Resuelve una URL relativa respecto de una URL de origen."""
        if not relative_or_absolute_url:
            return base_url
        return urljoin(base_url, relative_or_absolute_url.strip())

    def follow_redirects(self, url: str, client: Optional[httpx.Client] = None) -> Tuple[str, List[str], int, Dict[str, str]]:
        """
        Sigue la cadena de redirecciones HTTP registrando cada salto.
        Retorna: (url_final, redirect_chain, http_status, headers_finales)
        """
        redirect_chain = [url]
        current_url = url
        status_code = 200
        response_headers = {}

        should_close = False
        if client is None:
            client = httpx.Client(headers=self.headers, timeout=self.timeout, follow_redirects=False)
            should_close = True

        try:
            for _ in range(10):  # Máximo 10 saltos
                r = client.head(current_url)
                # Si HEAD devuelve 405 Method Not Allowed, intentar GET con stream
                if r.status_code == 405:
                    r = client.get(current_url, headers={**self.headers, "Range": "bytes=0-10"})
                
                status_code = r.status_code
                response_headers = dict(r.headers)

                if 300 <= r.status_code < 400 and "location" in r.headers:
                    next_url = self.resolve_url(current_url, r.headers["location"])
                    redirect_chain.append(next_url)
                    current_url = next_url
                else:
                    break
        except Exception:
            # Fallback en caso de error de red en HEAD
            pass
        finally:
            if should_close:
                client.close()

        return current_url, redirect_chain, status_code, response_headers

    def classify_resource_type(self, url: str, content_type: Optional[str] = None, body_sample: Optional[bytes] = None) -> str:
        """
        Determina el tipo exacto del recurso combinando URL, cabecera Content-Type y muestra de bytes iniciales.
        """
        parsed = urlparse(url)
        clean_path = unquote(parsed.path).lower()

        # 1. Comprobación por linkbases específicas de XBRL
        for lb in self.RESOURCE_EXTENSIONS["LINKBASE"]:
            if clean_path.endswith(lb):
                return "LINKBASE"

        # 2. Comprobación por extensión
        for res_type, exts in self.RESOURCE_EXTENSIONS.items():
            for ext in exts:
                if clean_path.endswith(ext):
                    return res_type

        # 3. Comprobación por Content-Type
        if content_type:
            ct = content_type.lower()
            if "application/pdf" in ct:
                return "PDF"
            elif "application/zip" in ct or "application/x-zip-compressed" in ct:
                return "ZIP"
            elif "application/xhtml+xml" in ct:
                return "XHTML"
            elif "text/html" in ct:
                return "HTML"
            elif "application/xml" in ct or "text/xml" in ct:
                return "XML"
            elif "image/" in ct:
                return "IMAGE"

        # 4. Comprobación por Magic Bytes iniciales
        if body_sample and len(body_sample) >= 4:
            if body_sample.startswith(b"%PDF"):
                return "PDF"
            elif body_sample.startswith(b"PK\x03\x04"):
                return "ZIP"
            elif b"<?xml" in body_sample[:100] or b"<html" in body_sample[:100].lower():
                if b"xmlns:ix" in body_sample[:500] or b"inlineXBRL" in body_sample[:500]:
                    return "XHTML"
                return "HTML"

        return "OTHER"

    def is_navigation_or_index_page(self, url: str, html_content: Optional[str] = None) -> bool:
        """Determina si una URL o su contenido HTML corresponde a una página de navegación o índice."""
        for pat in self.NAVIGATION_PATTERNS:
            if pat.search(url):
                return True

        if html_content:
            text_lower = html_content.lower()
            if "<table class=\"tableFile\"" in text_lower or "filing details" in text_lower or "interactive data" in text_lower:
                return True
            if "document format files" in text_lower or "data files" in text_lower:
                return True

        return False

    def detect_error_html(self, html_content: str) -> Optional[str]:
        """Detecta si un contenido HTML es en realidad una respuesta de error del servidor o sesión caducada."""
        for pat in self.ERROR_PAGE_PATTERNS:
            m = pat.search(html_content)
            if m:
                return f"Error detectado en HTML: {m.group(0)[:100]}"
        return None

    def extract_document_links(self, base_url: str, html_or_xml_content: str) -> List[Dict[str, Any]]:
        """
        Extrae y clasifica todos los enlaces a documentos, anexos, taxonomías e imágenes
        a partir de un documento contenedor (manifiesto, índice o página de filing).
        """
        found_links = []
        seen_urls: Set[str] = set()

        # Regex para extraer href / src
        link_regex = re.compile(r'(?:href|src|target)=["\']([^"\']+)["\']', re.IGNORECASE)
        for match in link_regex.finditer(html_or_xml_content):
            raw_href = match.group(1).strip()
            if not raw_href or raw_href.startswith("#") or raw_href.startswith("javascript:"):
                continue

            resolved = self.resolve_url(base_url, raw_href)
            if resolved in seen_urls:
                continue
            seen_urls.add(resolved)

            res_type = self.classify_resource_type(resolved)
            is_nav = self.is_navigation_or_index_page(resolved)

            found_links.append({
                "raw_url": raw_href,
                "resolved_url": resolved,
                "resource_type": res_type,
                "is_navigation_page": is_nav,
                "filename": resolved.split("/")[-1].split("?")[0]
            })

        return found_links
