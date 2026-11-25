"""Single-admin authentication service, session management, rate limiting, and ASGI gate middleware."""

from __future__ import annotations

import base64
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from http.cookies import SimpleCookie
import json
import re
import secrets
import threading
import time
from typing import Any

from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import _read_config_value, get_session_ttl_days, is_auth_enabled
from app.database import SessionLocal, User, UserSession, utcnow

COOKIE_NAME = "vc_session"
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32

SETUP_LOCK = threading.Lock()
_RATE_LOCK = threading.Lock()
_FAILED_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW_SEC = 900.0
_MAX_FAILURES = 10

PUBLIC_API_PATHS = {
    "/api/health",
    "/api/auth/status",
    "/api/auth/setup",
    "/api/auth/login",
    "/api/auth/logout",
}


def normalize_username(username: str) -> str:
    cleaned = (username or "").strip().lower()
    if not _USERNAME_RE.match(cleaned):
        raise ValueError("用户名需为 3~32 位字母、数字或 . _ - 字符")
    return cleaned


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return (
        f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(dk).decode('ascii')}"
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, n_s, r_s, p_s, salt_b64, dk_b64 = stored_hash.split("$", 5)
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected_dk = base64.b64decode(dk_b64)
        actual_dk = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_s),
            r=int(r_s),
            p=int(p_s),
            dklen=len(expected_dk),
        )
        return hmac.compare_digest(actual_dk, expected_dk)
    except Exception:
        return False


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "").strip()
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first[:64]
    if request.client and request.client.host:
        return str(request.client.host)[:64]
    return "unknown"


def is_https_request(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return proto == "https"


def check_login_rate_limit(ip: str) -> None:
    now = time.monotonic()
    with _RATE_LOCK:
        recent = [ts for ts in _FAILED_ATTEMPTS[ip] if now - ts < _RATE_WINDOW_SEC]
        _FAILED_ATTEMPTS[ip] = recent
        if len(recent) >= _MAX_FAILURES:
            raise HTTPException(
                status_code=429,
                detail="登录失败次数过多，请 15 分钟后再试",
            )


def record_login_failure(ip: str) -> None:
    now = time.monotonic()
    with _RATE_LOCK:
        recent = [ts for ts in _FAILED_ATTEMPTS[ip] if now - ts < _RATE_WINDOW_SEC]
        recent.append(now)
        _FAILED_ATTEMPTS[ip] = recent


def clear_login_failures(ip: str) -> None:
    with _RATE_LOCK:
        _FAILED_ATTEMPTS.pop(ip, None)


def reset_rate_limiter() -> None:
    """Test helper to clear all tracked login failure counters."""
    with _RATE_LOCK:
        _FAILED_ATTEMPTS.clear()


def _to_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def create_session(
    db: Session,
    user: User,
    *,
    remember: bool = True,
    user_agent: str = "",
    ip_address: str = "",
) -> tuple[str, int]:
    now = utcnow()
    db.query(UserSession).filter(UserSession.expires_at <= now).delete(synchronize_session=False)

    ttl_days = get_session_ttl_days() if remember else 1
    max_age = ttl_days * 86400
    raw_token = secrets.token_urlsafe(32)
    sess = UserSession(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        user_agent=(user_agent or "")[:300],
        ip_address=(ip_address or "")[:64],
        expires_at=now + timedelta(seconds=max_age),
    )
    db.add(sess)
    db.commit()
    return raw_token, max_age


def set_session_cookie(response: Response, request: Request, raw_token: str, max_age: int) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=raw_token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=is_https_request(request),
        path="/",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=is_https_request(request),
        path="/",
    )


def validate_session_token(raw_token: str | None) -> dict[str, str] | None:
    if not raw_token:
        return None
    token_hash = hash_token(raw_token)
    db = SessionLocal()
    try:
        row = (
            db.query(UserSession, User)
            .join(User, UserSession.user_id == User.id)
            .filter(UserSession.token_hash == token_hash)
            .first()
        )
        if not row:
            return None
        sess, user = row
        if _to_utc(sess.expires_at) <= utcnow():
            db.delete(sess)
            db.commit()
            return None
        return {
            "user_id": user.id,
            "username": user.username,
            "role": user.role,
            "session_id": sess.id,
        }
    finally:
        db.close()


def ensure_env_admin_if_configured() -> None:
    """Optionally bootstrap initial admin from ADMIN_USERNAME / ADMIN_PASSWORD when DB has no users."""
    raw_user = _read_config_value("ADMIN_USERNAME", "")
    raw_pass = _read_config_value("ADMIN_PASSWORD", "")
    if not raw_user or not raw_pass or len(raw_pass) < 8:
        return
    try:
        username = normalize_username(raw_user)
    except ValueError:
        return

    with SETUP_LOCK:
        db = SessionLocal()
        try:
            if db.query(User).count() > 0:
                return
            admin = User(
                username=username,
                password_hash=hash_password(raw_pass),
                role="admin",
            )
            db.add(admin)
            db.commit()
        finally:
            db.close()


def _extract_cookie_from_headers(headers: list[tuple[bytes, bytes]], name: str) -> str | None:
    for k, v in headers:
        if k.lower() == b"cookie":
            cookie = SimpleCookie()
            try:
                cookie.load(v.decode("latin-1"))
            except Exception:
                continue
            morsel = cookie.get(name)
            if morsel:
                return morsel.value
    return None


def _is_protected_path(path: str) -> bool:
    if path in PUBLIC_API_PATHS:
        return False
    if path == "/api" or path.startswith("/api/"):
        return True
    if path == "/media" or path.startswith("/media/"):
        return True
    if path in ("/docs", "/redoc", "/openapi.json"):
        return True
    return False


class AuthGateMiddleware:
    """Pure ASGI gate enforcing session authentication without buffering SSE responses."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        if not is_auth_enabled():
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not _is_protected_path(path):
            await self.app(scope, receive, send)
            return

        raw_token = _extract_cookie_from_headers(scope.get("headers") or [], COOKIE_NAME)
        if validate_session_token(raw_token):
            await self.app(scope, receive, send)
            return

        body = json.dumps({"detail": "请先登录后再使用"}, ensure_ascii=False).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"cache-control", b"no-store"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
