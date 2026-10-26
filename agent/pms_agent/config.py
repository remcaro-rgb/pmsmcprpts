import os
import tempfile
from dataclasses import dataclass, field


def _env_list(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    mcp_url: str = field(default_factory=lambda: os.environ.get("PMS_MCP_URL", "http://localhost:7070/mcp"))
    # Service token for an MCP server that requires sign-in (its PMS_MCP_SERVICE_TOKEN).
    mcp_token: str | None = field(default_factory=lambda: os.environ.get("PMS_MCP_TOKEN") or None)
    model: str = field(default_factory=lambda: os.environ.get("PMS_CLAUDE_MODEL", "claude-sonnet-5-5"))
    effort: str = field(default_factory=lambda: os.environ.get("PMS_CLAUDE_EFFORT", "medium"))
    max_tokens: int = field(default_factory=lambda: int(os.environ.get("PMS_CLAUDE_MAX_TOKENS", "64000")))
    max_tool_steps: int = field(default_factory=lambda: int(os.environ.get("PMS_MAX_TOOL_STEPS", "15")))
    # Server-side refusal fallbacks are available on the Claude API; disable for other platforms.
    server_fallbacks: bool = field(
        default_factory=lambda: os.environ.get("PMS_SERVER_FALLBACKS", "true").lower() == "true")
    # Shared with the MCP server, which writes generated files here.
    artifacts_dir: str = field(default_factory=lambda: os.environ.get(
        "PMS_ARTIFACTS_DIR", os.path.join(tempfile.gettempdir(), "pms-artifacts")))
    # Saved conversations (SQLite file, or ":memory:").
    conversations_db: str = field(default_factory=lambda: os.environ.get(
        "PMS_CONVERSATIONS_DB", os.path.join(tempfile.gettempdir(), "pms-conversations.sqlite")))
    # The user directory (db/init/05_users.sh), as the pms_app role. When set, the website's users
    # sign in with these accounts, administrators manage them, and chat requires an active user.
    app_database_url: str | None = field(default_factory=lambda: os.environ.get("PMS_APP_DATABASE_URL") or None)
    # When the day's recommendations are made again (the hotels' time zone).
    timezone: str = field(default_factory=lambda: os.environ.get("PMS_TIMEZONE", "UTC"))
    # The daily email (digest.py): sent through this SMTP server at PMS_DIGEST_TIME (PMS_TIMEZONE)
    # to the users who turn it on. Off without SMTP_HOST.
    smtp_host: str | None = field(default_factory=lambda: os.environ.get("SMTP_HOST") or None)
    smtp_port: int = field(default_factory=lambda: int(os.environ.get("SMTP_PORT") or "587"))
    smtp_user: str | None = field(default_factory=lambda: os.environ.get("SMTP_USER") or None)
    smtp_password: str | None = field(default_factory=lambda: os.environ.get("SMTP_PASSWORD") or None, repr=False)
    smtp_from: str | None = field(default_factory=lambda: os.environ.get("SMTP_FROM") or None)
    # "starttls" (port 587), "ssl" (port 465) or "none".
    smtp_security: str = field(default_factory=lambda: (os.environ.get("SMTP_SECURITY") or "starttls").lower())
    digest_time: str = field(default_factory=lambda: os.environ.get("PMS_DIGEST_TIME") or "07:00")
    # When the day's recommendations are made for everyone who used them lately (after the nightly
    # FNSrooms import, before people arrive), so the first visit doesn't wait for them.
    prepare_time: str = field(default_factory=lambda: os.environ.get("PMS_PREPARE_TIME") or "05:00")
    # The website's address, for the email's links.
    site_url: str = field(default_factory=lambda: (os.environ.get("PMS_SITE_URL") or "http://localhost:5050").rstrip("/"))
    cors_origins: list[str] = field(
        default_factory=lambda: _env_list("PMS_CORS_ORIGINS", "http://localhost:5050"))
