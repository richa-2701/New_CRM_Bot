from fastapi import APIRouter, Request, Response, status
from app.handlers.message_router import route_message
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

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

    # We only care about text messages from users.
    if msg_type != "text":
        logger.info(f"✅ Ignored: Non-text message type received ('{msg_type}').")
        return Response(status_code=status.HTTP_200_OK)

    # --- VALIDATE REQUIRED FIELDS FOR PROCESSING ---
    sender_phone = data.get("user", {}).get("phone")
    message_text = msg.get("text", "").strip()
    reply_url = data.get("reply")

    if not all([sender_phone, message_text, reply_url]):
        missing_fields = []
        if not sender_phone: missing_fields.append("user.phone")
        if not message_text: missing_fields.append("message.text")
        if not reply_url: missing_fields.append("reply_url")
        logger.error(f"❌ Aborted: Missing critical fields in payload: {', '.join(missing_fields)}")
        return Response(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=f"Missing fields: {', '.join(missing_fields)}")

    # If all checks pass, route the message to the central handler
    logger.info(f"Routing message from {sender_phone} to message_router.")
    response_from_handler = await route_message(sender_phone, message_text, reply_url)

    return response_from_handler
