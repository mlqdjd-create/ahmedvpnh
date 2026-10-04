import os
import json
import time
import hmac
import hashlib
import base64
import threading
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Load environment variables
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

# SECURITY: no hard-coded fallback secret. If it is not set in .env the
# admin-only endpoints refuse to work instead of accepting a known key.
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()

# SECURITY: shared secret used to verify that requests come from our app.
# Must match the obfuscated key inside the Android app (ApiSigner).
# If empty, the app-facing endpoints refuse to work.
APP_SIGNING_SECRET = os.getenv("APP_SIGNING_SECRET", "").strip()

# اسم المستخدم وكلمة السر لحماية الرابط (HTTP Basic) — يظهران كطلب دخول في المتصفح.
# يجب أن يطابقا القيمتين المُعتّمتين داخل التطبيق (ApiSigner).
APP_API_USER = os.getenv("APP_API_USER", "").strip()
APP_API_PASS = os.getenv("APP_API_PASS", "").strip()

_NONCE_LOCK = threading.Lock()
_SEEN_NONCES = {}  # nonce -> epoch seconds (replay protection)
_NONCE_TTL = 300
_MAX_SKEW = 300    # allowed clock skew in seconds

# ---- حماية من الإساءة (Rate limiting + auto-ban) ----
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "90") or "90")
RATE_BAN_MINUTES = int(os.getenv("RATE_BAN_MINUTES", "10") or "10")
# قائمة بيضاء لبصمات توقيع التطبيق (SHA-256 مفصولة بفواصل) — اختيارية.
# إن ضُبطت، تُرفض أي بصمة غير موجودة (يقتل النسخ المُعاد تغليفها).
CERT_ALLOWLIST = [x.strip().lower() for x in os.getenv("CERT_ALLOWLIST", "").split(",") if x.strip()]
TRUST_PROXY = (os.getenv("TRUST_PROXY", "0").strip().lower() in ("1", "true", "yes"))

_RL_LOCK = threading.Lock()
_RL_HITS = {}   # ip -> [epoch, ...]
_RL_BAN = {}    # ip -> ban_until_epoch


def _client_ip(request: Request) -> str:
    # Cloudflare يضبط CF-Connecting-IP (لا يمكن تزييفه من العميل) — نفضّله.
    if TRUST_PROXY:
        cf = request.headers.get("CF-Connecting-IP")
        if cf and cf.strip():
            return cf.strip()
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(request: Request):
    ip = _client_ip(request)
    now = time.time()
    with _RL_LOCK:
        until = _RL_BAN.get(ip, 0)
        if until > now:
            raise HTTPException(status_code=429, detail="Banned: too many requests")
        hits = [t for t in _RL_HITS.get(ip, []) if now - t < 60]
        hits.append(now)
        _RL_HITS[ip] = hits
        if len(hits) > RATE_LIMIT_PER_MIN:
            _RL_BAN[ip] = now + RATE_BAN_MINUTES * 60
            raise HTTPException(status_code=429, detail="Rate limit exceeded — temporarily banned")

import database

app = FastAPI(
    title="AHMED VPN Server API",
    description="REST API for AHMED VPN Android client and server management",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# CORS middleware for mobile & external connections.
# NOTE: allow_origins=["*"] cannot be combined with allow_credentials=True
# (browsers reject it), so credentials are disabled here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ServerCreate(BaseModel):
    name: str
    protocol: str
    config: str
    country: Optional[str] = ""
    proxy_host: Optional[str] = ""
    proxy_port: Optional[int] = 0
    proxy_user: Optional[str] = ""
    proxy_pass: Optional[str] = ""
    payload: Optional[str] = ""


class ServerAdvanced(BaseModel):
    country: Optional[str] = ""
    proxy_host: Optional[str] = ""
    proxy_port: Optional[int] = 0
    proxy_user: Optional[str] = ""
    proxy_pass: Optional[str] = ""
    payload: Optional[str] = ""


class PingBody(BaseModel):
    user_id: str
    app_version: Optional[str] = ""


class ActivityBody(BaseModel):
    user_id: str
    server: Optional[str] = ""
    event: Optional[str] = ""


class AnnouncementBody(BaseModel):
    message: str


class AppUpdateBody(BaseModel):
    enabled: bool = False
    version_code: int = 0
    url: str = ""
    message: str = ""


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

    if not ADMIN_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Server misconfigured: ADMIN_API_KEY is not set in .env"
        )
    if not key or key != ADMIN_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Valid ADMIN_API_KEY is required for this operation."
        )
    return True


