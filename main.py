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
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="WhatsApp CRM Bot API",
    description="Handles incoming WhatsApp messages and processes CRM actions",
    version="1.0.0"
)
router = APIRouter()
app.include_router(webhook_router)
app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def start_background_tasks():
    """
    On application startup, this creates a background task that runs the reminder_loop.
    """
    print("🚀 Starting background task for reminders...")
    asyncio.create_task(reminder_loop())

@router.get("/ping")
async def ping():
    return {"status": "✅ Webhook is alive"}


@router.post("/test-app", tags=["Test"])
async def test_app_message():
    """
    Test endpoint to verify app message handling works correctly
    """
    from app.handlers.message_router import route_message
    
    # Test data
    test_message = "ABC Corp, John Doe, 9876543210, referral, assign to Banwari"
    test_phone = "9876543210"
    
    # Route the message with app source
    response = await route_message(test_phone, test_message, "", "app")
    
    return {
        "test_input": {
            "message": test_message,
            "phone": test_phone,
            "source": "app"
        },
        "response": response
    }

def extract_company_name(text: str) -> str:
    match = re.search(r"(?:for|with)\s+(.*?)\s+(?:on|at|with|and|is|\.|,|$)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""