# 登录安全增强方案

> 日期：2026-06-06
> 状态：待实施

## 1. 背景

### 1.1 现状

当前登录系统架构：

```
前端 → Supabase Auth → JWT → Nginx(JWT验证) → 后端
```

- **认证层**：Supabase Auth（邮箱/密码/OAuth）
- **JWT 验证**：Nginx 层 lua 实现
- **API 限流**：Nginx 层 30r/s，burst=60

### 1.2 风险点

| 风险 | 现状 | 后果 |
|------|------|------|
| 暴力破解 | 只有全局 30r/s，无登录失败计数 | 可无限尝试密码 |
| 人机验证 | 无 CAPTCHA | 机器人批量注册/登录 |
| 账号锁定 | 无 | 攻击者可一直尝试 |
| 错误信息泄露 | 可能返回"用户不存在"/"密码错误" | 枚举有效用户 |
| 登录异常检测 | 无 | 无法识别异常登录 |
| 登录日志 | 无 | 安全事件无据可查 |

### 1.3 优化目标

1. **人机验证**：集成 Cloudflare Turnstile（免费、隐私友好）
2. **登录计数**：Redis 或 SQLite 存储失败次数
3. **账号锁定**：连续失败 N 次锁定 M 分钟
4. **统一错误信息**：不区分"用户不存在"和"密码错误"
5. **登录日志**：记录 IP、时间、设备、结果
6. **渐进迁移**：新旧登录方式共存一段时间

---

## 2. 目标架构

### 2.1 数据流

```
                    ┌──────────────────────────────────────────┐
                    │              前端登录页                   │
                    │  1. 渲染 Turnstile widget                │
                    │  2. 用户通过验证 → 获得 turnstile_token  │
                    │  3. 提交 { email, password, token }      │
                    └────────────────────┬─────────────────────┘
                                         │ POST /auth/login
                                         ▼
              ┌──────────────────────────────────────────────┐
              │           Nginx (不改动)                      │
              │  - 全局 30r/s 限流                            │
              │  - JWT 验证（仅对 /backend/* 生效）           │
              │  - /auth/* 路由放行（不需要 JWT）             │
              └────────────────────┬─────────────────────────┘
                                   ▼
              ┌──────────────────────────────────────────────┐
              │           login_router.py                    │
              │  1. 验证 Turnstile token（失败 → 拒绝）       │
              │  2. 检查登录计数/锁定（锁定中 → 拒绝）        │
              │  3. 调用 Supabase Auth（失败 → 记录计数）     │
              │  4. 记录登录日志                             │
              │  5. 返回 JWT                                │
              └──────────────────────────────────────────────┘
```

### 2.2 双轨制（渐进迁移）

```
旧接口（废弃过渡）: POST /auth/login/supabase
  - 限流更严（10r/s）
  - 最终废弃

新接口（推荐）: POST /auth/login
  - 正常限流
  - 带 CAPTCHA
  - 计数/锁定
```

---

## 3. 技术方案

### 3.1 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| CAPTCHA | Cloudflare Turnstile | 免费、隐私友好、效果好 |
| 计数存储 | Redis（可选）/ SQLite | Redis 推荐，支持过期键自动清理 |
| 登录日志 | SQLite `auth.login_logs` 表 | 轻量，与现有数据库一致 |
| Supabase 客户端 | `supabase-py` | 官方 Python SDK |

### 3.2 新增模块

```
auth/
  ├── __init__.py            # 新增 exports
  ├── login_security.py      # 登录安全核心：计数、锁定
  ├── captcha.py             # Turnstile 验证
  ├── login_router.py        # 新登录 API 路由
  ├── login_logs.py          # 登录日志表 + 写入
  ├── (原有模块不变)
```

### 3.3 环境变量

```bash
# Turnstile（必填）
TURNSTILE_SITE_KEY=1x00000000000000000000AA
TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA

# 登录安全（可选，有默认值）
LOGIN_MAX_ATTEMPTS=5          # 最大失败次数
LOGIN_LOCKOUT_MINUTES=15      # 锁定时长（分钟）
LOGIN_SECURITY_ENABLED=true    # 总开关
CAPTCHA_ENABLED=true           # CAPTCHA 开关

# Redis（可选，不填则用 SQLite）
REDIS_URL=redis://localhost:6379/0
```

---

## 4. 详细设计

### 4.1 `auth/login_security.py`

**职责**：登录失败计数 + 账号锁定

