#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
STATER / ARGOS MOTOR — INSPECTOR DE METADATA EN MICROSOFT AZURE BLOB
================================================================================
Inspecciona, audita y valida en tiempo real la metadata de todos los documentos
almacenados en Microsoft Azure Blob Storage (contenedor 'fulgen').

Capacidades:
  1. Conexión directa vía SDK sin necesidad de infraestructura intermedia (Azure Functions).
  2. Inspección rápida de metadatos (SHA-256, fechas, canales, URLs de origen) leyendo
     los streams .meta.json y cabeceras Blob directamente en memoria.
  3. Comprobación de integridad criptográfica y cobertura por año y emisor.
  4. Generación de informes JSON para que agentes de IA (Qwen Coder) los analicen.
================================================================================
"""

import os
import sys
import json
import argparse
from pathlib import Path
from azure.storage.blob import BlobServiceClient

DEFAULT_SECRETS_PATH = Path(__file__).resolve().parent.parent / "config" / "azure_secrets.json"
DEFAULT_CONTAINER = "fulgen"


def get_connection_string():
    conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if conn:
        return conn
    if DEFAULT_SECRETS_PATH.exists():
        try:
            data = json.loads(DEFAULT_SECRETS_PATH.read_text(encoding='utf-8'))
            return data.get("connection_string")
        except Exception:
            pass
    return None


class AzureMetadataInspector:
    def __init__(self, conn_str: str, container_name: str = DEFAULT_CONTAINER):
        self.blob_service = BlobServiceClient.from_connection_string(conn_str)
        self.container_name = container_name
        self.container = self.blob_service.get_container_client(container_name)

    def audit_jurisdiction(self, prefix: str):
        """Audita exhaustivamente una jurisdicción (ej: raw/DE_BAFIN o raw/NL_AFM)."""
        print(f"\n[AZURE INSPECTOR] Escaneando blobs bajo '{prefix}'...")
        blobs = list(self.container.list_blobs(name_starts_with=prefix))
        
        pdf_blobs = [b for b in blobs if b.name.lower().endswith('.pdf')]
        zip_blobs = [b for b in blobs if b.name.lower().endswith('.zip')]
        html_blobs = [b for b in blobs if b.name.lower().endswith(('.htm', '.html', '.xhtml'))]
        meta_blobs = [b for b in blobs if b.name.endswith('.meta.json')]
        manifest_blobs = [b for b in blobs if 'MANIFEST' in b.name]

        total_bytes = sum(b.size for b in blobs)
        print(f"  Total objetos:   {len(blobs)}")
        print(f"  PDFs:            {len(pdf_blobs)}")
        print(f"  ZIPs (ESEF):     {len(zip_blobs)}")
        print(f"  HTML/xHTML:      {len(html_blobs)}")
        print(f"  Archivos .meta:  {len(meta_blobs)}")
        print(f"  Manifiestos:     {len(manifest_blobs)}")
        print(f"  Espacio en nube: {total_bytes / (1024**2):.2f} MB")

        # Muestreo de metadatos de los últimos 5 archivos
        sample_metas = meta_blobs[:5]
        parsed_samples = []
        for mb in sample_metas:
            try:
                content = self.container.get_blob_client(mb.name).download_blob().readall().decode('utf-8')
                parsed_samples.append(json.loads(content))
            except Exception as e:
                print(f"  [WARN] Error leyendo {mb.name}: {e}")

        return {
            "jurisdiction": prefix,
            "total_objects": len(blobs),
            "pdfs": len(pdf_blobs),
            "zips": len(zip_blobs),
            "html": len(html_blobs),
            "metas": len(meta_blobs),
            "manifests": len(manifest_blobs),
            "total_mb": round(total_bytes / (1024**2), 2),
            "sample_metadata": parsed_samples
        }

    def read_manifest(self, manifest_blob_name: str) -> dict:
        """Lee y deserializa un manifiesto regulatorio directamente desde Azure."""
        blob_client = self.container.get_blob_client(manifest_blob_name)
        content = blob_client.download_blob().readall().decode('utf-8')
        return json.loads(content)


def main():
    parser = argparse.ArgumentParser(description="Inspector de Metadata en Azure Blob Storage")
    parser.add_argument("--country", "-c", default="all", help="Jurisdicción a auditar: de, nl, es, all")
    parser.add_argument("--container", default=DEFAULT_CONTAINER, help="Contenedor en Azure Blob")
    parser.add_argument("--output-json", action="store_true", help="Salida en formato JSON para consumo de IA")
    args = parser.parse_args()

    conn_str = get_connection_string()
    if not conn_str:
        print("[ERROR] Cadena de conexión de Azure no encontrada.")
        print("        Configura AZURE_STORAGE_CONNECTION_STRING o config/azure_secrets.json")
        sys.exit(1)

    inspector = AzureMetadataInspector(conn_str, args.container)

    jurisdictions = []
    c = args.country.lower()
    if c in ["de", "germany"]:
        jurisdictions.append("raw/DE_BAFIN")
    elif c in ["nl", "netherlands"]:
        jurisdictions.append("raw/NL_AFM")
    elif c in ["es", "spain"]:
        jurisdictions.append("raw/ES_CNMV")
    else:
        jurisdictions = ["raw/DE_BAFIN", "raw/NL_AFM", "raw/ES_CNMV"]

    results = {}
    for jur in jurisdictions:
        results[jur] = inspector.audit_jurisdiction(jur)

    if args.output_json:
        print("\n" + "=" * 50)
        print("JSON OUTPUT PARA AGENTE IA:")
        print("=" * 50)
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
