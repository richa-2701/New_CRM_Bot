# app/models.py
import enum
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Date
from sqlalchemy.orm import relationship
from app.db import Base

class LeadStatus(str, enum.Enum):
    NEW = "new"
    QUALIFIED = "qualified"
    UNQUALIFIED = "unqualified"
    NOT_OUR_SEGMENT = "not_our_segment"

class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(100), nullable=False)
    usernumber = Column(String(15), unique=True, nullable=False)
    email = Column("Email", String(100), nullable=True)
    department = Column(String(100), nullable=True)
    password = Column("Password", String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    role = Column(String(50), nullable=False, default="Company User")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)
    leads = relationship("Lead", back_populates="assigned_to_user")
    reminders = relationship("Reminder", back_populates="user")
    task_history = relationship("TaskHistory", back_populates="user")

class Contact(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    contact_name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String, nullable=True)
    designation = Column(String, nullable=True) # e.g., "Manager", "IT Head"
    
    # This creates the link back to the Lead model
    lead = relationship("Lead", back_populates="contacts")

class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String, nullable=False)
    source = Column(String, nullable=False)
    created_by = Column(String, nullable=False)
    assigned_to = Column(String, ForeignKey("users.username"), nullable=False)
    email = Column(String, nullable=True)
    address = Column(String, nullable=True)
    segment = Column(String, nullable=True)
    team_size = Column(String, nullable=True)
    remark = Column(Text, nullable=True)
    status = Column(String, default="new")
    lead_type = Column(String, nullable=True)
    phone_2 = Column(String, nullable=True)
    turnover = Column(String, nullable=True)
    current_system = Column(String, nullable=True)
    machine_specification = Column(Text, nullable=True)
    challenges = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    contacts = relationship("Contact", back_populates="lead", cascade="all, delete-orphan")
    assigned_to_user = relationship("User", back_populates="leads")
    meetings = relationship("Meeting", back_populates="lead")
    demos = relationship("Demo", back_populates="lead")
    reminders = relationship("Reminder", back_populates="lead")
    feedbacks = relationship("Feedback", back_populates="lead")
    task_history = relationship("TaskHistory", back_populates="lead")
    AssignmentLogs = relationship("AssignmentLog", back_populates="lead")
    events = relationship("Event", back_populates="lead")
    tasks = relationship("Task", back_populates="lead")
    activities = relationship("ActivityLog", back_populates="lead")
    drip_assignments = relationship("LeadDripAssignment", back_populates="lead")

# (The rest of the models are correct and do not need changes)
class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    phase = Column(String, nullable=False)
    details = Column(Text, nullable=False)
    attachment_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    lead = relationship("Lead", back_populates="activities")

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    task_type = Column(String)
    date_time = Column(DateTime)
    assigned_to = Column(String)
    remark = Column(String)
    status = Column(String, default="pending")
    lead = relationship("Lead", back_populates="tasks")

class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    assigned_to = Column(String)
    event_type = Column(String)
    event_time = Column(DateTime)
    event_end_time = Column(DateTime, nullable=True)
    created_by = Column(String)
    remark = Column(String)
    phase = Column(String, default="Scheduled")
    created_at = Column(DateTime, default=datetime.now)
    lead = relationship("Lead", back_populates="events")

class Reminder(Base):
    __tablename__ = "reminders"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    remind_time = Column(DateTime)
    message = Column(String)
    assigned_to = Column(String)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.now)
    lead = relationship("Lead", back_populates="reminders")
    user = relationship("User", back_populates="reminders")

class TaskHistory(Base):
    __tablename__ = "task_history"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String)
    details = Column(Text)
    timestamp = Column(DateTime, default=datetime.now)
    lead = relationship("Lead", back_populates="task_history")
    user = relationship("User", back_populates="task_history")

class Meeting(Base):
    __tablename__ = "meetings"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    scheduled_by = Column(String)
    assigned_to = Column(String)
    start_time = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    lead = relationship("Lead", back_populates="meetings")

class Demo(Base):
    __tablename__ = "demos"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    scheduled_by = Column(String)
    assigned_to = Column(String)
    start_time = Column(DateTime)
    event_end_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    phase = Column(String, default="Scheduled")
    remark = Column(Text, nullable=True)
    lead = relationship("Lead", back_populates="demos")

class Feedback(Base):
    __tablename__ = "feedbacks"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    feedback_by = Column(String)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    lead = relationship("Lead", back_populates="feedbacks")

class AssignmentLog(Base):
    __tablename__ = "AssignmentLogs"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    assigned_to = Column(String)
    assigned_by = Column(String)
    assigned_at = Column(DateTime, default=datetime.utcnow)
    lead = relationship("Lead", back_populates="AssignmentLogs")


class MessageMaster(Base):
    __tablename__ = "MessageMaster"
    id = Column(Integer, primary_key=True, index=True)
    message_code = Column(String, unique=True, nullable=False, server_default="DEFAULT_CODE") # Handled by DB
    message_name = Column(String, nullable=False)
    message_content = Column(Text, nullable=True)
    message_type = Column(String, nullable=False) # 'text', 'media', 'document'
    attachment_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String, nullable=False)

class DripSequence(Base):
    __tablename__ = "DripSequence"
    id = Column(Integer, primary_key=True, index=True)
    drip_code = Column(String, unique=True, nullable=False, server_default="DEFAULT_CODE") # Handled by DB
    drip_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String, nullable=False)
    steps = relationship("DripSequenceStep", back_populates="drip_sequence", cascade="all, delete-orphan")
    lead_assignments = relationship("LeadDripAssignment", back_populates="drip_sequence")

class DripSequenceStep(Base):
    __tablename__ = "DripSequenceStep"
    id = Column(Integer, primary_key=True, index=True)
    drip_sequence_id = Column(Integer, ForeignKey("DripSequence.id"), nullable=False)
    message_id = Column(Integer, ForeignKey("MessageMaster.id"), nullable=False)
    day_to_send = Column(Integer, nullable=False)
    time_to_send = Column(String, nullable=False) # Storing time as string for simplicity
    sequence_order = Column(Integer, nullable=False)
    
    # Relationships
    drip_sequence = relationship("DripSequence", back_populates="steps")
    message = relationship("MessageMaster")


class LeadDripAssignment(Base):
    """Tracks which Lead is assigned to which Drip Sequence."""
    __tablename__ = "LeadDripAssignment"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    drip_sequence_id = Column(Integer, ForeignKey("DripSequence.id"), nullable=False)
    
    start_date = Column(Date, nullable=False, default=date.today)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    lead = relationship("Lead", back_populates="drip_assignments")
    drip_sequence = relationship("DripSequence", back_populates="lead_assignments")
    sent_messages = relationship("SentDripMessageLog", back_populates="assignment", cascade="all, delete-orphan")


class SentDripMessageLog(Base):
    """Logs which drip message step has been sent for a specific assignment."""
    __tablename__ = "SentDripMessageLog"
    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("LeadDripAssignment.id"), nullable=False)
    step_id = Column(Integer, ForeignKey("DripSequenceStep.id"), nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)

    assignment = relationship("LeadDripAssignment", back_populates="sent_messages")
    step = relationship("DripSequenceStep")