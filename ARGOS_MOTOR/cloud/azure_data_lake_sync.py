#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
STATER / ARGOS DATA LAKE - AZURE BLOB STORAGE SYNCHRONIZER
================================================================================
Sincronizador institucional de alta concurrencia entre el almacenamiento local
(D:\\ARGOS_DATA\\raw) y Microsoft Azure Blob Storage (Data Lake Gen2).

Características:
  - Idempotente: Omite automáticamente blobs ya subidos con tamaño idéntico.
  - Multi-hilo (ThreadPoolExecutor) con transferencia por bloques (BlockBlob).
  - Conserva exactamente la jerarquía canónica (raw/ES_CNMV/..., raw/DE_BAFIN/...).
  - Inyección de metadatos SHA-256 en cabeceras de Azure Blob.
================================================================================
"""

import os
import sys
import json
import time
import hashlib
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from azure.storage.blob import BlobServiceClient, ContentSettings

# Configuración por defecto
DEFAULT_SECRETS_PATH = Path(__file__).resolve().parent.parent / "config" / "azure_secrets.json"
DEFAULT_SOURCE_DIR = Path("D:/ARGOS_DATA/raw")
DEFAULT_CONTAINER = "fulgen"
DEFAULT_WORKERS = 8

def calculate_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(1048576):
            h.update(chunk)
    return h.hexdigest()

def get_content_type(suffix: str) -> str:
    s = suffix.lower()
    if s == '.pdf': return 'application/pdf'
    if s == '.zip': return 'application/zip'
    if s == '.json': return 'application/json'
    if s in ['.htm', '.html']: return 'text/html'
    if s == '.xhtml': return 'application/xhtml+xml'
    if s == '.xsd': return 'text/xml'
    return 'application/octet-stream'

class AzureDataLakeSynchronizer:
    def __init__(self, conn_str: str, container_name: str = DEFAULT_CONTAINER, max_workers: int = DEFAULT_WORKERS):
        self.blob_service_client = BlobServiceClient.from_connection_string(conn_str)
        self.container_name = container_name
        self.max_workers = max_workers
        self.container_client = self.blob_service_client.get_container_client(container_name)
        
        # Asegurar contenedor existente
        try:
            if not self.container_client.exists():
                self.container_client.create_container()
                print(f"[AZURE] Contenedor '{container_name}' creado con éxito.")
            else:
                print(f"[AZURE] Conectado al contenedor existente: '{container_name}'.")
        except Exception as e:
            print(f"[AZURE] Aviso al verificar contenedor: {e}")

    def get_remote_blobs_map(self, prefix: str = "raw/") -> dict:
        """Obtiene un mapa {blob_name: size} de los blobs existentes en el contenedor"""
        print(f"[AZURE] Obteniendo inventario de blobs remotos bajo '{prefix}'...")
        remote_map = {}
        try:
            blobs = self.container_client.list_blobs(name_starts_with=prefix)
            for b in blobs:
                remote_map[b.name] = b.size
            print(f"[AZURE] Blobs remotos existentes encontrados: {len(remote_map)}")
        except Exception as e:
            print(f"[AZURE] Error listando blobs: {e}")
        return remote_map

    def upload_single_file(self, local_path: Path, relative_blob_name: str, remote_size: int, dry_run: bool = False):
        """Sube un archivo individual si no existe o difiere en tamaño"""
        local_size = local_path.stat().st_size
        
        # Comprobar si ya existe con el mismo tamaño (Caché hit)
        if remote_size is not None and remote_size == local_size:
            return {"status": "skipped_exists", "file": local_path.name, "size": local_size, "blob": relative_blob_name}

        if dry_run:
            return {"status": "dry_run_upload", "file": local_path.name, "size": local_size, "blob": relative_blob_name}

        blob_client = self.container_client.get_blob_client(relative_blob_name)
        content_type = get_content_type(local_path.suffix)
        content_settings = ContentSettings(content_type=content_type)
        
        # Intentar leer sha256 del archivo .meta.json acompañante si existe
        sha = ""
        meta_companion = local_path.with_suffix(local_path.suffix + '.meta.json')
        if meta_companion.exists():
            try:
                m_data = json.loads(meta_companion.read_text(encoding='utf-8'))
                sha = m_data.get('sha256', '')
            except Exception:
                pass

        metadata = {"stater_managed": "true"}
        if sha:
            metadata["sha256"] = sha

        for attempt in range(3):
            try:
                with open(local_path, "rb") as data:
                    blob_client.upload_blob(
                        data,
                        overwrite=True,
                        content_settings=content_settings,
                        metadata=metadata,
                        max_concurrency=4
                    )
                return {"status": "uploaded", "file": local_path.name, "size": local_size, "blob": relative_blob_name}
            except Exception as e:
                if attempt == 2:
                    return {"status": "error", "file": local_path.name, "size": local_size, "blob": relative_blob_name, "error": str(e)}
                time.sleep(1.5 * (attempt + 1))

    def sync(self, source_dir: Path, subfolder: str = None, year_filter: list = None, dry_run: bool = False):
        if not source_dir.exists():
            print(f"[ERROR] Directorio origen local no encontrado: {source_dir}")
            return

        print("\n=========================================================================")
        print("=== INICIANDO SINCRONIZACIÓN DATA LAKE LOCAL -> MICROSOFT AZURE BLOB ===")
        print("=========================================================================")
        print(f"Directorio Origen Local:  {source_dir}")
        print(f"Contenedor Destino Azure: {self.container_name}")
        print(f"Filtro Subcarpeta:        {subfolder or 'TODAS (ES_CNMV + DE_BAFIN)'}")
        print(f"Filtro Años:              {year_filter or 'TODOS (2012-2025)'}")
        print(f"Hilos Concurrentes:       {self.max_workers}")
        print(f"Modo Dry-Run:             {dry_run}")
        print("=========================================================================\n")

        # 1. Escaneo de archivos locales
        all_local_files = []
        for root, _, files in os.walk(source_dir):
            root_p = Path(root)
            for f in files:
                f_p = root_p / f
                if f_p.is_file():
                    rel = f_p.relative_to(source_dir).as_posix()
                    # Aplicar filtros si existen
                    if subfolder and not rel.startswith(subfolder):
                        continue
                    if year_filter:
                        parts = rel.split('/')
                        if len(parts) > 1 and parts[1] not in year_filter:
                            continue
                    all_local_files.append((f_p, f"raw/{rel}"))

        total_files = len(all_local_files)
        total_bytes = sum(f[0].stat().st_size for f in all_local_files)
        total_gb = total_bytes / (1024**3)
        print(f"[LOCAL] Archivos seleccionados para sincronizar: {total_files} ({total_gb:.2f} GB)")

        if total_files == 0:
            print("[INFO] No se encontraron archivos para subir con los filtros especificados.")
            return

        # 2. Obtener mapa remoto existente
        prefix = f"raw/{subfolder}" if subfolder else "raw/"
        remote_blobs = self.get_remote_blobs_map(prefix=prefix)

        # 3. Separar archivos ligeros (manifiestos .json) de archivos pesados (.pdf, .zip)
        json_files = [(lp, rb) for lp, rb in all_local_files if lp.suffix.lower() == '.json']
        binary_files = [(lp, rb) for lp, rb in all_local_files if lp.suffix.lower() != '.json']
        
        # Orden de subida: manifiestos primero para establecer índices
        sorted_files = json_files + binary_files

        # 4. Ejecución multi-hilo
        uploaded_count = 0
        skipped_count = 0
        error_count = 0
        uploaded_bytes = 0
        start_time = time.time()

        print(f"\n[SUBIDA] Comenzando transferencia paralela ({self.max_workers} workers)...")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_file = {
                executor.submit(
                    self.upload_single_file,
                    local_path,
                    blob_name,
                    remote_blobs.get(blob_name),
                    dry_run
                ): (local_path, blob_name)
                for local_path, blob_name in sorted_files
            }

            processed = 0
            for future in as_completed(future_to_file):
                processed += 1
                res = future.result()
                status = res['status']
                size = res['size']
                fname = res['file']

                if status == 'uploaded':
                    uploaded_count += 1
                    uploaded_bytes += size
                elif status == 'skipped_exists':
                    skipped_count += 1
                elif status == 'dry_run_upload':
                    uploaded_count += 1
                    uploaded_bytes += size
                elif status == 'error':
                    error_count += 1
                    print(f"\n[ERROR] Error subiendo {fname}: {res.get('error')}")

                if processed % 50 == 0 or processed == total_files:
                    elapsed = max(time.time() - start_time, 0.1)
                    speed_mb = (uploaded_bytes / (1024**2)) / elapsed
                    pct = (processed / total_files) * 100
                    print(f"[{processed:>5}/{total_files}] ({pct:>5.1f}%) | "
                          f"Nuevos Subidos: {uploaded_count:<5} | "
                          f"Ya en Azure: {skipped_count:<5} | "
                          f"Fallos: {error_count:<3} | "
                          f"Velocidad: {speed_mb:.1f} MB/s", end='\r')

        total_elapsed = time.time() - start_time
        print("\n\n=========================================================================")
        print("=== RESUMEN GLOBAL DE SINCRONIZACIÓN CON AZURE DATA LAKE ===")
        print("=========================================================================")
        print(f" • Total Archivos Evaluados: {total_files}")
        print(f" • Nuevos Blobs Subidos:     {uploaded_count} ({(uploaded_bytes / (1024**3)):.2f} GB)")
        print(f" • Ya Existentes (Caché Hit):{skipped_count}")
        print(f" • Errores de Transferencia: {error_count}")
        print(f" • Tiempo Total Empleado:    {total_elapsed:.1f} s")
        print("=========================================================================\n")


def load_secrets():
    if DEFAULT_SECRETS_PATH.exists():
        try:
            return json.loads(DEFAULT_SECRETS_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="STATER / ARGOS Azure Blob Synchronizer")
    parser.add_argument("--source-dir", type=str, default=str(DEFAULT_SOURCE_DIR), help="Directorio raíz local")
    parser.add_argument("--container", type=str, default=None, help="Nombre del contenedor en Azure (por defecto 'fulgen')")
    parser.add_argument("--conn-str", type=str, default=None, help="Cadena de conexión de Azure Storage")
    parser.add_argument("--subfolder", type=str, default=None, help="Subcarpeta a sincronizar (ej: ES_CNMV o DE_BAFIN)")
    parser.add_argument("--years", type=str, default=None, help="Años a sincronizar separados por coma (ej: 2024,2025)")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_WORKERS, help="Hilos paralelos de subida")
    parser.add_argument("--dry-run", action="store_true", help="Simulación sin realizar subidas")

    args = parser.parse_args()

    secrets = load_secrets()
    conn_str = args.conn_str or secrets.get("connection_string") or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        print("[ERROR] No se especificó --conn-str ni se encontró en azure_secrets.json ni en variable de entorno.")
        sys.exit(1)

    container = args.container or secrets.get("default_container") or DEFAULT_CONTAINER
    years = [y.strip() for y in args.years.split(',')] if args.years else None

    sync_tool = AzureDataLakeSynchronizer(conn_str=conn_str, container_name=container, max_workers=args.max_workers)
    sync_tool.sync(
        source_dir=Path(args.source_dir),
        subfolder=args.subfolder,
        year_filter=years,
        dry_run=args.dry_run
    )
