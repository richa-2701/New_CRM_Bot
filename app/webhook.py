from fastapi import APIRouter, Request, Response, status,HTTPException,Depends
from app.handlers.message_router import route_message
import logging
from app.models import Lead
from app.schemas import LeadResponse, UserCreate, UserLogin, UserResponse, TaskOut
from app.crud import create_user, verify_user
from sqlalchemy.orm import Session
from app.db import get_db
from app.crud import get_user_by_username,get_tasks_by_username


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/register", response_model=UserResponse)
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    existing = get_user_by_username(db, user.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    return create_user(db, user)


@router.post("/login", response_model=UserResponse)
def login_user(user: UserLogin, db: Session = Depends(get_db)):
    authenticated_user = verify_user(db, user.username, user.password)
    if not authenticated_user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return authenticated_user

@router.get("/leads/{user_id}", response_model=list[LeadResponse])
async def get_leads_by_user_id(user_id: str, db: Session = Depends(get_db)):
    leads = db.query(Lead).filter(Lead.assigned_to == user_id).all()
    if not leads:
        raise HTTPException(status_code=404, detail="No leads found for this user")
    return leads

@router.get("/tasks/{username}", response_model=list[TaskOut])
def get_user_tasks(username: str, db: Session = Depends(get_db)):
    tasks = get_tasks_by_username(db, username)
    if not tasks:
        raise HTTPException(status_code=404, detail="No tasks found for this user")
    return tasks

@router.get("/webhook", tags=["Webhook"])
async def webhook_verification(request: Request):
    """
    Handles WhatsApp's webhook verification GET request.
    Your webhook provider might require this to confirm your endpoint is valid.
    """
    logger.info("GET request received at /webhook for verification.")
    return Response(content="Webhook Verified", status_code=200)


@router.post("/webhook", tags=["Webhook"])
async def receive_message(req: Request):
    """
    Handles all incoming POST requests from the WhatsApp API provider.
    It filters for user-sent text messages and routes them for processing.
    """
    try:
        data = await req.json()
    except Exception as e:
        logger.error(f"❌ Failed to parse incoming JSON: {e}")
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content="Invalid JSON")

    logger.info(f"📦 Incoming Payload: {data}")

    # ✅ Filter: Ignore non-message types like 'ack', 'status', etc.
    if data.get("type") != "message":
        logger.info(f"✅ Skipped non-message payload of type: {data.get('type')}")
        return Response(status_code=status.HTTP_200_OK)

    # Check if this is a user message payload.
    if "message" not in data or not isinstance(data["message"], dict):
        logger.info("✅ Ignored: Payload does not contain a 'message' object.")
        return Response(status_code=status.HTTP_200_OK)

    msg = data.get("message", {})
    msg_type = msg.get("type")
    source = data.get("source", "whatsapp")  # Default to "whatsapp" if not specified
    logger.info(f"📩 Processing message type: {msg_type} from source: {source}")

    # We only care about text messages from users.
    if msg_type != "text":
        logger.info(f"✅ Ignored: Non-text message type received ('{msg_type}').")
        return Response(status_code=status.HTTP_200_OK)

    # --- VALIDATE REQUIRED FIELDS FOR PROCESSING ---
    sender_phone = data.get("user", {}).get("phone")
    message_text = msg.get("text", "").strip()
    reply_url = data.get("reply", "")  # For app, reply_url might not be needed

    # For app source, we don't need reply_url
    if source.lower() == "app":
        if not all([sender_phone, message_text]):
            missing_fields = []
            if not sender_phone: missing_fields.append("user.phone")
            if not message_text: missing_fields.append("message.text")
            logger.error(f"❌ Aborted: Missing critical fields in app payload: {', '.join(missing_fields)}")
            return Response(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=f"Missing fields: {', '.join(missing_fields)}")
    else:
        # For WhatsApp, we need all fields
        if not all([sender_phone, message_text, reply_url]):
            missing_fields = []
            if not sender_phone: missing_fields.append("user.phone")
            if not message_text: missing_fields.append("message.text")
            if not reply_url: missing_fields.append("reply_url")
            logger.error(f"❌ Aborted: Missing critical fields in payload: {', '.join(missing_fields)}")
            return Response(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=f"Missing fields: {', '.join(missing_fields)}")

    # If all checks pass, route the message to the central handler
    logger.info(f"Routing message from {sender_phone} to message_router.")
    response_from_handler = await route_message(sender_phone, message_text, reply_url, source)

    return response_from_handler


@router.post("/app", tags=["App"])
async def receive_app_message(req: Request):
    """
    Handles incoming POST requests from the mobile/web app.
    Simplified endpoint for app-based CRM interactions.
    """
    try:
        data = await req.json()
    except Exception as e:
        logger.error(f"❌ Failed to parse incoming JSON: {e}")
        return {"status": "error", "reply": "Invalid JSON"}

    logger.info(f"📱 Incoming App Payload: {data}")

    # --- VALIDATE REQUIRED FIELDS FOR APP ---
    sender_phone = data.get("user_phone") or data.get("phone")
    message_text = data.get("message", "").strip()

    if not all([sender_phone, message_text]):
        missing_fields = []
        if not sender_phone: missing_fields.append("user_phone")
        if not message_text: missing_fields.append("message")
        logger.error(f"❌ Aborted: Missing critical fields in app payload: {', '.join(missing_fields)}")
        return {"status": "error", "reply": f"Missing fields: {', '.join(missing_fields)}"}

    # Route the message to the central handler with app source
    logger.info(f"Routing app message from {sender_phone} to message_router.")
    response_from_handler = await route_message(sender_phone, message_text, "", "app")

    return response_from_handler