```python
from dataclasses import dataclass
from datetime import datetime, timezone

# 计数存储（Redis 或 SQLite）
# Redis key: login_fail:{email} → count, TTL = LOCKOUT_MINUTES
# Redis key: login_fail:{ip} → count, TTL = LOCKOUT_MINUTES

@dataclass
class LoginAttemptResult:
    allowed: bool
    reason: str | None  # None = 允许，string = 拒绝原因
    remaining_attempts: int
    lockout_until: datetime | None

class LoginSecurity:
    def __init__(self, max_attempts=5, lockout_minutes=15):
        ...

    def check(self, email: str, ip: str) -> LoginAttemptResult:
        """检查是否允许尝试登录"""

    def record_failure(self, email: str, ip: str) -> None:
        """记录一次失败"""

    def record_success(self, email: str) -> None:
        """登录成功，清零计数"""

    def is_locked_out(self, email: str, ip: str) -> bool:
        """是否被锁定"""
```

### 4.2 `auth/captcha.py`

**职责**：Turnstile token 验证

```python
import httpx

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

async def verify_turnstile(token: str, secret: str) -> bool:
    """
    验证 Turnstile token
    Returns: True = 验证通过，False = 验证失败
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TURNSTILE_VERIFY_URL,
            data={
                "secret": secret,
                "response": token,
            },
            timeout=10.0,
        )
        result = resp.json()
        return result.get("success", False)
```

### 4.3 `auth/login_router.py`

**职责**：新的登录 API 路由

```python
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["Authentication"])

class LoginRequest(BaseModel):
    email: str
    password: str
    turnstile_token: str = ""

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str

@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request):
    """
    新登录接口（推荐）
    - 验证 Turnstile token
    - 检查登录计数/锁定
    - 调用 Supabase Auth
    - 记录登录日志
    """
    # 1. CAPTCHA 验证
    if CAPTCHA_ENABLED:
        ok = await verify_turnstile(payload.turnstile_token, TURNSTILE_SECRET_KEY)
        if not ok:
            raise HTTPException(status_code=403, detail="人机验证失败")

    # 2. 检查登录计数
    ip = request.client.host
    check = login_security.check(payload.email, ip)
    if not check.allowed:
        raise HTTPException(status_code=429, detail=check.reason)

    # 3. 调用 Supabase Auth
    try:
        session = await supabase.auth.sign_in_with_password(
            email=payload.email,
            password=payload.password,
        )
    except Exception as e:
        login_security.record_failure(payload.email, ip)
        record_login_log(email=payload.email, ip=ip, success=False, reason=str(e))
        # 统一错误信息，不区分原因
        raise HTTPException(status_code=401, detail="认证失败")

    # 4. 登录成功
    login_security.record_success(payload.email)
    record_login_log(email=payload.email, ip=ip, success=True)

    return LoginResponse(
        access_token=session.access_token,
        expires_in=session.expires_in,
        user_id=session.user.id,
    )


@router.post("/login/supabase", response_model=LoginResponse)
async def login_supabase(payload: LoginRequest, request: Request):
    """
    旧登录接口（废弃过渡，限流更严）
    不验证 CAPTCHA，不记录计数
    仅用于兼容现有前端迁移
    """
    # 更严格的限流 + 记录
    ...
```

### 4.4 `auth/login_logs.py`

**职责**：登录日志记录

```python
# SQL
_CREATE_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS auth.login_logs (
    log_id        SERIAL PRIMARY KEY,
    email         TEXT NOT NULL,
    ip            TEXT NOT NULL,
    user_agent    TEXT,
    success       BOOLEAN NOT NULL,
    failure_reason TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_login_logs_email ON auth.login_logs(email);
CREATE INDEX IF NOT EXISTS idx_login_logs_ip ON auth.login_logs(ip);
CREATE INDEX IF NOT EXISTS idx_login_logs_created_at ON auth.login_logs(created_at);
"""

def record_login_log(
    conn,
    email: str,
    ip: str,
    success: bool,
    failure_reason: str = None,
):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO auth.login_logs (email, ip, success, failure_reason) VALUES (%s, %s, %s, %s)",
            (email, ip, success, failure_reason)
        )
    conn.commit()
```

### 4.5 Nginx 配置调整

**需要调整的地方**：

```nginx
# /auth/login 和 /auth/login/supabase 不需要 JWT 验证
# 需要加到 PUBLIC_PATHS 或单独处理

# /auth/* 路由的限流可以稍微放宽（因为有应用层计数兜底）
limit_req_zone $binary_remote_addr zone=auth_login:10m rate=10r/s;
```

---

## 5. 前端改动

### 5.1 Turnstile 集成

**登录页面 HTML**：

