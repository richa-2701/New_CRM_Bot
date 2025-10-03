# main.py

from fastapi import APIRouter, Request, FastAPI
from fastapi.staticfiles import StaticFiles
from app.gpt_parser import parse_lead_info
from app.message_sender import send_whatsapp_message
from app.crud import save_lead, update_lead_status
from app.schemas import LeadCreate
from app.reminders import reminder_loop, drip_campaign_loop
import re
from app.webhook import main_router, web_router
import asyncio
from fastapi.middleware.cors import CORSMiddleware
# --- START OF CHANGE ---
# REMOVED: from app.db import Base, engine
# ADDED: New imports for multi-tenant database initialization and the scheduler
from app.db import Base, get_engine, COMPANY_TO_ENV_MAP
from app.scheduler import scheduler
import logging
# --- END OF CHANGE ---
import os

# --- START OF CHANGE ---
# Using the logger for consistent output
logger = logging.getLogger(__name__)
# --- END OF CHANGE ---

# Define the absolute path to the project's root directory
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# Define the absolute path to the 'uploads' directory
UPLOADS_DIR_ABSOLUTE = os.path.join(PROJECT_ROOT, "uploads")


app = FastAPI(
    title="WhatsApp CRM Bot API",
    description="Handles incoming WhatsApp messages and processes CRM actions",
    version="1.0.0"
)

# Add the CORS Middleware FIRST.
origins = [
"http://localhost:3000",
"http://192.168.1.62:3000",
"http://157.20.215.187:3001",
"http://157.20.215.187:7200",
"https://9f7cb36b5732.ngrok-free.app",
"http://192.168.1.23:3000"# Your Ngrok URL
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(main_router)
app.include_router(web_router, prefix="/web", tags=["Web Application"])

app.mount("/attachments", StaticFiles(directory=UPLOADS_DIR_ABSOLUTE), name="attachments")


@app.on_event("startup")
async def startup_event():
    """
    On application startup, this function performs critical tasks:
    1. Initializes all configured databases, creating tables if they don't exist.
    2. Starts the background tasks for reminders and drip campaigns.
    3. Starts the background scheduler for jobs like weekly reports.
    """
    logger.info("🚀 Application starting up...")

    # 1. Initialize Databases
    logger.info("🔧 Initializing databases for all tenants...")
    all_companies = list(COMPANY_TO_ENV_MAP.keys())
    for company in all_companies:
        try:
            logger.info(f"   -> Connecting to database for company: '{company}'")
            # Get the specific engine for the company
            company_engine = get_engine(company)
            # Create all tables defined in models.py for this specific engine
            Base.metadata.create_all(bind=company_engine)
            logger.info(f"   ✅ Database tables verified/created for '{company}'.")
        except Exception as e:
            logger.error(f"   ❌ FAILED to initialize database for '{company}': {e}")
            # Depending on your needs, you might want to exit the app if a DB fails
            # For now, we just print the error and continue.
    
    # 2. Start Background Tasks
    logger.info("⏰ Starting background task for reminders...")
    asyncio.create_task(reminder_loop())

    logger.info("💧 Starting background task for drip campaigns...")
    asyncio.create_task(drip_campaign_loop())
    
    # --- START OF CHANGE: ADDED THE SCHEDULER START LOGIC ---
    # 3. Start the Background Scheduler
    try:
        scheduler.start()
        logger.info("✅ Background scheduler for weekly reports has been started.")
    except Exception as e:
        logger.error(f"❌ Failed to start the scheduler: {e}", exc_info=True)
    # --- END OF CHANGE ---
    
    logger.info("✅ Startup complete.")


@app.get("/ping", tags=["Health"])
async def ping():
    """A simple endpoint to check if the API is alive."""
    return {"status": "✅ API is alive"}




def extract_company_name(text: str) -> str:
    match = re.search(r"(?:for|with)\s+(.*?)\s+(?:on|at|with|and|is|\.|,|$)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""