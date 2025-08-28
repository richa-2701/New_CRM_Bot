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
from app.db import Base, engine

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="WhatsApp CRM Bot API",
    description="Handles incoming WhatsApp messages and processes CRM actions",
    version="1.0.0"
)

# Add the CORS Middleware FIRST.
origins = [
"http://localhost:3000",
"http://192.168.1.62:3000",
"https://9f7cb36b5732.ngrok-free.app", # Your Ngrok URL
]
app.add_middleware(
    CORSMiddleware,
    # Using ["*"] is the most flexible for development with changing Ngrok URLs
    allow_origins=["*"],
    allow_credentials=True,
    # Use ["*"] to allow all methods (POST, GET, OPTIONS, etc.)
    # and all headers (Content-Type, Authorization, etc.)
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- CORRECTED: Include the correctly imported routers ---
# This includes routes like /login, /register, /webhook, etc.
app.include_router(main_router)
# This includes all routes prefixed with /web for the frontend
app.include_router(web_router, prefix="/web", tags=["Web Application"])


app.mount("/attachments", StaticFiles(directory="uploads"), name="attachments")

@app.on_event("startup")
async def start_background_tasks():
    """
    On application startup, this creates a background task that runs the reminder_loop.
    """
    print("🚀 Starting background task for reminders...")
    asyncio.create_task(reminder_loop())

    print("🚀 Starting background task for drip campaigns...")
    asyncio.create_task(drip_campaign_loop())

@app.get("/ping", tags=["Health"])
async def ping():
    """A simple endpoint to check if the API is alive."""
    return {"status": "✅ API is alive"}




def extract_company_name(text: str) -> str:
    match = re.search(r"(?:for|with)\s+(.*?)\s+(?:on|at|with|and|is|\.|,|$)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""