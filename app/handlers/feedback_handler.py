from sqlalchemy.orm import Session
from app.models import Feedback
from app.message_sender import send_whatsapp_message
from datetime import datetime

def handle_feedback(db: Session, message: str, sender: str, reply_url: str):
    try:
        # TODO: extract company and feedback content
        send_whatsapp_message(reply_url, sender, "✅ Feedback recorded successfully.")
        return {"status": "success"}
    except Exception as e:
        send_whatsapp_message(reply_url, sender, f"❌ Error saving feedback: {str(e)}")
        return {"status": "error", "details": str(e)}
