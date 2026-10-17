import os
from dataclasses import dataclass, field


def _env_list(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    mcp_url: str = field(default_factory=lambda: os.environ.get("PMS_MCP_URL", "http://localhost:8000/mcp"))
    model: str = field(default_factory=lambda: os.environ.get("PMS_CLAUDE_MODEL", "claude-opus-5-5"))
    effort: str = field(default_factory=lambda: os.environ.get("PMS_CLAUDE_EFFORT", "medium"))
    max_tokens: int = field(default_factory=lambda: int(os.environ.get("PMS_CLAUDE_MAX_TOKENS", "64000")))
    max_tool_steps: int = field(default_factory=lambda: int(os.environ.get("PMS_MAX_TOOL_STEPS", "15")))
    # Server-side refusal fallbacks are available on the Claude API; disable for other platforms.
    server_fallbacks: bool = field(
        default_factory=lambda: os.environ.get("PMS_SERVER_FALLBACKS", "true").lower() == "true")
    cors_origins: list[str] = field(
        default_factory=lambda: _env_list("PMS_CORS_ORIGINS", "http://localhost:3000"))