```html
<!-- 1. 引入 Turnstile SDK -->
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>

<!-- 2. 在登录表单中添加 widget -->
<form id="login-form">
    <input type="email" name="email" required>
    <input type="password" name="password" required>

    <!-- Turnstile widget -->
    <div class="cf-turnstile" data-sitekey="{{ TURNSTILE_SITE_KEY }}" data-callback="onTurnstileSuccess"></div>

    <button type="submit">登录</button>
</form>

<script>
let turnstileToken = '';

function onTurnstileSuccess(token) {
    turnstileToken = token;
}

document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const formData = new FormData(e.target);
    const email = formData.get('email');
    const password = formData.get('password');

    const response = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            email,
            password,
            turnstile_token: turnstileToken
        })
    });

    if (response.ok) {
        const { access_token } = await response.json();
        // 保存 token，跳转
    } else {
        // 显示错误，重置 Turnstile
        turnstileToken = '';
        turnstile.reset();
    }
});
</script>
```

### 5.2 改动点清单

| 改动 | 说明 |
|------|------|
| 引入 Turnstile SDK | 1 行 script |
| 渲染 widget | 1 个 div + callback JS |
| 提交时附带 token | 修改 fetch 参数 |
| 错误处理 | 显示错误 + 重置 widget |

**改动量**：约 30 行代码

---

## 6. 实施计划

### 6.1 优先级

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| **Phase 1** | 后端 `login_security.py` + `captcha.py` + `login_router.py` | P0 |
| **Phase 1** | 后端 `login_logs.py` | P0 |
| **Phase 1** | Supabase Auth 配置（邮箱验证、密码强度） | P0 |
| **Phase 2** | 前端 Turnstile 集成 | P1 |
| **Phase 2** | 灰度切换：新旧接口共存 | P1 |
| **Phase 3** | 旧接口 `/auth/login/supabase` 限流收紧 | P2 |
| **Phase 3** | 监控告警（异常登录检测） | P2 |

### 6.2 实施步骤

#### Phase 1（后端安全增强）

1. 新增 `auth/login_security.py`（登录计数/锁定）
2. 新增 `auth/captcha.py`（Turnstile 验证）
3. 新增 `auth/login_logs.py`（登录日志）
4. 新增 `auth/login_router.py`（新登录路由）
5. 修改 `auth/user_db.py`（加 login_logs 建表）
6. 修改 `api/main.py`（注册 login_router）
7. 配置 Supabase（强制邮箱验证、密码最小长度）
8. 添加环境变量

#### Phase 2（前端集成 + 灰度）

1. 前端登录页集成 Turnstile widget
2. 前端改用 `/auth/login`
3. 保留 `/auth/login/supabase` 兼容
4. 观察日志，确认流程正常

#### Phase 3（加固 + 监控）

1. 收紧旧接口限流
2. 添加异常登录告警（可选）

---

## 7. 配置参考

### 7.1 Supabase Auth 配置

建议在 Supabase Dashboard 设置：

| 设置 | 推荐值 |
|------|--------|
| 邮箱确认 | **强制开启** |
| 密码最小长度 | 8 位 |
| JWT expiry | 1 小时 |
| Refresh token expiry | 7 天 |

### 7.2 Turnstile 配置

在 [Cloudflare Dashboard](https://dash.cloudflare.com/turnstile) 创建站点，获取：

- **Site Key**：前端渲染 widget 用
- **Secret Key**：后端验证 token 用

---

## 8. 错误处理

| 场景 | 返回 | 前端处理 |
|------|------|---------|
| CAPTCHA 验证失败 | 403 | 提示重试，重新获取 token |
| 账号被锁定 | 429 | 显示剩余解锁时间 |
| 登录失败（密码错误） | 401 | 提示认证失败，显示剩余尝试次数 |
| 登录失败（用户不存在） | 401 | 提示认证失败（同上，不区分） |
| Supabase 不可用 | 503 | 提示服务暂时不可用 |

---

## 9. 测试计划

| 测试 | 场景 | 预期 |
|------|------|------|
| CAPTCHA 失败 | 不带/带无效 token | 403，拒绝登录 |
| 正常登录 | 带有效 token + 正确密码 | 200，返回 JWT |
| 密码错误 | 带有效 token + 错误密码 | 401，记录失败计数 |
| 暴力破解 | 连续 5 次错误密码 | 第 6 次返回 429，锁定 |
| 锁定期间 | 锁定后再请求 | 429，显示剩余解锁时间 |
| 登录成功后 | 正确密码 | 失败计数清零 |
| 旧接口降级 | 关掉新接口 | 旧接口仍可用（限流更严） |

---

## 10. 回滚方案

如果 Phase 2/3 出现问题：

1. **前端**：改回调用 `/auth/login/supabase`
2. **后端**：设置 `LOGIN_SECURITY_ENABLED=false` 可禁用计数/锁定
3. **CAPTCHA**：设置 `CAPTCHA_ENABLED=false` 可禁用验证
4. **完全回滚**：删除新路由，前端恢复旧调用

---

*文档创建日期：2026-06-06*
*方案状态：待实施*
