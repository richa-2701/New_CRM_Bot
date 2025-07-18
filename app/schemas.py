from pydantic import BaseModel, ConfigDict
from typing import Optional, Union
from datetime import datetime
from app.models import LeadStatus, TaskStatus
# ---------------- LEAD SCHEMAS ----------------
class LeadBase(BaseModel):
    company_name: str
    contact_name: str
    phone: str
    email: Optional[str] = None
    address: Optional[str] = None
    team_size: Optional[Union[str, int]] = None
    source: str
    segment: Optional[str] = None
    remark: Optional[str] = None
    product: Optional[str] = None  # optional for future use
class LeadCreate(LeadBase):
    created_by: str
    assigned_to: Optional[str]  # FK to users.id
class LeadOut(LeadBase):
    id: int
    status: str
    created_at: datetime
    assigned_to: Optional[str]
    model_config = ConfigDict(from_attributes=True)
class LeadUpdate(BaseModel):
    status: Optional[str]
    remark: Optional[str] = None
    assigned_to: Optional[int]
# ---------------- TASK SCHEMAS ----------------
class TaskBase(BaseModel):
    lead_id: int
    assigned_to: str
    task_type: str
    date_time: datetime
    remark: Optional[str] = None
class TaskCreate(TaskBase):
    pass
class TaskOut(TaskBase):
    id: int
    status: str
    model_config = ConfigDict(from_attributes=True)
# ---------------- USER SCHEMAS ----------------
class UserBase(BaseModel):
    username: str
    usernumber: str
    department: Optional[str] = None
class UserCreate(UserBase):
    pass
class UserOut(UserBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
# ---------------- EVENT SCHEMAS ----------------
class EventBase(BaseModel):
    lead_id: int
    assigned_to: str
    event_type: str
    event_time: datetime
    created_by: str
    remark: Optional[str] = None
class EventCreate(EventBase):
    pass
class EventOut(EventBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
# ---------------- FEEDBACK SCHEMAS ----------------
class FeedbackBase(BaseModel):
    lead_id: int
    feedback_by: str
    content: str
class FeedbackCreate(FeedbackBase):
    pass
class FeedbackOut(FeedbackBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
# ---------------- REMINDER SCHEMAS ----------------
class ReminderBase(BaseModel):
    lead_id: int
    remind_time: datetime
    message: str
    assigned_to: str
class ReminderCreate(ReminderBase):
    user_id: int  # required for FK to users.id
class ReminderOut(ReminderBase):
    id: int
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)