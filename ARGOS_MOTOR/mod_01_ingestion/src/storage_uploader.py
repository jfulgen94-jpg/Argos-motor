"""Sync local raw filings to Azure Blob Storage using Microsoft Founders Hub credits."""
import os
from pathlib import Path
from typing import Optional


class StorageUploader:
    def __init__(self, connection_string: Optional[str] = None, container_name: str = "stater-raw-filings"):
        self.conn_str = connection_string or os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        self.container = container_name

    def upload_file(self, local_path: Path, blob_name: str) -> bool:
        if not self.conn_str:
            return False  # In local dev mode without azure credentials
        try:
            from azure.storage.blob import BlobServiceClient
            service = BlobServiceClient.from_connection_string(self.conn_str)
            blob_client = service.get_blob_client(container=self.container, blob=blob_name)
            with open(local_path, "rb") as data:
                blob_client.upload_blob(data, overwrite=True)
            return True
        except Exception:
            return False
