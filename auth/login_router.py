"""
登录 API 路由

接口一览：
- POST /auth/send-magic-link  : 前端登录页调用，验证 CAPTCHA + 发送 OTP 魔法链接
- POST /auth/login            : 邮箱密码登录（预留）
- POST /auth/login/supabase   : 旧接口（废弃过渡）
"""

import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from agno.utils.log import logger

from auth.login_security import get_login_security

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


class MagicLinkRequest(BaseModel):
    email: str
    turnstile_token: str = ""


class MagicLinkResponse(BaseModel):
    success: bool
    message: str


# === Supabase Auth 调用 ===

async def _supabase_sign_in(email: str, password: str) -> dict:
    """
    调用 Supabase Auth 进行邮箱密码登录。

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


async def _supabase_send_otp(email: str) -> None:
    """
    调用 Supabase Auth 发送 Magic Link (OTP)。

    Raises:
        Exception: 发送失败
    """
    if not SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL 未配置")

    import httpx

    url = f"{SUPABASE_URL}/auth/v1/otp"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "create_user": True,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, headers=headers, timeout=15.0)

    if resp.status_code not in (200, 201):
        data = resp.json()
        error_msg = data.get("error_description") or data.get("msg") or "发送失败"
        raise ValueError(error_msg)


# === 路由 ===

@router.post("/send-magic-link", response_model=MagicLinkResponse)
async def send_magic_link(payload: MagicLinkRequest, request: Request):
    """
    发送 Magic Link 登录邮件（前端登录页实际调用）。

    流程：验证 CAPTCHA → 检查锁定 → 调用 Supabase OTP → 记录日志
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
        login_security = get_login_security()
        check = login_security.check(payload.email, ip)
        if not check.allowed:
            raise HTTPException(
                status_code=429,
                detail=check.reason or "请求过于频繁，请稍后再试",
            )

    # 3. 调用 Supabase 发送 OTP
    try:
        await _supabase_send_otp(payload.email)
    except (ValueError, RuntimeError) as e:
        logger.warning(f"Magic link 发送失败: email={payload.email} error={e}")
        if LOGIN_SECURITY_ENABLED:
            login_security = get_login_security()
            login_security.record_failure(payload.email, ip)

        from auth.login_logs import record_login_log
        record_login_log(
            email=payload.email, ip=ip, success=False,
            user_agent=user_agent, failure_reason=str(e),
        )
        raise HTTPException(status_code=400, detail="发送登录链接失败，请稍后再试")
    except Exception as e:
        logger.error(f"Supabase OTP 服务异常: {e}")
        raise HTTPException(status_code=503, detail="认证服务暂时不可用")

    # 4. 成功日志
    from auth.login_logs import record_login_log
    record_login_log(
        email=payload.email, ip=ip, success=True,
        user_agent=user_agent,
    )

    return MagicLinkResponse(
        success=True,
        message="登录链接已发送，请前往邮箱点击链接完成登录。",
    )


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request):
    """
    邮箱密码登录接口（预留）

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


@router.post("/login/supabase", response_model=LoginResponse, deprecated=True)
async def login_supabase(payload: LoginRequest, request: Request):
    """
    [DEPRECATED] 旧登录接口（废弃过渡）

    此接口已弃用，请使用 /auth/login 或 /auth/send-magic-link。
    现已加入 CAPTCHA 验证和登录安全检查。
    """
    import warnings
    warnings.warn(
        "/auth/login/supabase is deprecated. Use /auth/login or /auth/send-magic-link instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    logger.warning("Deprecated endpoint /auth/login/supabase called")

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
    except (ValueError, RuntimeError):
        if LOGIN_SECURITY_ENABLED:
            login_security = get_login_security()
            login_security.record_failure(payload.email, ip)

        from auth.login_logs import record_login_log
        record_login_log(
            email=payload.email, ip=ip, success=False,
            user_agent=user_agent, failure_reason="legacy_login_failed",
        )
        raise HTTPException(status_code=401, detail="认证失败")
    except Exception as e:
        logger.error(f"Supabase Auth 异常 (legacy): {e}")
        raise HTTPException(status_code=503, detail="认证服务暂时不可用")

    # 4. 登录成功
    if LOGIN_SECURITY_ENABLED:
        login_security = get_login_security()
        login_security.record_success(payload.email, ip)

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
