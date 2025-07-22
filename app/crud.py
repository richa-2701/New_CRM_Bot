# app/crud.py
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from app import models, schemas
from app.models import User, Event, ActivityLog

def create_user(db: Session, user: schemas.UserCreate):
    db_user = models.User(
        username=user.username,
        usernumber=user.usernumber,
        email=user.email,
        department=user.department,
        password=user.password  
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()


def get_user_by_phone(db: Session, phone: str):
    return db.query(User).filter(User.usernumber == phone.strip()).first()
# :mag: Get user by name (username - case-insensitive)

def verify_user(db: Session, username: str, password: str):
    user = get_user_by_username(db, username)
    if user and user.password == password:
        return user
    return None


def get_user_by_name(db: Session, name):
    if not isinstance(name, str):
        return None
    return db.query(User).filter(User.username.ilike(f"%{name.strip()}%")).first()

# :mag: Get lead by company (case-insensitive, partial match)
def get_lead_by_company(db: Session, company_name: str):
    return db.query(models.Lead).filter(
        func.lower(models.Lead.company_name).like(f"%{company_name.strip().lower()}%")
    ).first()


def get_tasks_by_username(db: Session, username: str):
    return db.query(Event).filter(Event.assigned_to == username).order_by(Event.event_time).all()

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
        phone_2=lead.phone_2,
        turnover=lead.turnover,
        current_system=lead.current_system,
        machine_specification=lead.machine_specification,
        challenges=lead.challenges,
        created_at=datetime.utcnow()
    )
    db.add(db_lead)
    db.commit()
    db.refresh(db_lead)

    # --- AUTOMATIC ACTIVITY LOGGING on Lead Creation ---
    activity_details = f"Lead created by {created_by} and assigned to {assigned_user.username}."
    create_activity_log(db, activity=schemas.ActivityLogCreate(lead_id=db_lead.id, phase="New Lead", details=activity_details))

    return db_lead

# :arrows_counterclockwise: Update lead status and add activity log
def update_lead_status(
    db: Session,
    lead_id: int,
    status: str,
    updated_by: str,
    remark: str = None
):
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if lead:
        old_status = lead.status
        lead.status = status
        
        # Add to main remark if provided
        if remark:
            if lead.remark:
                lead.remark += f"\n--\nStatus Update: {remark}"
            else:
                lead.remark = f"Status Update: {remark}"
                
        # --- REMOVED StatusLog CREATION ---
        
        # --- AUTOMATIC ACTIVITY LOGGING on Status Change ---
        activity_details = f"Status changed from '{old_status}' to '{status}' by {updated_by}."
        if remark:
            activity_details += f" Remark: {remark}"
        create_activity_log(db, activity=schemas.ActivityLogCreate(lead_id=lead.id, phase=status, details=activity_details))
        
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

# --- CRUD FUNCTION FOR ACTIVITY LOG ---
def create_activity_log(db: Session, activity: schemas.ActivityLogCreate):
    db_activity = models.ActivityLog(
        lead_id=activity.lead_id,
        phase=activity.phase,
        details=activity.details
    )
    db.add(db_activity)
    db.commit()
    db.refresh(db_activity)
    return db_activity
