"""
登录 API 路由

新登录接口（推荐）：POST /auth/login
- 验证 Turnstile CAPTCHA
- 检查登录失败计数/锁定
- 调用 Supabase Auth
- 记录登录日志

旧登录接口（废弃过渡）：POST /auth/login/supabase
"""

import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from agno.utils.log import logger

load_dotenv()

router = APIRouter(prefix="/auth", tags=["Authentication"])

# === 配置 ===

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
CAPTCHA_ENABLED = os.getenv("CAPTCHA_ENABLED", "true").lower() == "true"
LOGIN_SECURITY_ENABLED = os.getenv("LOGIN_SECURITY_ENABLED", "true").lower() == "true"


# === 请求/响应模型 ===

class LoginRequest(BaseModel):
    email: str
    password: str
    turnstile_token: str = ""


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    email: str


class LoginErrorResponse(BaseModel):
    detail: str
    remaining_attempts: Optional[int] = None


# === Supabase Auth 调用 ===

async def _supabase_sign_in(email: str, password: str) -> dict:
    """
    调用 Supabase Auth 进行登录验证。

    Returns:
        dict with access_token, expires_in, user_id, email

    Raises:
        Exception: 认证失败
    """
    if not SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL 未配置")

    import httpx

    url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "password": password,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, headers=headers, timeout=15.0)
        data = resp.json()

    if resp.status_code != 200:
        error_msg = data.get("error_description") or data.get("msg") or data.get("error", {}).get("message", "认证失败")
        raise ValueError(error_msg)

    return {
        "access_token": data["access_token"],
        "expires_in": data.get("expires_in", 3600),
        "user_id": data.get("user", {}).get("id", ""),
        "email": data.get("user", {}).get("email", email),
    }


# === 路由 ===

@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request):
    """
    新登录接口（推荐）

    流程：验证 CAPTCHA → 检查锁定 → 调用 Supabase Auth → 记录日志
    """
    ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")

    # 1. CAPTCHA 验证
    if CAPTCHA_ENABLED:
        from auth.captcha import verify_turnstile
        ok = await verify_turnstile(payload.turnstile_token)
        if not ok:
            raise HTTPException(
                status_code=403,
                detail="人机验证失败，请重试",
            )

    # 2. 检查登录计数/锁定
    if LOGIN_SECURITY_ENABLED:
        from auth.login_security import get_login_security
        login_security = get_login_security()
        check = login_security.check(payload.email, ip)
        if not check.allowed:
            from auth.login_logs import record_login_log
            record_login_log(
                email=payload.email, ip=ip, success=False,
                user_agent=user_agent, failure_reason="account_locked",
            )
            raise HTTPException(
                status_code=429,
                detail=check.reason or "账号已锁定，请稍后再试",
            )

    # 3. 调用 Supabase Auth
    try:
        session = await _supabase_sign_in(payload.email, payload.password)
    except (ValueError, RuntimeError) as e:
        # 认证失败
        if LOGIN_SECURITY_ENABLED:
            from auth.login_security import get_login_security
            login_security = get_login_security()
            login_security.record_failure(payload.email, ip)

        from auth.login_logs import record_login_log
        record_login_log(
            email=payload.email, ip=ip, success=False,
            user_agent=user_agent, failure_reason=str(e),
        )

        # 统一错误信息，不区分"用户不存在"和"密码错误"
        remaining = None
        if LOGIN_SECURITY_ENABLED:
            from auth.login_security import get_login_security
            login_security = get_login_security()
            check = login_security.check(payload.email, ip)
            remaining = check.remaining_attempts

        raise HTTPException(
            status_code=401,
            detail=f"认证失败{'，剩余尝试次数: ' + str(remaining) if remaining is not None else ''}",
        )
    except Exception as e:
        # Supabase 服务不可用
        logger.error(f"Supabase Auth 异常: {e}")
        from auth.login_logs import record_login_log
        record_login_log(
            email=payload.email, ip=ip, success=False,
            user_agent=user_agent, failure_reason=f"service_error: {str(e)}",
        )
        raise HTTPException(
            status_code=503,
            detail="认证服务暂时不可用，请稍后再试",
        )

    # 4. 登录成功
    if LOGIN_SECURITY_ENABLED:
        from auth.login_security import get_login_security
        login_security = get_login_security()
        login_security.record_success(payload.email, ip)

    from auth.login_logs import record_login_log
    record_login_log(
        email=payload.email, ip=ip, success=True,
        user_agent=user_agent,
    )

    # 5. 同步用户信息到本地数据库
    try:
        import psycopg
        from auth.user_db import upsert_user
        from auth.model import LocalUser
        from config.db_config import get_psycopg_db_url

        db_url = get_psycopg_db_url(id="login-sync")
        with psycopg.connect(db_url) as conn:
            user = LocalUser(
                user_id=session["user_id"],
                email=session["email"],
            )
            upsert_user(conn, user)
    except Exception as exc:
        logger.warning(f"用户信息同步失败（不影响登录）: {exc}")

    return LoginResponse(
        access_token=session["access_token"],
        expires_in=session["expires_in"],
        user_id=session["user_id"],
        email=session["email"],
    )


@router.post("/login/supabase", response_model=LoginResponse)
async def login_supabase(payload: LoginRequest, request: Request):
    """
    旧登录接口（废弃过渡）

    不验证 CAPTCHA，不记录计数。仅用于兼容现有前端迁移。
    """
    ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")

    try:
        session = await _supabase_sign_in(payload.email, payload.password)
    except (ValueError, RuntimeError):
        from auth.login_logs import record_login_log
        record_login_log(
            email=payload.email, ip=ip, success=False,
            user_agent=user_agent, failure_reason="legacy_login_failed",
        )
        raise HTTPException(status_code=401, detail="认证失败")
    except Exception as e:
        logger.error(f"Supabase Auth 异常 (legacy): {e}")
        raise HTTPException(status_code=503, detail="认证服务暂时不可用")

    from auth.login_logs import record_login_log
    record_login_log(
        email=payload.email, ip=ip, success=True,
        user_agent=user_agent,
    )

    return LoginResponse(
        access_token=session["access_token"],
        expires_in=session["expires_in"],
        user_id=session["user_id"],
        email=session["email"],
    )
