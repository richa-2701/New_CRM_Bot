# app/crud.py
from datetime import datetime, date
from typing import Optional, Union, List
from sqlalchemy.orm import Session, aliased
import re
from sqlalchemy import func, union_all, literal_column, case 
from app import models, schemas
from app.schemas import (
    UserCreate, UserPasswordChange, LeadCreate, LeadUpdateWeb, EventCreate, 
    UserUpdate, HistoryItemOut, ContactCreate, ActivityLogCreate, 
    AssignmentLogCreate, ReminderCreate, ActivityLogUpdate
)
from app.models import User, Event, ActivityLog, Lead, AssignmentLog, Demo, Contact,LeadDripAssignment, SentDripMessageLog, DripSequenceStep 

def create_user(db: Session, user: UserCreate):
    db_user = models.User(
        username=user.username,
        usernumber=user.usernumber,
        email=user.email,
        department=user.department,
        password=user.password,
        role=user.role
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def get_user_by_id(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_users(db: Session):
    return db.query(models.User).order_by(models.User.username).all()

def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()

def get_user_by_phone(db: Session, phone: Union[str, int]):
    phone_str = str(phone)
    return db.query(User).filter(User.usernumber == phone_str.strip()).first()

def verify_user(db: Session, username: str, password: str) -> Optional[models.User]:
    user = get_user_by_username(db, username)
    if user and user.password == password:
        return user
    return None

def change_user_password(db: Session, user_data: UserPasswordChange) -> Optional[models.User]:
    user_to_update = verify_user(db, user_data.username, user_data.old_password)
    if not user_to_update: return None
    user_to_update.password = user_data.new_password
    db.commit()
    db.refresh(user_to_update)
    return user_to_update

def update_user(db: Session, user_id: int, user_data: UserUpdate) -> Optional[models.User]:
    db_user = get_user_by_id(db, user_id)
    if not db_user: return None
    update_data = user_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_user, key, value)
    db.commit()
    db.refresh(db_user)
    return db_user

def delete_user(db: Session, user_id: int) -> bool:
    db_user = get_user_by_id(db, user_id)
    if not db_user: return False
    db.delete(db_user)
    db.commit()
    return True

def get_user_by_name(db: Session, name):
    if not isinstance(name, str): return None
    return db.query(User).filter(User.username.ilike(f"%{name.strip()}%")).first()

def get_all_leads(db: Session):
    return db.query(models.Lead).order_by(models.Lead.created_at.desc()).all()

def get_lead_by_id(db: Session, lead_id: int):
    return db.query(models.Lead).filter(models.Lead.id == lead_id).first()

def get_lead_by_company(db: Session, company_name: str):
    return db.query(models.Lead).filter(
        func.lower(models.Lead.company_name).like(f"%{company_name.strip().lower()}%")
    ).first()

def get_tasks_by_username(db: Session, username: str):
    user = get_user_by_username(db, username)
    if not user: return []
    meetings_query = db.query(Event.id.label("id"), Event.lead_id.label("lead_id"), Event.event_type.label("event_type"), Event.event_time.label("event_time"), Event.remark.label("remark")).filter(Event.assigned_to == user.username)
    demos_query = db.query(Demo.id.label("id"), Demo.lead_id.label("lead_id"), literal_column("'Demo'").label("event_type"), Demo.start_time.label("event_time"), Demo.remark.label("remark")).filter(Demo.assigned_to == user.usernumber)
    all_tasks_cte = union_all(meetings_query, demos_query).cte("all_tasks")
    results = db.query(all_tasks_cte, Lead.company_name).outerjoin(Lead, all_tasks_cte.c.lead_id == Lead.id).order_by(all_tasks_cte.c.event_time.desc()).all()
    return results

def get_activities_by_lead_id(db: Session, lead_id: int):
    return db.query(ActivityLog).filter(ActivityLog.lead_id == lead_id).order_by(ActivityLog.created_at.desc()).all()

def get_lead_history(db: Session, lead_id: int) -> list[HistoryItemOut]:
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead: return []
    history = []
    creator = get_user_by_phone(db, lead.created_by) or get_user_by_name(db, lead.created_by)
    creator_name = creator.username if creator else lead.created_by
    history.append(HistoryItemOut(timestamp=lead.created_at, event_type="Lead Creation", details=f"Lead created and assigned to {lead.assigned_to}.", user=creator_name))
    activities = db.query(ActivityLog).filter(ActivityLog.lead_id == lead_id).all()
    for activity in activities:
        user_match = re.search(r"by (.+?)(?:\.|$)", activity.details)
        user = user_match.group(1).strip() if user_match else "System"
        history.append(HistoryItemOut(timestamp=activity.created_at, event_type="Activity / Status Change", details=activity.details, user=user))
    assignments = db.query(AssignmentLog).filter(AssignmentLog.lead_id == lead_id).all()
    for assign in assignments:
        assigner = get_user_by_phone(db, assign.assigned_by) or get_user_by_name(db, assign.assigned_by)
        assigner_name = assigner.username if assigner else assign.assigned_by
        history.append(HistoryItemOut(timestamp=assign.assigned_at, event_type="Reassignment", details=f"Lead reassigned to {assign.assigned_to}.", user=assigner_name))
    history.sort(key=lambda item: item.timestamp, reverse=True)
    return history

# --- THIS IS THE CORRECTED AND FINAL save_lead FUNCTION ---
def save_lead(db: Session, lead_data: LeadCreate) -> models.Lead:
    """
    Creates a new Lead and its initial Contact person(s).
    This function is now robust against missing optional contact fields.
    """
    assigned_user = get_user_by_name(db, lead_data.assigned_to)
    if not assigned_user:
        raise ValueError(f"Assigned user not found by name '{lead_data.assigned_to}'")

    # Create the main Lead object without the contacts first
    db_lead = models.Lead(
        company_name=lead_data.company_name,
        source=lead_data.source,
        created_by=lead_data.created_by,
        assigned_to=assigned_user.username,
        email=lead_data.email,
        address=lead_data.address,
        address_2=lead_data.address_2,
        city=lead_data.city,
        state=lead_data.state,
        pincode=lead_data.pincode,
        country=lead_data.country,
        team_size=str(lead_data.team_size) if lead_data.team_size else None,
        segment=lead_data.segment,
        remark=lead_data.remark,
        lead_type=lead_data.lead_type,
        phone_2=lead_data.phone_2,
        turnover=lead_data.turnover,
        current_system=lead_data.current_system,
        machine_specification=lead_data.machine_specification,
        challenges=lead_data.challenges,
        created_at=datetime.now()
    )
    
    db.add(db_lead)
    # Commit here to get an ID for the lead, which is needed for the contacts
    db.commit()
    db.refresh(db_lead)

    # Now, loop through the contact data and add contacts
    for contact_pydantic in lead_data.contacts:
        # Convert the Pydantic model to a dictionary to safely access its values
        contact_dict = contact_pydantic.model_dump()
        
        # Create a SQLAlchemy Contact model using .get() for safety.
        # .get('key') will return None if the key doesn't exist, preventing the AttributeError.
        db_contact = models.Contact(
            lead_id=db_lead.id,
            contact_name=contact_dict.get('contact_name'),
            phone=contact_dict.get('phone'),
            email=contact_dict.get('email'),
            designation=contact_dict.get('designation')
        )
        db.add(db_contact)
    
    # Commit again to save the contacts
    db.commit()
    db.refresh(db_lead)
    
    return db_lead
# --- END CORRECTION ---

def create_contact_for_lead(db: Session, lead_id: int, contact: ContactCreate) -> models.Contact:
    db_contact = models.Contact(**contact.model_dump(), lead_id=lead_id)
    db.add(db_contact)
    db.commit()
    db.refresh(db_contact)
    return db_contact

def get_contacts_by_lead_id(db: Session, lead_id: int) -> List[models.Contact]:
    return db.query(models.Contact).filter(models.Contact.lead_id == lead_id).all()

def update_lead(db: Session, lead_id: int, lead_data: LeadUpdateWeb):
    """
    Updates a lead and its contacts, and correctly logs a single, accurate activity.
    """
    db_lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not db_lead:
        return None

    update_data = lead_data.model_dump(exclude_unset=True)
    
    # --- STEP 1: Separate the special fields from the simple ones ---
    contacts_data = update_data.pop("contacts", None)
    new_status = update_data.pop("status", None)
    activity_details = update_data.pop("activity_details", None)
    activity_type = update_data.pop("activity_type", "General")
    
    # --- STEP 2: Update all the simple, direct fields on the lead model ---
    for key, value in update_data.items():
        if hasattr(db_lead, key):
            setattr(db_lead, key, value)
    
    db_lead.updated_at = datetime.utcnow()

    # --- STEP 3: Handle contact updates (delete and recreate for simplicity) ---
    if contacts_data is not None:
        db.query(Contact).filter(Contact.lead_id == lead_id).delete(synchronize_session=False)
        for contact_info in contacts_data:
            new_contact = Contact(
                lead_id=db_lead.id,
                contact_name=contact_info.get("contact_name"),
                phone=contact_info.get("phone"),
                email=contact_info.get("email"),
                designation=contact_info.get("designation")
            )
            db.add(new_contact)

    # --- STEP 4: Centralized and intelligent activity logging ---
    # We prioritize the status change log, as it's the most important event.
    if new_status and new_status != db_lead.status:
        # If the status is different, call the specialized function.
        # It handles both the status update and the logging in one go.
        # We pass `activity_details` as the remark for a richer log message.
        update_lead_status(
            db=db,
            lead_id=lead_id,
            status=new_status,
            updated_by="System", # Replace with actual user if available
            remark=activity_details
        )
    elif activity_details:
        # ONLY if the status did NOT change, but we have new notes,
        # we log a simple activity.
        create_activity_log(db, ActivityLogCreate(
            lead_id=lead_id,
            phase=db_lead.status, # Log against the current status
            details=activity_details,
            activity_type=activity_type
        ))

    db.commit()
    db.refresh(db_lead)
    return db_lead



def update_lead_status(db: Session, lead_id: int, status: str, updated_by: str, remark: str = None):
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if lead:
        old_status = lead.status
        lead.status = status
        
        # Construct the activity details. Start with the status change.
        activity_details = f"Status changed from '{old_status}' to '{status}' by {updated_by}."
        
        # If a remark (from activity_details) was also provided, append it.
        if remark:
            activity_details += f"\nNote: {remark}"
        
        # Create a single, comprehensive log entry.
        create_activity_log(db, ActivityLogCreate(
            lead_id=lead.id, 
            phase=status, 
            details=activity_details,
        )) 
        # Note: We do not need to commit here because the calling function (`update_lead`) will commit.
    return lead

def create_event(db: Session, event: EventCreate):
    db_event = models.Event(
        lead_id=event.lead_id, 
        assigned_to=event.assigned_to, 
        event_type=event.event_type, 
        event_time=event.event_time, 
        event_end_time=event.event_end_time, 
        created_by=event.created_by, 
        remark=event.remark, 
        created_at=datetime.now(),
        phase="Scheduled"  # <-- THE CRITICAL FIX IS ADDING THIS LINE
    )
    
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

def complete_meeting(db: Session, meeting_id: int, notes: str, updated_by: str) -> Optional[models.Event]:
    event = db.query(models.Event).filter(models.Event.id == meeting_id, models.Event.event_type == "Meeting").first()
    if not event: return None
    event.phase = "Done"
    event.remark = notes
    update_lead_status(db, lead_id=event.lead_id, status="Meeting Done", updated_by=updated_by, remark=notes)
    db.commit()
    db.refresh(event)
    return event

def complete_demo(db: Session, demo_id: int, notes: str, updated_by: str) -> Optional[models.Demo]:
    demo = db.query(models.Demo).filter(models.Demo.id == demo_id).first()
    if not demo: return None
    demo.phase = "Done"
    demo.remark = notes
    update_lead_status(db, lead_id=demo.lead_id, status="Demo Done", updated_by=updated_by, remark=notes)
    db.commit()
    db.refresh(demo)
    return demo

def create_activity_log(db: Session, activity: ActivityLogCreate):
    db_activity = models.ActivityLog(
        lead_id=activity.lead_id, 
        phase=activity.phase, 
        details=activity.details,
        activity_type=activity.activity_type,
        created_at=datetime.utcnow()  # Explicitly set consistent timestamp
    )
    db.add(db_activity)
    db.commit()
    db.refresh(db_activity)
    return db_activity

def create_assignment_log(db: Session, log: AssignmentLogCreate):
    db_log = models.AssignmentLog(lead_id=log.lead_id, assigned_to=log.assigned_to, assigned_by=log.assigned_by)
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log

def is_user_available(db: Session, username: str, user_phone: str, start_time: datetime, end_time: datetime, exclude_event_id: int = None, exclude_demo_id: int = None) -> Optional[Union[Event, Demo]]:
    """
    Checks for conflicting events in a database-agnostic way by making all datetimes 
    timezone-naive before comparison. This works reliably on SQLite, PostgreSQL, and MySQL.
    """
    # CRITICAL FIX: Convert the incoming timezone-aware datetimes from the request
    # into timezone-naive datetimes. This allows for a direct, "apples-to-apples" 
    # comparison with the naive datetimes stored in your database.
    start_time_naive = start_time.replace(tzinfo=None)
    end_time_naive = end_time.replace(tzinfo=None)

    # --- Check for conflicting MEETINGS (assigned by username) ---
    meeting_conflict_query = db.query(models.Event).filter(
        models.Event.assigned_to == username,
        models.Event.event_time < end_time_naive,        # Compare naive to naive
        models.Event.event_end_time > start_time_naive,   # Compare naive to naive
        models.Event.phase == "Scheduled"
    )
    if exclude_event_id:
        meeting_conflict_query = meeting_conflict_query.filter(models.Event.id != exclude_event_id)
    
    conflicting_meeting = meeting_conflict_query.first()
    if conflicting_meeting:
        return conflicting_meeting

    # --- Check for conflicting DEMOS (assigned by usernumber/phone) ---
    demo_conflict_query = db.query(models.Demo).filter(
        models.Demo.assigned_to == user_phone,
        models.Demo.start_time < end_time_naive,          # Compare naive to naive
        models.Demo.event_end_time > start_time_naive,    # Compare naive to naive
        models.Demo.phase == "Scheduled"
    )
    if exclude_demo_id:
        demo_conflict_query = demo_conflict_query.filter(models.Demo.id != exclude_demo_id)
        
    conflicting_demo = demo_conflict_query.first()
    if conflicting_demo:
        return conflicting_demo

    # If no conflicts are found, the user is available
    return None


def create_reminder(db: Session, reminder_data: schemas.ReminderCreate): # This is now the definitive version
    """Creates a new reminder in the database."""
    
    # Get the user to link the reminder correctly
    user = get_user_by_id(db, reminder_data.user_id)
    if not user:
        # This case should ideally not happen if created_by_user_id is validated
        return None

    new_reminder = models.Reminder(
        lead_id=reminder_data.lead_id,
        user_id=reminder_data.user_id,
        assigned_to=user.username, # Assign to the creator by default
        remind_time=reminder_data.remind_time,
        message=reminder_data.message,
        activity_type=reminder_data.activity_type,
        status="pending",
        created_at=datetime.utcnow()
    )
    db.add(new_reminder)
    db.commit()
    db.refresh(new_reminder)
    return new_reminder

def get_scheduled_meetings(db: Session) -> list[models.Event]:
    return db.query(models.Event).filter(models.Event.event_type == "Meeting", models.Event.phase == "Scheduled").order_by(models.Event.event_time.asc()).all()

def get_all_meetings(db: Session) -> list[models.Event]:
    """Fetches all meetings, regardless of their phase (Scheduled, Done, etc.)."""
    return db.query(models.Event).filter(models.Event.event_type == "Meeting").order_by(models.Event.event_time.desc()).all()

def get_scheduled_demos(db: Session) -> list[models.Demo]:
    return db.query(models.Demo).filter(models.Demo.phase == "Scheduled").order_by(models.Demo.start_time.asc()).all()

def get_all_demos(db: Session) -> list[models.Demo]:
    """Fetches all demos, regardless of their phase."""
    return db.query(models.Demo).order_by(models.Demo.start_time.desc()).all()

def get_message_by_id(db: Session, message_id: int):
    return db.query(models.MessageMaster).filter(models.MessageMaster.id == message_id).first()

def get_all_messages(db: Session):
    return db.query(models.MessageMaster).order_by(models.MessageMaster.message_name).all()

def create_message(db: Session, message: schemas.MessageMasterCreate):
    db_message = models.MessageMaster(**message.model_dump())
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

def update_message(db: Session, message_id: int, message_data: schemas.MessageMasterUpdate):
    db_message = get_message_by_id(db, message_id)
    if not db_message:
        return None
    for key, value in message_data.model_dump().items():
        setattr(db_message, key, value)
    db.commit()
    db.refresh(db_message)
    return db_message

def delete_message(db: Session, message_id: int):
    db_message = get_message_by_id(db, message_id)
    if not db_message:
        return False
    db.delete(db_message)
    db.commit()
    return True

# --- Drip Sequence CRUD ---
def get_drip_sequence_by_id(db: Session, drip_id: int):
    return db.query(models.DripSequence).filter(models.DripSequence.id == drip_id).first()

def get_all_drip_sequences(db: Session):
    return db.query(models.DripSequence).order_by(models.DripSequence.drip_name).all()

def create_drip_sequence(db: Session, drip: schemas.DripSequenceCreate):
    # Create the main drip sequence record
    db_drip = models.DripSequence(drip_name=drip.drip_name, created_by=drip.created_by)
    db.add(db_drip)
    db.flush() # Use flush to get the ID of the new drip sequence before committing

    # Create all the step records and link them
    for step_data in drip.steps:
        db_step = models.DripSequenceStep(
            **step_data.model_dump(),
            drip_sequence_id=db_drip.id
        )
        db.add(db_step)

    db.commit()
    db.refresh(db_drip)
    return db_drip

def update_drip_sequence(db: Session, drip_id: int, drip_data: schemas.DripSequenceCreate):
    db_drip = get_drip_sequence_by_id(db, drip_id)
    if not db_drip:
        return None
        
    # Update the name
    db_drip.drip_name = drip_data.drip_name
    
    # Easiest way to handle step updates: delete old ones and create new ones
    db.query(models.DripSequenceStep).filter(models.DripSequenceStep.drip_sequence_id == drip_id).delete()
    
    for step_data in drip_data.steps:
        db_step = models.DripSequenceStep(**step_data.model_dump(), drip_sequence_id=drip_id)
        db.add(db_step)
        
    db.commit()
    db.refresh(db_drip)
    return db_drip

def delete_drip_sequence(db: Session, drip_id: int):
    db_drip = get_drip_sequence_by_id(db, drip_id)
    if not db_drip:
        return False
    db.delete(db_drip) # Cascade delete will handle the steps
    db.commit()
    return True


def find_and_complete_reminder(db: Session, lead_id: int, message_like: str) -> bool:
    """
    Finds the most recent pending reminder for a lead that matches a message pattern
    and updates its status to 'completed'.
    """
    reminder_to_complete = db.query(models.Reminder).filter(
        models.Reminder.lead_id == lead_id,
        models.Reminder.message.like(f"%{message_like}%"),
        models.Reminder.status == 'pending'
    ).order_by(models.Reminder.remind_time.desc()).first()

    if reminder_to_complete:
        reminder_to_complete.status = 'completed'
        db.commit()
        return True
    
    return False

def get_pending_reminders(db: Session) -> list[models.Reminder]:
    """
    Retrieves all reminders from the database that are currently pending.
    This is used to get all scheduled activities.
    """
    return db.query(models.Reminder).filter(
        models.Reminder.status == 'pending'
    ).order_by(models.Reminder.remind_time.asc()).all()

def assign_drip_to_lead(db: Session, lead_id: int, drip_sequence_id: int) -> LeadDripAssignment:
    """Assigns a drip sequence to a lead and deactivates any previous ones."""
    # Deactivate any existing active drips for this lead
    db.query(LeadDripAssignment)\
      .filter(LeadDripAssignment.lead_id == lead_id, LeadDripAssignment.is_active == True)\
      .update({"is_active": False})

    # Create the new assignment
    new_assignment = LeadDripAssignment(
        lead_id=lead_id,
        drip_sequence_id=drip_sequence_id,
        start_date=date.today()
    )
    db.add(new_assignment)
    db.commit()
    db.refresh(new_assignment)
    return new_assignment

def get_active_drip_assignments(db: Session) -> List[LeadDripAssignment]:
    """Gets all currently active drip assignments."""
    return db.query(LeadDripAssignment).filter(LeadDripAssignment.is_active == True).all()

def log_sent_drip_message(db: Session, assignment_id: int, step_id: int):
    """Logs that a specific drip message has been sent."""
    log_entry = SentDripMessageLog(assignment_id=assignment_id, step_id=step_id)
    db.add(log_entry)
    db.commit()

def get_sent_step_ids_for_assignment(db: Session, assignment_id: int) -> List[int]:
    """Returns a list of step IDs that have already been sent for an assignment."""
    sent_steps = db.query(SentDripMessageLog.step_id)\
                   .filter(SentDripMessageLog.assignment_id == assignment_id)\
                   .all()
    return [step_id for (step_id,) in sent_steps]

def complete_scheduled_activity(db: Session, reminder_id: int, notes: str, updated_by: str) -> Optional[models.Reminder]:
    """
    Finds a pending reminder (scheduled activity), marks it as 'completed',
    and creates a new entry in the ActivityLog table.
    """
    reminder_to_complete = db.query(models.Reminder).filter(
        models.Reminder.id == reminder_id,
        models.Reminder.status == 'pending'
    ).first()

    if not reminder_to_complete:
        return None

    # 1. Update the reminder's status
    reminder_to_complete.status = 'completed'

    # 2. Create a new ActivityLog entry from the completed reminder
    # We combine the original message with the new outcome notes.
    activity_details = f"{reminder_to_complete.message}\n---\nOutcome: {notes}"
    
    new_activity_log = models.ActivityLog(
        lead_id=reminder_to_complete.lead_id,
        phase="Discussion Done",  # Or another appropriate status
        details=f"{activity_details} - Marked as done by {updated_by}"
    )
    db.add(new_activity_log)
    
    # 3. Commit all changes to the database
    db.commit()
    db.refresh(reminder_to_complete)
    
    return reminder_to_complete

def get_all_unified_activities(db: Session, username: str, is_admin: bool) -> List[any]:
    """
    Fetches a unified list of all activities, combining logged activities
    from ActivityLog and scheduled activities from Reminder.
    """
    # Query for logged activities
    logged_activities_query = db.query(
        ActivityLog.id.label("id"),
        literal_column("'log'").label("type"),
        ActivityLog.lead_id.label("lead_id"),
        Lead.company_name.label("company_name"),
        
        case(
            (ActivityLog.activity_type != None, ActivityLog.activity_type),
            else_=literal_column("'General'")
        ).label("activity_type"),

        ActivityLog.details.label("details"),
        ActivityLog.phase.label("status"),
        ActivityLog.created_at.label("created_at"),
        literal_column("NULL").label("scheduled_for")
    ).join(Lead, Lead.id == ActivityLog.lead_id)

    # Query for scheduled activities (reminders)
    scheduled_activities_query = db.query(
        models.Reminder.id.label("id"),
        literal_column("'reminder'").label("type"),
        models.Reminder.lead_id.label("lead_id"),
        Lead.company_name.label("company_name"),
        
        case(
            (models.Reminder.activity_type != None, models.Reminder.activity_type),
            else_=literal_column("'Follow-up'")
        ).label("activity_type"),
        
        models.Reminder.message.label("details"),
        models.Reminder.status.label("status"),
        models.Reminder.created_at.label("created_at"),
        models.Reminder.remind_time.label("scheduled_for")
    ).join(Lead, Lead.id == models.Reminder.lead_id)

    if not is_admin:
        logged_activities_query = logged_activities_query.filter(Lead.assigned_to == username)
        # --- THIS IS THE FIX ---
        # Scheduled activities must be filtered by who they are assigned to in the Reminder table, not the Lead table.
        scheduled_activities_query = scheduled_activities_query.filter(models.Reminder.assigned_to == username)

    unified_query = union_all(logged_activities_query, scheduled_activities_query).alias("unified")
    results = db.query(unified_query).order_by(unified_query.c.created_at.desc()).all()
    return results


def reschedule_meeting(db: Session, meeting_id: int, start_time: datetime, end_time: datetime, updated_by: str) -> Optional[models.Event]:
    # --- FIX: Allow rescheduling if the event is 'Scheduled' OR 'Rescheduled' ---
    event = db.query(models.Event).filter(
        models.Event.id == meeting_id,
        models.Event.phase.in_(["Scheduled", "Rescheduled"])
    ).first()

    if not event:
        return None

    old_time = event.event_time.strftime('%Y-%m-%d %H:%M')
    new_time = start_time.strftime('%Y-%m-%d %H:%M')

    event.event_time = start_time
    event.event_end_time = end_time
    event.phase = "Rescheduled"

    create_activity_log(db, ActivityLogCreate(
        lead_id=event.lead_id,
        phase="Rescheduled",
        details=f"Meeting rescheduled from {old_time} to {new_time} by {updated_by}."
    ))
    db.commit()
    db.refresh(event)
    return event

def reassign_meeting(db: Session, meeting_id: int, new_assignee: User, updated_by: str) -> Optional[models.Event]:
    event = db.query(models.Event).filter(models.Event.id == meeting_id, models.Event.phase.in_(["Scheduled", "Rescheduled"])).first()
    if not event:
        return None
        
    old_assignee = event.assigned_to
    event.assigned_to = new_assignee.username
    
    create_activity_log(db, ActivityLogCreate(
        lead_id=event.lead_id,
        phase="Reassigned",
        details=f"Meeting reassigned from {old_assignee} to {new_assignee.username} by {updated_by}."
    ))
    db.commit()
    db.refresh(event)
    return event

def cancel_meeting(db: Session, meeting_id: int, reason: str, updated_by: str) -> Optional[models.Event]:
    event = db.query(models.Event).filter(models.Event.id == meeting_id, models.Event.phase.in_(["Scheduled", "Rescheduled"])).first()
    if not event:
        return None
        
    event.phase = "Canceled"
    event.remark = f"Canceled by {updated_by}. Reason: {reason}"
    
    create_activity_log(db, ActivityLogCreate(
        lead_id=event.lead_id,
        phase="Canceled",
        details=f"Meeting canceled by {updated_by}. Reason: {reason}"
    ))
    db.commit()
    db.refresh(event)
    return event

def update_meeting_notes(db: Session, meeting_id: int, notes: str, updated_by: str) -> Optional[models.Event]:
    event = db.query(models.Event).filter(models.Event.id == meeting_id, models.Event.phase == "Done").first()
    if not event:
        return None
    
    event.remark = notes # Overwrites old notes
    # Optionally, log this change as well
    create_activity_log(db, ActivityLogCreate(
        lead_id=event.lead_id,
        phase="Notes Updated",
        details=f"Meeting notes updated by {updated_by}."
    ))
    db.commit()
    db.refresh(event)
    return event

# --- NEW: CRUD Functions for Event (Demo) Modifications ---

def reschedule_demo(db: Session, demo_id: int, start_time: datetime, end_time: datetime, updated_by: str) -> Optional[models.Demo]:
    # --- FIX: Allow rescheduling if the demo is 'Scheduled' OR 'Rescheduled' ---
    demo = db.query(models.Demo).filter(
        models.Demo.id == demo_id,
        models.Demo.phase.in_(["Scheduled", "Rescheduled"])
    ).first()

    if not demo: return None

    old_time = demo.start_time.strftime('%Y-%m-%d %H:%M')
    new_time = start_time.strftime('%Y-%m-%d %H:%M')

    demo.start_time = start_time
    demo.event_end_time = end_time
    demo.phase = "Rescheduled"

    create_activity_log(db, ActivityLogCreate(lead_id=demo.lead_id, phase="Rescheduled", details=f"Demo rescheduled from {old_time} to {new_time} by {updated_by}."))
    db.commit()
    db.refresh(demo)
    return demo

def reassign_demo(db: Session, demo_id: int, new_assignee: User, updated_by: str) -> Optional[models.Demo]:
    demo = db.query(models.Demo).filter(models.Demo.id == demo_id, models.Demo.phase.in_(["Scheduled", "Rescheduled"])).first()
    if not demo: return None
        
    old_assignee_num = demo.assigned_to
    demo.assigned_to = new_assignee.usernumber
    
    create_activity_log(db, ActivityLogCreate(lead_id=demo.lead_id, phase="Reassigned", details=f"Demo reassigned from user number {old_assignee_num} to {new_assignee.username} by {updated_by}."))
    db.commit()
    db.refresh(demo)
    return demo

def cancel_demo(db: Session, demo_id: int, reason: str, updated_by: str) -> Optional[models.Demo]:
    demo = db.query(models.Demo).filter(models.Demo.id == demo_id, models.Demo.phase.in_(["Scheduled", "Rescheduled"])).first()
    if not demo: return None
        
    demo.phase = "Canceled"
    demo.remark = f"Canceled by {updated_by}. Reason: {reason}"
    
    create_activity_log(db, ActivityLogCreate(lead_id=demo.lead_id, phase="Canceled", details=f"Demo canceled by {updated_by}. Reason: {reason}"))
    db.commit()
    db.refresh(demo)
    return demo

def update_demo_notes(db: Session, demo_id: int, notes: str, updated_by: str) -> Optional[models.Demo]:
    demo = db.query(models.Demo).filter(models.Demo.id == demo_id, models.Demo.phase == "Done").first()
    if not demo: return None
    
    demo.remark = notes
    create_activity_log(db, ActivityLogCreate(lead_id=demo.lead_id, phase="Notes Updated", details=f"Demo notes updated by {updated_by}."))
    db.commit()
    db.refresh(demo)
    return demo

# --- NEW: CRUD Functions for Activity Management ---

def update_activity_log(db: Session, activity_id: int, activity_data: ActivityLogUpdate) -> Optional[models.ActivityLog]:
    db_activity = db.query(models.ActivityLog).filter(models.ActivityLog.id == activity_id).first()
    if not db_activity:
        return None
    
    db_activity.details = activity_data.details
    if activity_data.activity_type:
        db_activity.activity_type = activity_data.activity_type

    db.commit()
    db.refresh(db_activity)
    return db_activity

def delete_activity_log(db: Session, activity_id: int) -> bool:
    db_activity = db.query(models.ActivityLog).filter(models.ActivityLog.id == activity_id).first()
    if not db_activity:
        return False
    db.delete(db_activity)
    db.commit()
    return True

def delete_reminder(db: Session, reminder_id: int) -> bool:
    # We can "cancel" a scheduled activity by simply deleting the reminder
    db_reminder = db.query(models.Reminder).filter(models.Reminder.id == reminder_id, models.Reminder.status == 'pending').first()
    if not db_reminder:
        return False
    db.delete(db_reminder)
    db.commit()
    return True


def get_all_leads_with_last_activity(db: Session):
    """
    Fetches all leads and joins them with their most recent activity log.
    This is done efficiently using a window function to avoid N+1 query problems.
    """
    # 1. Create a subquery to find the latest activity for each lead
    latest_activity_subquery = db.query(
        ActivityLog,
        func.row_number().over(
            partition_by=ActivityLog.lead_id,
            order_by=ActivityLog.created_at.desc()
        ).label("row_num")
    ).subquery()

    # Alias the subquery so we can refer to its columns
    latest_activity = aliased(ActivityLog, latest_activity_subquery)

    # 2. Query all leads and LEFT JOIN them with the latest activity
    results = db.query(
        Lead,
        latest_activity
    ).outerjoin(
        latest_activity,
        (Lead.id == latest_activity.lead_id) & (latest_activity_subquery.c.row_num == 1)
    ).order_by(Lead.created_at.desc()).all()

    # 3. Process the results by directly attaching the activity to the lead object.
    # This is much cleaner and more reliable than converting to a dictionary.
    leads_to_return = []
    for lead, activity in results:
        # Pydantic will use this new attribute during model validation.
        lead.last_activity = activity 
        leads_to_return.append(lead)
        
    return leads_to_return
