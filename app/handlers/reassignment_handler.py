from sqlalchemy.orm import Session
from app.models import Lead, AssignmentLog
from app.message_sender import send_whatsapp_message
from datetime import datetime

def handle_reassignment(db: Session, message: str, sender: str, reply_url: str):
    try:
        # TODO: extract lead and new assignee
        send_whatsapp_message(reply_url, sender, "✅ Reassignment completed.")
        return {"status": "success"}
    except Exception as e:
        send_whatsapp_message(reply_url, sender, f"❌ Error in reassignment: {str(e)}")
        return {"status": "error", "details": str(e)}
