#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
STATER / ARGOS MOTOR — AUDITOR Y CLASIFICADOR DOCUMENTAL CON AZURE AI
================================================================================
Combina Azure AI Document Intelligence + Azure OpenAI (gpt-4o-mini) para:
  1. Extraer y verificar portadas de informes financieros (PDF, HTML, ZIP).
  2. Auditar coherencia contra el universo institucional (Empresa, CIF/ISIN, Año).
  3. Clasificar en la taxonomía canónica:
     - País
     - Mercado (IBEX, Continuo, Growth, Prime Standard, General Standard, Scale...)
     - Año real auditado
     - Empresa (Razón social y Ticker canónico)
     - Tipo de informe (Anual Auditado, Trimestral, Semestral, Gestión, Hecho Relevante...)
  4. Organizar en D:/ARGOS_DATA/lake/ o desviar a D:/ARGOS_DATA/quarantine_coherence/
================================================================================
"""

import os
import sys
import json
import time
import re
import argparse
from pathlib import Path
from enum import Enum
from typing import Optional, Dict, Any, List

import fitz  # PyMuPDF
from pydantic import BaseModel, Field
from openai import AzureOpenAI
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient

ROOT = Path(__file__).resolve().parents[1]  # ARGOS_MOTOR
SECRETS_FILE = ROOT / "config" / "azure_secrets.json"
DATA_RAW = Path("D:/ARGOS_DATA/raw")
DATA_LAKE = Path("D:/ARGOS_DATA/lake")
DATA_QUARANTINE = Path("D:/ARGOS_DATA/quarantine_coherence")


class MercadoEnum(str, Enum):
    IBEX35 = "IBEX35"
    MERCADO_CONTINUO = "MERCADO_CONTINUO"
    BME_GROWTH = "BME_GROWTH_DESARROLLO"
    PRIME_STANDARD = "PRIME_STANDARD"
    GENERAL_STANDARD = "GENERAL_STANDARD"
    SCALE_GROWTH = "SCALE_GROWTH"
    FREIVERKEHR = "FREIVERKEHR_OPEN_MARKET"
    EURONEXT_A = "EURONEXT_COMPARTIMENT_A"
    EURONEXT_GROWTH = "EURONEXT_GROWTH"
    NYSE_NASDAQ = "NYSE_NASDAQ"
    OTRO = "OTRO"


class TipoInformeEnum(str, Enum):
    ANUAL_AUDITADO = "INFORME_ANUAL_CUENTAS_CONSOLIDADAS_AUDITORIA"
    SEMESTRAL = "INFORME_FINANCIERO_SEMESTRAL"
    TRIMESTRAL = "INFORME_TRIMESTRAL_INTERINO"
    INFORME_GESTION = "INFORME_DE_GESTION_EXCLUSIVO"
    HECHO_RELEVANTE = "HECHO_RELEVANTE_INFORMACION_PRIVILEGIADA"
    FOLLETO_EMISION = "FOLLETO_EMISION_PROSPECTUS"
    DESCONOCIDO_NO_FINANCIERO = "NO_FINANCIERO_O_CORRUPTO"


class ClasificacionDocumento(BaseModel):
    pais: str = Field(description="País de la sociedad: ESPANA, ALEMANIA, FRANCIA, ESTADOS_UNIDOS, etc.")
    mercado: MercadoEnum = Field(description="Segmento o mercado bursátil de cotización")
    ano_ejercicio_real: int = Field(description="Año del ejercicio económico auditado dentro del informe (ej: 2023)")
    empresa_detectada: str = Field(description="Razón social oficial identificada en el documento")
    cif_isin_lei: Optional[str] = Field(default=None, description="Identificador fiscal, ISIN o LEI si figura")
    tipo_informe: TipoInformeEnum = Field(description="Clasificación del tipo de informe")
    es_coherente_con_nombre_esperado: bool = Field(description="True si el documento corresponde a la empresa esperada")
    motivo_incoherencia: Optional[str] = Field(default=None, description="Motivo en caso de error, 404, o discrepancia")


def load_secrets() -> Dict[str, Any]:
    if not SECRETS_FILE.exists():
        print(f"[ERROR] Archivo no encontrado: {SECRETS_FILE}")
        sys.exit(1)
    with open(SECRETS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def test_connections(secrets: Dict[str, Any]):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("=" * 65)
    print("  VERIFICACIÓN DE CONEXIÓN CON AZURE AI")
    print("=" * 65)
    
    # 1. Probar Document Intelligence
    doc_endpoint = secrets.get("document_intelligence_endpoint", "")
    doc_key = secrets.get("document_intelligence_key", "")
    print(f"\n1. Azure Document Intelligence:")
    print(f"   Endpoint: {doc_endpoint}")
    if not doc_endpoint or "PEGA_AQUI" in doc_endpoint:
        print("   [AVISO] Falta configurar endpoint en azure_secrets.json")
    else:
        try:
            client = DocumentIntelligenceClient(endpoint=doc_endpoint, credential=AzureKeyCredential(doc_key))
            print("   [OK] Conexión con Document Intelligence inicializada con éxito.")
        except Exception as e:
            print(f"   [ERROR] Error al conectar Document Intelligence: {e}")

    # 2. Probar Azure OpenAI
    oai_endpoint = secrets.get("openai_endpoint", "")
    oai_key = secrets.get("openai_key", "")
    deployment = secrets.get("openai_deployment", "gpt-4o-mini")
    print(f"\n2. Azure OpenAI Service:")
    print(f"   Endpoint:   {oai_endpoint}")
    print(f"   Deployment: {deployment}")
    if not oai_endpoint or "PEGA_AQUI" in oai_endpoint:
        print("   [AVISO] Falta configurar endpoint en azure_secrets.json")
    else:
        try:
            client = AzureOpenAI(
                azure_endpoint=oai_endpoint,
                api_key=oai_key,
                api_version="2024-08-01-preview"
            )
            resp = client.chat.completions.create(
                model=deployment,
                messages=[{"role": "user", "content": "Responde 'OK' para verificar la conexión."}],
                max_tokens=10
            )
            respuesta = resp.choices[0].message.content.strip()
            print(f"   [OK] Azure OpenAI ({deployment}) respondió con éxito: '{respuesta}'")
        except Exception as e:
            print(f"   [ERROR] Error al invocar Azure OpenAI: {e}")
    print("=" * 65)


def extraer_portada(path: Path, secrets: Dict[str, Any]) -> str:
    """Extrae las páginas de portada/carátula con fallback a Document Intelligence."""
    ext = path.suffix.lower()

    # Si es HTML
    if ext in [".htm", ".html"]:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore")[:35000], "html.parser")
            return soup.get_text(separator=" ")[:3500]
        except Exception:
            return path.read_text(encoding="utf-8", errors="ignore")[:2500]

    # Si es ZIP ESEF
    if ext == ".zip":
        try:
            import zipfile
            with zipfile.ZipFile(path) as z:
                # Buscar xhtml principal
                xbrl_files = [n for n in z.namelist() if n.endswith((".xhtml", ".htm")) and not n.startswith("__")]
                if xbrl_files:
                    sample = z.read(xbrl_files[0])[:35000].decode("utf-8", errors="ignore")
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(sample, "html.parser")
                    return f"[PAQUETE ESEF XBRL OFICIAL]\n" + soup.get_text(separator=" ")[:3000]
        except Exception:
            pass

    # Si es PDF
    if ext == ".pdf":
        try:
            doc = fitz.open(path)
            texto = ""
            for p_idx in range(min(3, len(doc))):
                texto += doc[p_idx].get_text() + "\n"
            doc.close()

            # Si tiene texto digital real
            if len(texto.strip()) > 150:
                return texto[:3500]
        except Exception:
            pass

        # Fallback: Document Intelligence si el PDF es escaneado
        doc_endpoint = secrets.get("document_intelligence_endpoint")
        doc_key = secrets.get("document_intelligence_key")
        if doc_endpoint and doc_key and "PEGA_AQUI" not in doc_endpoint:
            try:
                # Optimización de alto rendimiento: recortar solo las primeras 2 páginas en memoria
                doc_full = fitz.open(path)
                sub_doc = fitz.open()
                sub_doc.insert_pdf(doc_full, from_page=0, to_page=min(1, len(doc_full) - 1))
                pdf_bytes = sub_doc.tobytes()
                doc_full.close()
                sub_doc.close()

                client = DocumentIntelligenceClient(endpoint=doc_endpoint, credential=AzureKeyCredential(doc_key))
                poller = client.begin_analyze_document(
                    model_id="prebuilt-layout",
                    body=pdf_bytes
                )
                res = poller.result()
                return res.content[:3500]
            except Exception as e:
                return f"[Error OCR]: {e}"

    return path.stem.replace("_", " ")


def clasificar_con_openai(texto: str, empresa_esperada: str, ano_esperado: str, secrets: Dict[str, Any]) -> ClasificacionDocumento:
    client = AzureOpenAI(
        azure_endpoint=secrets["openai_endpoint"],
        api_key=secrets["openai_key"],
        api_version="2024-08-01-preview"
    )

    system_prompt = (
        "Eres un auditor senior del regulador de mercados. Analiza el texto de portada e inicio de un informe "
        "financiero y clasifícalo en formato estructurado estricto. Determina con total rigor si el documento "
        "corresponde a la empresa y año esperados o si es una página de error/otra entidad."
    )

    user_prompt = f"""DATOS ESPERADOS EN BASE DE DATOS:
