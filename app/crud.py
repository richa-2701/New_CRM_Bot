from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from app import models, schemas
from app.models import User
# :mag: Get user by number (usernumber)
def get_user_by_phone(db: Session, phone: str):
    return db.query(User).filter(User.usernumber == phone.strip()).first()
# :mag: Get user by name (username - case-insensitive)
def get_user_by_name(db: Session, name):
    if not isinstance(name, str):
        return None
    return db.query(User).filter(User.username.ilike(f"%{name.strip()}%")).first()

# :mag: Get lead by company (case-insensitive, partial match)
def get_lead_by_company(db: Session, company_name: str):
    return db.query(models.Lead).filter(
        func.lower(models.Lead.company_name).like(f"%{company_name.strip().lower()}%")
    ).first()


# :floppy_disk: Create a new lead - checks assigned_to by name or number
def save_lead(
    db: Session,
    lead: schemas.LeadCreate,
    created_by: str,
    assigned_name: str = None,
    assigned_number: str = None
):
    assigned_user = None
    # Try to find by name
    if assigned_name:
        assigned_user = get_user_by_name(db, assigned_name)
    # If not found by name, try number
    if not assigned_user and assigned_number:
        assigned_user = get_user_by_phone(db, assigned_number)
    # If still not found, raise error
    if not assigned_user:
        raise ValueError(
            f"Assigned user not found by name '{assigned_name}' or number '{assigned_number}'"
        )
    db_lead = models.Lead(
        company_name=lead.company_name,
        contact_name=lead.contact_name,
        phone=lead.phone,
        email=lead.email,
        address=lead.address,
        team_size=lead.team_size,
        source=lead.source,
        segment=lead.segment,
        remark=lead.remark,
        created_by=created_by,
        assigned_to=assigned_user.username,
        created_at=datetime.utcnow()
    )
    db.add(db_lead)
    db.commit()
    db.refresh(db_lead)
    return db_lead
# :arrows_counterclockwise: Update lead status and add status log
def update_lead_status(
    db: Session,
    lead_id: int,
    status: str,
    updated_by: str,
    remark: str = None
):
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if lead:
        lead.status = status
        if remark:
            lead.remark = remark
        db_status = models.StatusLog(
            lead_id=lead_id,
            status=status,
            updated_by=updated_by,
            created_at=datetime.utcnow()
        )
        db.add(db_status)
        db.commit()
        db.refresh(lead)
    return lead
# :date: Create a new event (Meeting or Demo)
def create_event(db: Session, event: schemas.EventCreate):
    db_event = models.Event(
        lead_id=event.lead_id,
        assigned_to=event.assigned_to,
        event_type=event.event_type,
        event_time=event.event_time,
        created_by=event.created_by,
        remark=event.remark,
        created_at=datetime.utcnow()
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event
# :pushpin: Alias
create_lead = save_lead