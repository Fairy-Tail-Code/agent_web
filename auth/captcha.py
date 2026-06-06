"""
Cloudflare Turnstile CAPTCHA 验证

验证前端提交的 turnstile_token，确保请求来自真实用户。
"""

import os

import httpx
from dotenv import load_dotenv
from agno.utils.log import logger

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
        # 未配置 secret key 且 CAPTCHA 已启用，拒绝验证
        logger.warning("CAPTCHA_ENABLED=true but TURNSTILE_SECRET_KEY is not set. Rejecting verification.")
        return False

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
    except Exception as e:
        # 网络异常，拒绝验证（避免因 Turnstile 服务不可用而绕过保护）
        logger.warning(f"Turnstile verification request failed: {e}")
        return False
