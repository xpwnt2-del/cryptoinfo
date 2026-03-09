"""
config.py – Application settings loaded from environment / .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Flask
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    PORT: int = int(os.getenv("PORT", "5000"))

    # Exchange
    EXCHANGE_ID: str = os.getenv("EXCHANGE_ID", "binance")
    EXCHANGE_API_KEY: str = os.getenv("EXCHANGE_API_KEY", "")
    EXCHANGE_SECRET: str = os.getenv("EXCHANGE_SECRET", "")
    EXCHANGE_PASSPHRASE: str = os.getenv("EXCHANGE_PASSPHRASE", "")

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # Bot behaviour
    DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() != "false"
    BOT_INTERVAL: int = int(os.getenv("BOT_INTERVAL", "60"))
    MIN_CONFIDENCE: int = int(os.getenv("MIN_CONFIDENCE", "70"))
    BOT_TRADE_AMOUNT: float = float(os.getenv("BOT_TRADE_AMOUNT", "0.001"))

    # Public data endpoints (no auth required)
    COINGECKO_BASE: str = "https://api.coingecko.com/api/v3"
    CRYPTOCOMPARE_BASE: str = "https://min-api.cryptocompare.com/data"
