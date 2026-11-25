"""Authentication endpoints for single-admin setup, login, logout, and password rotation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import is_auth_enabled
from app.database import User, UserSession, get_db, utcnow
from app.schemas import AuthLoginRequest, AuthSetupRequest, AuthStatusOut, ChangePasswordRequest
from app.services.auth import (
    COOKIE_NAME,
    SETUP_LOCK,
    check_login_rate_limit,
    clear_login_failures,
    clear_session_cookie,
    create_session,
    get_client_ip,
    hash_password,
    normalize_username,
    record_login_failure,
    set_session_cookie,
    validate_session_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatusOut)
def get_auth_status(request: Request, db: Session = Depends(get_db)):
    enabled = is_auth_enabled()
    initialized = db.query(User.id).count() > 0
    if not enabled:
        return AuthStatusOut(
            auth_enabled=False,
            initialized=initialized,
            authenticated=True,
            username="local",
            role="admin",
        )

    session_info = validate_session_token(request.cookies.get(COOKIE_NAME))
    if not session_info:
        return AuthStatusOut(
            auth_enabled=True,
            initialized=initialized,
            authenticated=False,
        )
    return AuthStatusOut(
        auth_enabled=True,
        initialized=initialized,
        authenticated=True,
        username=session_info["username"],
        role=session_info["role"],
    )


@router.post("/setup", response_model=AuthStatusOut)
def setup_admin(
    payload: AuthSetupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        username = normalize_username(payload.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    with SETUP_LOCK:
        if db.query(User.id).count() > 0:
            raise HTTPException(status_code=403, detail="管理员账号已初始化，禁止重复注册")

        admin = User(
            username=username,
            password_hash=hash_password(payload.password),
            role="admin",
            last_login_at=utcnow(),
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)

        raw_token, max_age = create_session(
            db,
            admin,
            remember=True,
            user_agent=request.headers.get("user-agent", ""),
            ip_address=get_client_ip(request),
        )
        set_session_cookie(response, request, raw_token, max_age)

    return AuthStatusOut(
        auth_enabled=is_auth_enabled(),
        initialized=True,
        authenticated=True,
        username=admin.username,
        role=admin.role,
    )


@router.post("/login", response_model=AuthStatusOut)
def login(
    payload: AuthLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    ip = get_client_ip(request)
    check_login_rate_limit(ip)

    if db.query(User.id).count() == 0:
        raise HTTPException(status_code=400, detail="尚未创建管理员账号，请先完成首次设置")

    try:
        username = normalize_username(payload.username)
    except ValueError:
        record_login_failure(ip)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        record_login_failure(ip)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    clear_login_failures(ip)
    user.last_login_at = utcnow()
    db.commit()

    raw_token, max_age = create_session(
        db,
        user,
        remember=payload.remember,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=ip,
    )
    set_session_cookie(response, request, raw_token, max_age)

    return AuthStatusOut(
        auth_enabled=is_auth_enabled(),
        initialized=True,
        authenticated=True,
        username=user.username,
        role=user.role,
    )


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw_token = request.cookies.get(COOKIE_NAME)
    if raw_token:
        from app.services.auth import hash_token

        db.query(UserSession).filter(UserSession.token_hash == hash_token(raw_token)).delete(
            synchronize_session=False
        )
        db.commit()
    clear_session_cookie(response, request)
    return {"ok": True}


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    session_info = validate_session_token(request.cookies.get(COOKIE_NAME))
    if not session_info:
        raise HTTPException(status_code=401, detail="请先登录后再使用")

    user = db.get(User, session_info["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="账号不存在")

    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确")

    user.password_hash = hash_password(payload.new_password)
    db.query(UserSession).filter(UserSession.user_id == user.id).delete(synchronize_session=False)
    db.commit()

    raw_token, max_age = create_session(
        db,
        user,
        remember=True,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=get_client_ip(request),
    )
    set_session_cookie(response, request, raw_token, max_age)
    return {"ok": True}
