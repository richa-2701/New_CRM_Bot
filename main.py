# main.py

from fastapi import APIRouter, Request, FastAPI
from app.gpt_parser import parse_lead_info
from app.message_sender import send_whatsapp_message
from app.crud import save_lead, update_lead_status
from app.schemas import LeadCreate
import re
from app.webhook import router as webhook_router
from app.reminders import reminder_loop
import asyncio

app = FastAPI(
    title="WhatsApp CRM Bot API",
    description="Handles incoming WhatsApp messages and processes CRM actions",
    version="1.0.0"
)

app.include_router(webhook_router)

@app.on_event("startup")
async def start_background_tasks():
    asyncio.create_task(reminder_loop())

router = APIRouter()

@router.get("/ping")
async def ping():
    return {"status": "✅ Webhook is alive"}


def extract_company_name(text: str) -> str:
    match = re.search(r"(?:for|with)\s+(.*?)\s+(?:on|at|with|and|is|\.|,|$)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""
