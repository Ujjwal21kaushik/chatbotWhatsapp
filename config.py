"""Application configuration loaded from environment variables.

Secrets are never hard-coded. For local development, values can live in a
.env file in the project root. In production, set these variables in your
hosting platform or process manager.
"""

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent

# Load .env once before reading any settings. Existing real environment
# variables still win, so production configuration is not overwritten.
load_dotenv(BASE_DIR / ".env", override=False)

DATA_FILE = Path(os.getenv("COMPANY_DATA_FILE", BASE_DIR / "data" / "company_data.json"))
LOG_FILE = Path(os.getenv("APP_LOG_FILE", BASE_DIR / "logs" / "app.log"))

FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

MATCH_THRESHOLD = int(os.getenv("MATCH_THRESHOLD", "85"))
TWILIO_MAX_MESSAGE_LENGTH = int(os.getenv("TWILIO_MAX_MESSAGE_LENGTH", "1500"))

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "")

SAFE_FALLBACK_RESPONSE = (
    "Sorry, I only have information related to RightAds Digital.\n\n"
    "I can help with:\n"
    "- Company Information\n"
    "- Services\n"
    "- Experience\n"
    "- Industries Served\n"
    "- Contact Information\n"
    "- Website Details"
)
