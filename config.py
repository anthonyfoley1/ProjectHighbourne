"""Centralized configuration -- all API keys, feature flags, and settings."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

# Load .env file if it exists
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip())

# Data source toggle: "defeatbeta" or "legacy"
DATA_SOURCE = os.environ.get("HIGHBOURNE_DATA_SOURCE", "defeatbeta")

# API Keys (from environment or defaults)
SIMFIN_API_KEY = os.environ.get("SIMFIN_API_KEY", "")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

# Database
DB_PATH = PROJECT_ROOT / "highbourne.db"

# App
APP_PORT = int(os.environ.get("HIGHBOURNE_PORT", "8050"))
APP_DEBUG = os.environ.get("HIGHBOURNE_DEBUG", "false").lower() == "true"

# LLM (Groq — OpenAI-compatible, free tier)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.1-8b-instant"
