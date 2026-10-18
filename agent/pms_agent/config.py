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
    cors_origins: list[str] = field(
        default_factory=lambda: _env_list("PMS_CORS_ORIGINS", "http://localhost:5050"))
