import os
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Load environment variables
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "ahmed_vpn_admin_secret_key_2026")

import database

app = FastAPI(
    title="AHMED VPN Server API",
    description="REST API for AHMED VPN Android client and server management",
    version="1.0.0"
)

# CORS middleware for mobile & external connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ServerCreate(BaseModel):
    name: str
    protocol: str
    config: str

def verify_admin_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None)
):
    key = x_api_key
    if not key and authorization:
        if authorization.startswith("Bearer "):
            key = authorization[7:].strip()
        else:
            key = authorization.strip()

    if not key or key != ADMIN_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Valid ADMIN_API_KEY is required for this operation."
        )
    return True

@app.get("/")
def root():
    return {
        "app": "AHMED VPN",
        "status": "online",
        "docs": "/docs"
    }

@app.get("/api/health")
def health():
    count = database.get_servers_count()
    return {
        "status": "healthy",
        "app": "AHMED VPN",
        "servers_count": count
    }

@app.get("/api/servers")
def get_servers():
    """
    Returns servers list in exact format expected by AHMED VPN Android app.
    """
    servers = database.get_all_servers()
    result = []
    for s in servers:
        result.append({
            "id": s["id"],
            "name": s["name"],
            "protocol": s["protocol"],
            "config": s["config"]
        })
    return {"servers": result}

@app.get("/api/servers/{server_id}")
def get_single_server(server_id: int):
    server = database.get_server_by_id(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    return {
        "id": server["id"],
        "name": server["name"],
        "protocol": server["protocol"],
        "config": server["config"],
        "created_at": server["created_at"]
    }

@app.post("/api/servers", dependencies=[Depends(verify_admin_key)])
def create_server(data: ServerCreate):
    valid_protocols = ["VLESS", "VMESS", "TROJAN"]
    proto = data.protocol.upper().strip()
    if proto not in valid_protocols:
        raise HTTPException(status_code=400, detail=f"Invalid protocol. Must be one of: {valid_protocols}")

    server_id = database.add_server(
        name=data.name,
        protocol=proto,
        config=data.config
    )
    return {
        "status": "success",
        "message": "Server added successfully",
        "id": server_id
    }

@app.delete("/api/servers/{server_id}", dependencies=[Depends(verify_admin_key)])
def delete_server_endpoint(server_id: int):
    success = database.delete_server(server_id)
    if not success:
        raise HTTPException(status_code=404, detail="Server not found")
    return {
        "status": "success",
        "message": f"Server {server_id} deleted successfully"
    }

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("api:app", host=host, port=port, reload=True)
