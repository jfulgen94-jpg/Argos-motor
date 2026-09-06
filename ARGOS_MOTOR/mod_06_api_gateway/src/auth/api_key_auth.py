"""API Key authentication middleware and tier permissions."""
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
import os

API_KEY_HEADER = APIKeyHeader(name="X-STATER-KEY", auto_error=False)


async def verify_api_key(api_key: str = Security(API_KEY_HEADER)) -> str:
    admin_key = os.getenv("STATER_API_KEY_ADMIN", "test-admin-key")
    if not api_key or (api_key != admin_key and not api_key.startswith("stater_")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")
    return api_key
