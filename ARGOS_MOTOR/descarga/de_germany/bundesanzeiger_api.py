#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
STATER / ARGOS MOTOR — BUNDESANZEIGER HTTP API CLIENT (CANAL 3)
================================================================================
Cliente HTTP de alto rendimiento para el Bundesanzeiger alemán.
Inspirado en la arquitectura de bundesAPI/deutschland:
  - Realiza peticiones HTTP puras sin navegador visual (0 Playwright, 0 Selenium).
  - Gestiona cookies de sesión Wicket y consentimiento de cookies (cc=11).
  - Extrae publicaciones oficiales (Konzernabschluss, Jahresabschluss, Bilanz).
  - Devuelve informes estructurados con fecha, título, contenido HTML y metadatos.
================================================================================
"""

import sys
import time
import urllib.parse
from typing import Dict, List, Optional
import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

COOKIE_CONSENT = "1790023174-4e0021c737b2c4ce-11"  # Acepta todas las cookies


class BundesanzeigerReport:
    def __init__(self, date_str: str, name: str, content_url: str, company: str,
                 report_html: str = "", report_text: str = ""):
        self.date_str = date_str
        self.name = name
        self.content_url = content_url
        self.company = company
        self.report_html = report_html
        self.report_text = report_text

    def to_dict(self):
        return {
            "date": self.date_str,
            "name": self.name,
            "company": self.company,
            "content_url": self.content_url,
            "has_content": bool(self.report_html),
            "content_bytes": len(self.report_html.encode('utf-8')) if self.report_html else 0
        }


class BundesanzeigerAPI:
    """Cliente HTTP limpio para Bundesanzeiger sin requerir dependencias pesadas."""

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        })
        self.session.cookies.set("cc", COOKIE_CONSENT, domain="www.bundesanzeiger.de")
        self._initialized = False

    def init_session(self) -> bool:
        """Inicializa la sesión y obtiene JSESSIONID."""
        try:
            r = self.session.get("https://www.bundesanzeiger.de/pub/de/start", timeout=self.timeout)
            self._initialized = r.status_code == 200
            return self._initialized
        except Exception as e:
            print(f"  [3-API] Error inicializando sesión HTTP: {e}")
            return False

    def search(self, company_name: str, target_year: Optional[int] = None) -> List[BundesanzeigerReport]:
        """
        Busca publicaciones oficiales para un emisor.
        Filtra opcionalmente por año contable.
        """
        if not self._initialized:
            if not self.init_session():
                return []

        search_url = (
            f"https://www.bundesanzeiger.de/pub/de/start"
            f"?0-1.-top~content~panel-left~card-form="
            f"&fulltext={urllib.parse.quote_plus(company_name)}"
            f"&area_select=22"  # Area 22 = Rechnungslegung/Finanzberichte
            f"&search_button=Suchen"
        )

        try:
            resp = self.session.get(search_url, timeout=self.timeout)
            if resp.status_code != 200:
                # Intentar vía POST estándar si GET redirige
                resp = self.session.post(
                    "https://www.bundesanzeiger.de/pub/de/start",
                    data={
                        "0-1.-top~content~panel-left~card-form": "",
                        "fulltext": company_name,
                        "area_select": "22",
                        "search_button": "Suchen"
                    },
                    timeout=self.timeout
                )
        except Exception as e:
            print(f"  [3-API] Error en búsqueda de '{company_name}': {e}")
            return []

        soup = BeautifulSoup(resp.text, 'html.parser')
        rows = soup.select(".result_container .row, .result")
        if not rows:
            # Buscar en formato tabla alternativo
            rows = soup.select("table.result-table tr")

        reports = []
        year_str = str(target_year) if target_year else ""

        for row in rows:
            info_el = row.select_one(".info")
            if not info_el:
                continue
            link_el = info_el.select_one("a[href]")
            if not link_el:
                continue

            title = link_el.get_text(" ", strip=True)
            href = link_el.get("href", "")
            if not href.startswith("http"):
                href = urllib.parse.urljoin("https://www.bundesanzeiger.de/pub/de/", href)

            first_el = row.select_one(".first")
            company = first_el.get_text(" ", strip=True) if first_el else company_name

            date_el = row.select_one(".date")
            pub_date = date_el.get_text(" ", strip=True) if date_el else ""

            # Si se especificó año, filtrar por relevancia
            title_lower = title.lower()
            if any(k in title_lower for k in ['zahlungsbericht', 'gleichstellung', 'entgeltgleichheit', 'berichtigung']):
                continue

            if year_str:
                if year_str not in title and year_str not in pub_date:
                    continue

            reports.append(BundesanzeigerReport(pub_date, title, href, company))

        return reports

    def fetch_report_content(self, report: BundesanzeigerReport) -> Optional[str]:
        """Descarga el contenido completo de una publicación si no requiere CAPTCHA."""
        try:
            time.sleep(1.0)  # Cortesía con el servidor
            resp = self.session.get(report.content_url, timeout=self.timeout)
            if resp.status_code != 200:
                return None

            html = resp.text
            # Verificar si saltó CAPTCHA
            if "Sicherheitsabfrage" in html or "captcha" in html.lower() or "Zeichen eingeben" in html:
                print(f"  [3-API] CAPTCHA requerido en {report.content_url[:50]}... (Bypass activo)")
                return None

            soup = BeautifulSoup(html, 'html.parser')
            container = soup.select_one(".publication_container, .publication-text, .content-container, article")
            if container:
                report.report_html = html
                report.report_text = container.get_text(" ", strip=True)
                return html
            return None
        except Exception as e:
            print(f"  [3-API] Error descargando contenido de informe: {e}")
            return None
