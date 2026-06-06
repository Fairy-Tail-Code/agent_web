from dataclasses import dataclass, field


@dataclass(frozen=True)
class CurrentUser:
    """Written to request.state by AuthMiddleware."""
    user_id: str
    email: str
    scopes: list[str] = field(default_factory=list)


@dataclass
class LocalUser:
    """Local auth.users table row."""
    user_id: str
    email: str
    nickname: str = ""
    avatar_url: str = ""
    created_at: str = ""
    last_login_at: str = ""
    is_active: bool = True
