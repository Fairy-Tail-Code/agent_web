"""
Cloudflare Turnstile CAPTCHA 验证

验证前端提交的 turnstile_token，确保请求来自真实用户。
"""

import os

import httpx
from dotenv import load_dotenv

load_dotenv()

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")
CAPTCHA_ENABLED = os.getenv("CAPTCHA_ENABLED", "true").lower() == "true"


async def verify_turnstile(token: str) -> bool:
    """
    验证 Turnstile token。

    Args:
        token: 前端提交的 turnstile_token

    Returns:
        True = 验证通过，False = 验证失败
    """
    if not CAPTCHA_ENABLED:
        return True

    if not token:
        return False

    if not TURNSTILE_SECRET_KEY:
        # 未配置 secret key，跳过验证（开发环境）
        return True

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                TURNSTILE_VERIFY_URL,
                data={
                    "secret": TURNSTILE_SECRET_KEY,
                    "response": token,
                },
                timeout=10.0,
            )
            result = resp.json()
            return result.get("success", False)
    except Exception:
        # 网络异常，放行（避免因 Turnstile 服务不可用而阻断登录）
        return True
