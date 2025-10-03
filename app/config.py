# config.py
import os
from dotenv import load_dotenv

# load_dotenv()

# OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# # Whatsify API Configuration
# WHATSIFY_API_URL = os.getenv("WHATSIFY_API_URL")
# WHATSIFY_API_KEY = os.getenv("WHATSIFY_API_KEY")
# WHATSIFY_ACCOUNT_ID = os.getenv("WHATSIFY_ACCOUNT_ID")

# DATABASE_URL = os.getenv("DATABASE_URL")

# if not DATABASE_URL:
#     raise ValueError("❌ DATABASE_URL not found in environment variables")

# # Add checks for Whatsify if they are critical for application startup
# if not WHATSIFY_API_URL:
#     raise ValueError("❌ WHATSIFY_API_URL not found in environment variables")
# if not WHATSIFY_API_KEY:
#     raise ValueError("❌ WHATSIFY_API_KEY not found in environment variables")
# if not WHATSIFY_ACCOUNT_ID:
#     raise ValueError("❌ WHATSIFY_ACCOUNT_ID not found in environment variables")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)
UPLOAD_DIRECTORY = os.path.join(PROJECT_ROOT, "uploads")