def verify_basic(request: Request):
    """HTTP Basic — يجعل المتصفح يطلب اسم مستخدم وكلمة سر عند فتح الرابط."""
    if not APP_API_USER or not APP_API_PASS:
        raise HTTPException(status_code=503, detail="Server misconfigured: APP_API_USER/APP_API_PASS not set in .env")
    auth = request.headers.get("Authorization") or ""
    challenge = {"WWW-Authenticate": 'Basic realm="Iraq Tunnel API"'}
    if not auth.lower().startswith("basic "):
        raise HTTPException(status_code=401, detail="Authentication required", headers=challenge)
    try:
        raw = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
    except Exception:
        raise HTTPException(status_code=401, detail="Bad credentials", headers=challenge)
    if ":" not in raw:
        raise HTTPException(status_code=401, detail="Bad credentials", headers=challenge)
    u, p = raw.split(":", 1)
    if not (hmac.compare_digest(u, APP_API_USER) and hmac.compare_digest(p, APP_API_PASS)):
        raise HTTPException(status_code=401, detail="Invalid credentials", headers=challenge)
    return True


def verify_app_signature(request: Request):
    """يتحقّق من: حد المعدّل + HTTP Basic + توقيع HMAC-SHA256 + بصمة توقيع التطبيق."""
    _enforce_rate_limit(request)
    verify_basic(request)
    if not APP_SIGNING_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Server misconfigured: APP_SIGNING_SECRET is not set in .env"
        )
    ts = request.headers.get("X-IQ-Ts")
    nonce = request.headers.get("X-IQ-Nonce")
    sig = request.headers.get("X-IQ-Sig")
    if not ts or not nonce or not sig:
        raise HTTPException(status_code=401, detail="Missing signature headers")
    try:
        tsi = int(ts)
    except ValueError:
        raise HTTPException(status_code=401, detail="Bad timestamp")
    now = int(time.time())
    if abs(now - tsi) > _MAX_SKEW:
        raise HTTPException(status_code=401, detail="Stale request")
    with _NONCE_LOCK:
        for k in [k for k, v in list(_SEEN_NONCES.items()) if now - v > _NONCE_TTL]:
            _SEEN_NONCES.pop(k, None)
        if nonce in _SEEN_NONCES:
            raise HTTPException(status_code=401, detail="Replay detected")
        _SEEN_NONCES[nonce] = now
    msg = f"{ts}\n{nonce}\n{request.url.path}"
    expect = hmac.new(APP_SIGNING_SECRET.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        raise HTTPException(status_code=401, detail="Invalid signature")
    if CERT_ALLOWLIST:
        cert = (request.headers.get("X-IQ-Cert") or "").strip().lower()
        if cert not in CERT_ALLOWLIST:
            raise HTTPException(status_code=401, detail="Unknown app certificate")
    return True


@app.get("/", dependencies=[Depends(verify_basic)])
def root():
    return {
        "app": "AHMED VPN",
        "status": "online",
        "docs": "/docs"
    }


@app.get("/healthz")
def healthz():
    """نقطة فحص مفتوحة لـRailway (بدون مصادقة) — اجعل مسار الفحص في Railway = /healthz."""
    return {"status": "ok"}


@app.get("/api/health", dependencies=[Depends(verify_basic)])
def health():
    return {
        "status": "healthy",
        "app": "AHMED VPN",
        "servers_count": database.get_servers_count(),
        "users_count": database.get_users_count(),
    }


# ============================ SERVERS ============================

@app.get("/api/servers", dependencies=[Depends(verify_app_signature)])
def get_servers():
    """Servers list in the exact format expected by the Android app.
    Includes the per-server proxy/payload/country fields (the app applies them
    only for servers that have them, and connects directly otherwise)."""
    servers = database.get_all_servers()
    result = []
    for s in servers:
        item = {
            "id": s["id"],
            "name": s["name"],
            "protocol": s["protocol"],
            "config": s["config"],
        }
        if s.get("country"):
            item["country"] = s["country"]
        if s.get("proxy_host") and s.get("proxy_port"):
            item["proxy_host"] = s["proxy_host"]
            item["proxy_port"] = str(s["proxy_port"])
            if s.get("proxy_user"):
                item["proxy_user"] = s["proxy_user"]
            if s.get("proxy_pass"):
                item["proxy_pass"] = s["proxy_pass"]
        if s.get("payload"):
            item["payload"] = s["payload"]
        result.append(item)
    return {"servers": result}


@app.get("/api/servers/{server_id}", dependencies=[Depends(verify_app_signature)])
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
        config=data.config,
        country=data.country or "",
        proxy_host=data.proxy_host or "",
        proxy_port=data.proxy_port or 0,
        proxy_user=data.proxy_user or "",
        proxy_pass=data.proxy_pass or "",
        payload=data.payload or "",
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


@app.put("/api/servers/{server_id}/advanced", dependencies=[Depends(verify_admin_key)])
def set_server_advanced(server_id: int, data: ServerAdvanced):
    """Set the per-server proxy / payload / country (used by the bot)."""
    ok = database.update_server_advanced(
        server_id,
        country=data.country or "",
        proxy_host=data.proxy_host or "",
        proxy_port=data.proxy_port or 0,
        proxy_user=data.proxy_user or "",
        proxy_pass=data.proxy_pass or "",
        payload=data.payload or "",
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Server not found")
    return {"status": "success"}


# ============================ APP TELEMETRY ============================
# These endpoints are called by the Android app (base URL = .../api).

@app.post("/api/user/ping", dependencies=[Depends(verify_app_signature)])
def user_ping(data: PingBody):
    """Installation ping — the app calls this silently on start."""
    database.upsert_user(data.user_id, data.app_version or "")
    return {"status": "ok"}


@app.post("/api/user/activity", dependencies=[Depends(verify_app_signature)])
def user_activity(data: ActivityBody):
    """Connect/disconnect events — keeps per-server live user counts."""
    database.upsert_user(data.user_id)
    database.log_activity(data.user_id, data.server or "", data.event or "")
    return {"status": "ok"}


@app.get("/api/stats", dependencies=[Depends(verify_app_signature)])
def stats():
    """Live users per server, consumed by the app's server list."""
    return {
        "per_server": database.get_per_server_counts(),
        "users_count": database.get_users_count(),
        "servers_count": database.get_servers_count(),
    }


# ============================ ANNOUNCEMENTS ============================

@app.get("/api/notifications", dependencies=[Depends(verify_app_signature)])
def get_notification():
    """Latest announcement — the app polls this and shows a notification."""
    ann = database.get_latest_announcement()
    if not ann:
        return {"id": 0, "message": ""}
    return {"id": ann["id"], "message": ann["message"]}


@app.post("/api/notifications", dependencies=[Depends(verify_admin_key)])
def set_notification(data: AnnouncementBody):
    if not data.message.strip():
        raise HTTPException(status_code=400, detail="message is required")
    new_id = database.add_announcement(data.message)
    return {"status": "success", "id": new_id}


# ============================ APP UPDATE ============================

@app.get("/api/app-update", dependencies=[Depends(verify_app_signature)])
def get_app_update():
    """Forced-update info — the app compares version_code with its own."""
    raw = database.get_setting("app_update")
    if not raw:
        return {"enabled": False, "version_code": 0, "url": "", "message": ""}
    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    return {
        "enabled": bool(data.get("enabled", False)),
        "version_code": int(data.get("version_code", 0)),
        "url": data.get("url", ""),
        "message": data.get("message", ""),
    }


@app.post("/api/app-update", dependencies=[Depends(verify_admin_key)])
def set_app_update(data: AppUpdateBody):
    database.set_setting("app_update", json.dumps({
        "enabled": data.enabled,
        "version_code": data.version_code,
        "url": data.url,
        "message": data.message,
    }))
    return {"status": "success"}


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("api:app", host=host, port=port, reload=True)