- Empresa: {empresa_esperada}
- Año: {ano_esperado}

TEXTO EXTRAÍDO DE LA PORTADA/CABECERA DEL DOCUMENTO:
\"\"\"
{texto}
\"\"\"
"""

    response = client.beta.chat.completions.parse(
        model=secrets.get("openai_deployment", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format=ClasificacionDocumento,
        temperature=0.0
    )
    return response.choices[0].message.parsed


def main():
    parser = argparse.ArgumentParser(description="Auditor y Clasificador Documental Azure AI")
    parser.add_argument("--test-connection", action="store_true", help="Verifica las claves y conexión a Azure")
    parser.add_argument("--sample", type=int, default=0, help="Probar con N documentos de muestra")
    parser.add_argument("--file", type=str, default="", help="Auditar un archivo específico")
    args = parser.parse_args()

    secrets = load_secrets()

    if args.test_connection:
        test_connections(secrets)
        return

    if args.file:
        p = Path(args.file)
        if not p.exists():
            print(f"Archivo no encontrado: {p}")
            return
        print(f"Extrayendo portada de: {p.name}...")
        texto = extraer_portada(p, secrets)
        print("Clasificando con Azure OpenAI...")
        res = clasificar_con_openai(texto, empresa_esperada="DESCONOCIDO", ano_esperado="2024", secrets=secrets)
        print(json.dumps(res.model_dump(), indent=2, ensure_ascii=False))
        return

    print("Usa --test-connection para probar las claves o --sample 5 para ver una prueba.")


if __name__ == "__main__":
    main()
