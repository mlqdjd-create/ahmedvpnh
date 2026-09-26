from typing import Optional
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
import database

app = FastAPI(
    title=f"{config.APP_NAME} Server API",
    description="REST API for AHMED VPN Android client, administration and server management",
    version=config.VERSION
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
    # ميزات اختيارية لكل سيرفر: الدولة + البايلود + البروكسي
    country: str = ""
    payload: str = ""
    proxy_host: str = ""
    proxy_port: str = ""
    proxy_user: str = ""
    proxy_pass: str = ""

class UserPing(BaseModel):
    user_id: str
    app_version: Optional[str] = "1.0"

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

    if not key or key != config.ADMIN_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Valid ADMIN_API_KEY is required for this operation."
        )
    return True

@app.get("/")
def root():
    return {
        "app": config.APP_NAME,
        "version": config.VERSION,
        "status": "online",
        "docs": "/docs"
    }

@app.get("/api/health")
def health():
    stats = database.get_system_stats()
    return {
        "status": "healthy",
        "app": config.APP_NAME,
        "stats": stats
    }

@app.get("/api/stats")
def stats():
    return database.get_system_stats()

@app.post("/api/user/ping")
def ping_user(data: UserPing, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
        
    success = database.register_or_update_user(
        user_id=data.user_id,
        client_ip=client_ip,
        app_version=data.app_version or "1.0"
    )
    return {
        "status": "success" if success else "error",
        "registered": success,
        "total_users": database.get_users_count()
    }

def _server_payload(s, with_timestamp: bool = False):
    """صيغة السيرفر كما يتوقعها تطبيق الأندرويد — تتضمن الدولة والبايلود والبروكسي."""
    out = {
        "id": s["id"],
        "name": s["name"],
        "protocol": s["protocol"],
        "config": s["config"],
        "country": s.get("country", ""),
        "payload": s.get("payload", ""),
        "proxy_host": s.get("proxy_host", ""),
        "proxy_port": s.get("proxy_port", ""),
        "proxy_user": s.get("proxy_user", ""),
        "proxy_pass": s.get("proxy_pass", ""),
    }
    if with_timestamp:
        out["created_at"] = s["created_at"]
    return out


@app.get("/api/servers")
def get_servers():
    """
    Returns servers list in exact format expected by AHMED VPN Android app
    (includes optional per-server country, payload and proxy).
    """
    servers = database.get_all_servers()
    result = [_server_payload(s) for s in servers]
    return {"servers": result}


@app.get("/api/servers/{server_id}")
def get_single_server(server_id: int):
    server = database.get_server_by_id(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    return _server_payload(server, with_timestamp=True)


@app.post("/api/servers", dependencies=[Depends(verify_admin_key)])
def create_server(data: ServerCreate):
    valid_protocols = ["VLESS", "VMESS", "TROJAN"]
    proto = data.protocol.upper().strip()
    if proto not in valid_protocols:
        raise HTTPException(status_code=400, detail=f"Invalid protocol. Must be one of: {valid_protocols}")

    server_id = database.add_server(
        name=data.name,
        protocol=proto,
        config=data.config,
        country=data.country,
        payload=data.payload,
        proxy_host=data.proxy_host,
        proxy_port=data.proxy_port,
        proxy_user=data.proxy_user,
        proxy_pass=data.proxy_pass,
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
    uvicorn.run("api:app", host=config.HOST, port=config.PORT, reload=True)
