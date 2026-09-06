"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Módulo de Resolución de Identidad Regulatoria (Entity Resolver).

Resuelve y valida la identidad jurídica de entidades contra el Catálogo Maestro
(config/master_universe_es.json) y la API oficial de GLEIF (Global Legal Entity Identifier Foundation).

Regla de Oro:
- Similitud calculada mediante combinación de coincidencia de CIF/NIF exacto
  y score de similitud de cadenas ponderado (Jaro-Winkler / Token-Sort).
- Si el score es < 0.90 y el CIF/NIF no coincide exactamente, la resolución se RECHAZA.
- Previene matemáticamente cualquier colisión entre empresas (ej. ACS vs Prosegur, Urbas vs Aena).
"""

import sys
import os
import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GLEIF_API = "https://api.gleif.org/api/v1/lei-records"
MASTER_UNIVERSE_PATH = Path("config/master_universe_es.json")


def normalize_entity_name(name: str) -> str:
    """Normaliza una razón social eliminando acentos, sufijos jurídicos y signos de puntuación."""
    if not name:
        return ""
    # Descomponer caracteres con acento
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_name = "".join([c for c in nfkd if not unicodedata.combining(c)]).upper()
    
    # Eliminar puntos entre letras de siglas (S.A. -> SA, S.L. -> SL, S.A.U. -> SAU)
    ascii_name = re.sub(r'\.', '', ascii_name)
    
    # Eliminar signos de puntuación
    clean = re.sub(r'[^A-Z0-9\s]', ' ', ascii_name)
    
    # Eliminar términos societarios comunes
    stopwords = {
        "SOCIEDAD", "ANONIMA", "SA", "SL", "SE", "SAU", "SLU", "HOLDING", "HOLDINGS", 
        "GROUP", "GRUPO", "CORPORACION", "SME", "COMPANIA", "DE", "Y", "EN",
        "ESPANA", "ESPANOLA", "INTERNATIONAL", "GLOBAL"
    }
    tokens = [w for w in clean.split() if w not in stopwords]
    return " ".join(tokens)


def normalize_cif(cif: str) -> str:
    """Normaliza un CIF/NIF eliminando guiones y espacios."""
    if not cif:
        return ""
    return re.sub(r'[^A-Z0-9]', '', cif.upper())


def jaro_winkler_similarity(s1: str, s2: str) -> float:
    """Calcula la similitud de Jaro-Winkler entre dos cadenas (0.0 a 1.0)."""
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)
    max_dist = max(len1, len2) // 2 - 1
    if max_dist < 0:
        max_dist = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - max_dist)
        end = min(i + max_dist + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    transpositions //= 2
    jaro = (matches / len1 + matches / len2 + (matches - transpositions) / matches) / 3.0

    # Winkler prefix bonus
    prefix = 0
    max_p = min(4, min(len1, len2))
    for i in range(max_p):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break

    return jaro + prefix * 0.1 * (1.0 - jaro)


def token_sort_similarity(s1: str, s2: str) -> float:
    """Calcula la similitud de tokens ordenados (Jaccard / Overlap)."""
    t1 = set(s1.split())
    t2 = set(s2.split())
    if not t1 or not t2:
        return 0.0
    intersection = len(t1 & t2)
    union = len(t1 | t2)
    return intersection / union if union > 0 else 0.0


def compute_comprehensive_similarity(query_name: str, target_name: str, 
                                     query_cif: Optional[str] = None, 
                                     target_cif: Optional[str] = None) -> float:
    """
    Calcula un score compuesto de similitud (0.0 a 1.0).
    Si los CIF/NIF coinciden exactamente, el score es 1.0.
    Si los CIF/NIF son distintos y válidos, se penaliza drásticamente.
    """
    norm_qcif = normalize_cif(query_cif) if query_cif else ""
    norm_tcif = normalize_cif(target_cif) if target_cif else ""

    if norm_qcif and norm_tcif:
        if norm_qcif == norm_tcif:
            return 1.0
        else:
            # CIFs explícitamente discordantes -> no son la misma entidad jurídica
            return 0.10

    n1 = normalize_entity_name(query_name)
    n2 = normalize_entity_name(target_name)

    if not n1 or not n2:
        return 0.0
    if n1 == n2:
        return 1.0

    jw = jaro_winkler_similarity(n1, n2)
    ts = token_sort_similarity(n1, n2)

    # Si una cadena está completamente contenida en la otra (ej. "ACS" en "ACS ACTIVIDADES...")
    contains_bonus = 0.0
    if n1 in n2 or n2 in n1:
        contains_bonus = 0.15

    composite = (jw * 0.6) + (ts * 0.4) + contains_bonus
    return min(1.0, composite)


class EntityResolver:
    """
    Resolvedor de Entidades Regulatorias de Nivel Institucional.
    Consulta el catálogo maestro y realiza resolución segura contra GLEIF.
    """

    def __init__(self, master_universe_path: Path = MASTER_UNIVERSE_PATH):
        self.master_path = master_universe_path
        self.master_data = self._load_master_universe()
        self.companies = self.master_data.get("companies", {})
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ARGOS_MOTOR/3.0 (Regulatory Ingestion Engine; contact@stater.es)",
            "Accept": "application/json"
        })

    def _load_master_universe(self) -> Dict[str, Any]:
        if not self.master_path.exists():
            from mod_01_ingestion.src.master_universe_builder import build_master_universe
            return build_master_universe()
        try:
            with open(self.master_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            raise RuntimeError(f"Error cargando catálogo maestro {self.master_path}: {e}")

    def get_by_ticker(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Recupera la entidad oficial del catálogo por Ticker exacto."""
        if not ticker:
            return None
        return self.companies.get(ticker.upper())

    def get_by_lei(self, lei: str) -> Optional[Dict[str, Any]]:
        """Recupera la entidad oficial del catálogo por LEI."""
        if not lei:
            return None
        lei_clean = lei.strip().upper()
        for comp in self.companies.values():
            if comp.get("lei") and comp["lei"].strip().upper() == lei_clean:
                return comp
        return None

    def get_by_cif(self, cif: str) -> Optional[Dict[str, Any]]:
        """Recupera la entidad oficial del catálogo por CIF/NIF."""
        if not cif:
            return None
        cif_clean = normalize_cif(cif)
        for comp in self.companies.values():
            if comp.get("cif_nif") and normalize_cif(comp["cif_nif"]) == cif_clean:
                return comp
        return None

    def resolve_entity(self, query: str, expected_cif: Optional[str] = None, 
                       min_confidence: float = 0.90,
                       enable_remote_gleif: bool = False) -> Tuple[Optional[Dict[str, Any]], float, str]:
        """
        Resuelve una consulta de entidad garantizando que el score >= min_confidence.
        
        Retorna:
            (entity_dict_or_None, confidence_score, resolution_reason)
        """
        if not query:
            return None, 0.0, "CONSULTA_VACIA"

        q_clean = query.strip().upper()

        # 1. Búsqueda exacta por Ticker
        if q_clean in self.companies:
            entity = self.companies[q_clean]
            if expected_cif and normalize_cif(expected_cif) != normalize_cif(entity.get("cif_nif", "")):
                return None, 0.1, f"CIF_MISMATCH_ON_TICKER: Esperado {expected_cif} vs {entity.get('cif_nif')}"
            return entity, 1.0, "EXACT_TICKER_MATCH"

        # 2. Búsqueda exacta por CIF en la propia consulta
        query_cif = normalize_cif(query)
        if len(query_cif) == 9:
            by_cif = self.get_by_cif(query_cif)
            if by_cif:
                if expected_cif and normalize_cif(expected_cif) != query_cif:
                    return None, 0.1, f"CIF_MISMATCH: Consulta {query_cif} vs Esperado {expected_cif}"
                return by_cif, 1.0, "EXACT_CIF_MATCH"

        # 3. Extraer CIF de la propia consulta si existe
        match_cif = re.search(r'\b([A-HJ-NP-SUVW][\s\-]?[0-9]{7}[\s\-]?[0-9A-J])\b', query, re.IGNORECASE)
        query_extracted_cif = normalize_cif(match_cif.group(1)) if match_cif else None

        # 4. Búsqueda en catálogo maestro con similitud compuesta
        best_match = None
        best_score = 0.0
        best_ticker = None

        for ticker, comp in self.companies.items():
            name = comp.get("name_legal", "")
            alt_names = comp.get("historical_name_changes", [])
            cif = comp.get("cif_nif", "")

            # Score contra nombre legal usando el CIF extraído del query
            score = compute_comprehensive_similarity(query, name, query_extracted_cif, cif)
            
            # Score contra nombres históricos alternativos
            for alt in alt_names:
                alt_score = compute_comprehensive_similarity(query, alt, query_extracted_cif, cif)
                if alt_score > score:
                    score = alt_score

            # Si se especificó un expected_cif y la entidad candidata no coincide con expected_cif
            if expected_cif and normalize_cif(expected_cif) != normalize_cif(cif):
                score *= 0.1  # Penalización crítica por mismatch con el CIF esperado

            if score > best_score:
                best_score = score
                best_match = comp
                best_ticker = ticker

        if best_score >= min_confidence and best_match:
            return best_match, best_score, f"HIGH_CONFIDENCE_CATALOG_MATCH ({best_ticker})"

        # 5. Consulta a GLEIF API si está habilitada explícitamente
        if enable_remote_gleif:
            try:
                gleif_lei, gleif_name, gleif_score = self._query_gleif_api(query)
                if gleif_score >= min_confidence and gleif_lei:
                    local_by_lei = self.get_by_lei(gleif_lei)
                    if local_by_lei:
                        return local_by_lei, gleif_score, f"GLEIF_RESOLVED_TO_CATALOG ({local_by_lei['ticker']})"
            except Exception:
                pass

        return None, best_score, f"RECHAZADO: Confianza insuficiente ({best_score:.2f} < {min_confidence:.2f})"

    def _query_gleif_api(self, company_name: str) -> Tuple[Optional[str], Optional[str], float]:
        """Consulta la API de GLEIF filtrando por España y calcula similitud."""
        url = f"{GLEIF_API}?filter[entity.legalName]={requests.utils.quote(company_name)}&filter[entity.jurisdiction]=ES&page[size]=5"
        resp = self.session.get(url, timeout=8)
        if resp.status_code != 200:
            return None, None, 0.0

        data = resp.json().get("data", [])
        if not data:
            return None, None, 0.0

        best_lei = None
        best_name = None
        best_score = 0.0

        for item in data:
            lei = item.get("id", "")
            attrs = item.get("attributes", {}).get("entity", {})
            name = attrs.get("legalName", {}).get("name", "")
            score = compute_comprehensive_similarity(company_name, name)
            if score > best_score:
                best_score = score
                best_lei = lei
                best_name = name

        return best_lei, best_name, best_score
