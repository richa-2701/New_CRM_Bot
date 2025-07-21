# app/models.py
import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.db import Base
# Enums
class LeadStatus(str, enum.Enum):
    NEW = "new"
    QUALIFIED = "qualified"
    UNQUALIFIED = "unqualified"
    NOT_OUR_SEGMENT = "not_our_segment"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
# :white_check_mark: USER Model (according to your table)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(100), nullable=False)
    usernumber = Column(String(15), unique=True, nullable=False)
    department = Column(String(100), nullable=True)
    password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    leads = relationship("Lead", back_populates="assigned_to_user")
    reminders = relationship("Reminder", back_populates="user")
    task_history = relationship("TaskHistory", back_populates="user")


class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String)
    contact_name = Column(String)
    phone = Column(String)
    email = Column(String, nullable=True)
    address = Column(String, nullable=True)
    segment = Column(String, nullable=True)
    team_size = Column(String, nullable=True)
    source = Column(String)
    remark = Column(Text, nullable=True)
    status = Column(String, default="new")
    created_by = Column(String)
    assigned_to = Column(String, ForeignKey("users.username"))
    created_at = Column(DateTime, default=datetime.utcnow)
    assigned_to_user = relationship("User", back_populates="leads")
    meetings = relationship("Meeting", back_populates="lead")
    demos = relationship("Demo", back_populates="lead")
    reminders = relationship("Reminder", back_populates="lead")
    feedbacks = relationship("Feedback", back_populates="lead")
    task_history = relationship("TaskHistory", back_populates="lead")
    assignment_logs = relationship("AssignmentLog", back_populates="lead")
    status_logs = relationship("StatusLog", back_populates="lead")
    events = relationship("Event", back_populates="lead")
    tasks = relationship("Task", back_populates="lead")


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
    created_by = Column(String)
    remark = Column(String)
    phase = Column(String, default="Scheduled")  # e.g., Scheduled, Done
    created_at = Column(DateTime, default=datetime.utcnow)
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
    created_at = Column(DateTime, default=datetime.utcnow)
    lead = relationship("Lead", back_populates="reminders")
    user = relationship("User", back_populates="reminders")


class TaskHistory(Base):
    __tablename__ = "task_history"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String)
    details = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    lead = relationship("Lead", back_populates="task_history")
    user = relationship("User", back_populates="task_history")


class Meeting(Base):
    __tablename__ = "meetings"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    scheduled_by = Column(String)
    assigned_to = Column(String)
    start_time = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    lead = relationship("Lead", back_populates="meetings")


class Demo(Base):
    __tablename__ = "demos"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    scheduled_by = Column(String)
    assigned_to = Column(String)
    start_time = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    phase = Column(String, default="Scheduled")  # e.g., Scheduled, Done
    lead = relationship("Lead", back_populates="demos")


class Feedback(Base):
    __tablename__ = "feedbacks"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    feedback_by = Column(String)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    lead = relationship("Lead", back_populates="feedbacks")


class AssignmentLog(Base):
    __tablename__ = "assignment_logs"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    assigned_to = Column(String)
    assigned_by = Column(String)
    assigned_at = Column(DateTime, default=datetime.utcnow)
    lead = relationship("Lead", back_populates="assignment_logs")


class StatusLog(Base):
    __tablename__ = "status_logs"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    status = Column(String)
    updated_by = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    lead = relationship("Lead", back_populates="status_logs")