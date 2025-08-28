# app/crud.py
from datetime import datetime, date
from typing import Optional, Union, List
from sqlalchemy.orm import Session
import re
from sqlalchemy import func, union_all, literal_column
from app import models, schemas
from app.schemas import UserCreate, UserPasswordChange, LeadCreate, LeadUpdateWeb, EventCreate, UserUpdate,HistoryItemOut,ContactCreate,ActivityLogCreate,AssignmentLogCreate,ReminderCreate
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
    Creates a new Lead and its initial Contact person.
    The `created_by` value is now correctly taken from the lead_data object.
    """
    assigned_user = get_user_by_name(db, lead_data.assigned_to)
    if not assigned_user:
        raise ValueError(f"Assigned user not found by name '{lead_data.assigned_to}'")

    db_lead = models.Lead(
        company_name=lead_data.company_name,
        source=lead_data.source,
        created_by=lead_data.created_by,
        assigned_to=assigned_user.username,
        email=lead_data.email,
        address=lead_data.address,
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
    db.commit()
    db.refresh(db_lead)

    for contact_data in lead_data.contacts:
        db_contact = models.Contact(
            lead_id=db_lead.id,
            contact_name=contact_data.contact_name,
            phone=contact_data.phone,
            email=contact_data.email,
            designation=contact_data.designation
        )
        db.add(db_contact)
    
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
    Updates a lead and its associated contacts.
    This function uses a "delete and recreate" strategy for contacts to ensure consistency.
    """
    db_lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not db_lead:
        return None

    update_data = lead_data.model_dump(exclude_unset=True)
    contacts_data = update_data.pop("contacts", None)

    for key, value in update_data.items():
        if hasattr(db_lead, key):
            setattr(db_lead, key, value)
    
    db_lead.updated_at = datetime.utcnow()

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

    db.commit()
    db.refresh(db_lead)
    return db_lead


def update_lead_status(db: Session, lead_id: int, status: str, updated_by: str, remark: str = None):
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if lead:
        old_status = lead.status
        lead.status = status
        if remark:
            if lead.remark: lead.remark += f"\n--\nStatus Update: {remark}"
            else: lead.remark = f"Status Update: {remark}"
        activity_details = f"Status changed from '{old_status}' to '{status}' by {updated_by}."
        if remark: activity_details += f" Remark: {remark}"
        create_activity_log(db, activity=ActivityLogCreate(lead_id=lead.id, phase=status, details=activity_details))
        db.commit()
        db.refresh(lead)
    return lead

def create_event(db: Session, event: EventCreate):
    db_event = models.Event(lead_id=event.lead_id, assigned_to=event.assigned_to, event_type=event.event_type, event_time=event.event_time, event_end_time=event.event_end_time, created_by=event.created_by, remark=event.remark, created_at=datetime.now())
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
    db_activity = models.ActivityLog(lead_id=activity.lead_id, phase=activity.phase, details=activity.details)
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
    meeting_conflict_query = db.query(Event).filter(Event.assigned_to == username, Event.event_time < end_time, Event.event_end_time > start_time, Event.phase == "Scheduled")
    if exclude_event_id: meeting_conflict_query = meeting_conflict_query.filter(Event.id != exclude_event_id)
    conflicting_meeting = meeting_conflict_query.first()
    if conflicting_meeting: return conflicting_meeting
    demo_conflict_query = db.query(Demo).filter(Demo.assigned_to == user_phone, Demo.start_time < end_time, Demo.event_end_time > start_time, Demo.phase == "Scheduled")
    if exclude_demo_id: demo_conflict_query = demo_conflict_query.filter(Demo.id != exclude_demo_id)
    conflicting_demo = demo_conflict_query.first()
    if conflicting_demo: return conflicting_demo
    return None

def create_reminder(db: Session, reminder_data: ReminderCreate):
    new_reminder = models.Reminder(lead_id=reminder_data.lead_id, user_id=reminder_data.user_id, assigned_to=reminder_data.assigned_to, remind_time=reminder_data.remind_time, message=reminder_data.message, status="pending", created_at=datetime.utcnow())
    db.add(new_reminder)
    db.commit()
    db.refresh(new_reminder)
    return new_reminder

def get_scheduled_meetings(db: Session) -> list[models.Event]:
    return db.query(models.Event).filter(models.Event.event_type == "Meeting", models.Event.phase == "Scheduled").order_by(models.Event.event_time.asc()).all()

def get_scheduled_demos(db: Session) -> list[models.Demo]:
    return db.query(models.Demo).filter(models.Demo.phase == "Scheduled").order_by(models.Demo.start_time.asc()).all()



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

def get_pending_discussion_reminders(db: Session) -> list[models.Reminder]:
    """
    Retrieves all reminders from the database that are currently pending and
    contain the word 'discussion' in their message.
    """
    return db.query(models.Reminder).filter(
        models.Reminder.status == 'pending',
        models.Reminder.message.like('%discussion for%')
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