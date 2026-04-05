"""Centralized configuration -- all API keys, feature flags, and settings."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

# Data source toggle: "defeatbeta" or "legacy"
DATA_SOURCE = os.environ.get("HIGHBOURNE_DATA_SOURCE", "defeatbeta")

# API Keys (from environment or defaults)
SIMFIN_API_KEY = os.environ.get("SIMFIN_API_KEY", "4e0d0ff7-a1af-4333-9f4b-55d97e801b35")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "d78hojpr01qsbhvtsqo0d78hojpr01qsbhvtsqog")

# Database
DB_PATH = PROJECT_ROOT / "highbourne.db"

# App
APP_PORT = int(os.environ.get("HIGHBOURNE_PORT", "8050"))
APP_DEBUG = os.environ.get("HIGHBOURNE_DEBUG", "false").lower() == "true"

# LLM (Groq — OpenAI-compatible, free tier)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.1-8b-instant"
