from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class CourseBase(BaseModel):
    course_name: str = Field(..., description="שם הקורס")
    course_number: Optional[str] = Field(None, description="מספר קורס")
    credit_points: Optional[float] = Field(None, description="נקודות זכות")
    grade: Optional[float] = Field(None, description="ציון")
    letter_grade: Optional[str] = Field(None, description="ציון אות")
    semester: Optional[str] = Field(None, description="סמסטר")
    year: Optional[int] = Field(None, description="שנה")
    notes: Optional[str] = Field(None, description="הערות")
    is_passed: bool = Field(True, description="האם עבר את הקורס")
    retake_count: int = Field(0, description="מספר פעמים שנלמד מחדש")


class CourseCreate(CourseBase):
    pass


class Course(CourseBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class UserBase(BaseModel):
    name: str = Field(..., description="שם")
    id_number: str = Field(..., description="תעודת זהות")
    faculty: Optional[str] = Field(None, description="פקולטה")
    study_track: Optional[str] = Field(None, description="מסלול לימודים")
    cumulative_average: Optional[float] = Field(None, description="ממוצע מצטבר")
    success_rate: Optional[float] = Field(None, description="אחוזי הצלחה")
    current_semester: Optional[str] = Field(None, description="סמסטר נוכחי")
    current_year: Optional[int] = Field(None, description="שנה נוכחית")


class UserCreate(UserBase):
    courses: List[CourseCreate] = Field(default_factory=list, description="רשימת קורסים")


class User(UserBase):
    id: str
    created_at: datetime
    updated_at: datetime
    courses: List[Course] = []
    
    class Config:
        from_attributes = True


class TranscriptData(BaseModel):
    """JSON structure for parsed transcript"""
    student_info: UserBase
    courses: List[CourseBase]
    metadata: Optional[dict] = Field(default_factory=dict, description="מטא-דאטה נוסף")


# Auth models
class SignUpRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = None


class SignInRequest(BaseModel):
    email: str
    password: str


# Constraint models
class ConstraintBase(BaseModel):
    title: str = Field(..., description="שם האילוץ")
    description: Optional[str] = Field(None, description="תיאור האילוץ")
    days: List[int] = Field(..., description="ימים בשבוע (0=ראשון, 1=שני, וכו')")
    start_time: str = Field(..., description="שעת התחלה (HH:MM)")
    end_time: str = Field(..., description="שעת סיום (HH:MM)")


class ConstraintCreate(ConstraintBase):
    pass


class Constraint(ConstraintBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# Weekly Constraint models
class WeeklyConstraintBase(BaseModel):
    title: str = Field(..., description="שם האילוץ")
    description: Optional[str] = Field(None, description="תיאור האילוץ")
    days: List[int] = Field(..., description="ימים בשבוע (0=ראשון, 1=שני, וכו')")
    start_time: str = Field(..., description="שעת התחלה (HH:MM)")
    end_time: str = Field(..., description="שעת סיום (HH:MM)")
    week_start: str = Field(..., description="תחילת השבוע (YYYY-MM-DD)")
    is_hard: bool = Field(True, description="האם האילוץ קשיח")


class WeeklyConstraintCreate(WeeklyConstraintBase):
    pass


class WeeklyConstraint(WeeklyConstraintBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# Assignment models
class AssignmentBase(BaseModel):
    title: str = Field(..., description="כותרת המטלה")
    description: Optional[str] = Field(None, description="תיאור המטלה")
    due_date: str = Field(..., description="תאריך דד-ליין (YYYY-MM-DD)")
    priority: str = Field("medium", description="עדיפות: low, medium, high")
    is_completed: bool = Field(False, description="האם הושלמה")


class AssignmentCreate(AssignmentBase):
    course_id: str = Field(..., description="מזהה הקורס")


class Assignment(AssignmentBase):
    id: str
    course_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    days_remaining: Optional[int] = None  # Calculated field
    
    class Config:
        from_attributes = True


# Chat models
class ChatMessage(BaseModel):
    message: str = Field(..., description="הודעת המשתמש")
    conversation_id: Optional[str] = Field(None, description="מזהה שיחה (אופציונלי)")


class ChatResponse(BaseModel):
    response: str = Field(..., description="תשובת המערכת")
    conversation_id: Optional[str] = Field(None, description="מזהה שיחה")


# Study Groups models
class StudyGroupCreate(BaseModel):
    course_id: str = Field(..., description="מזהה הקורס")
    course_name: str = Field(..., description="שם הקורס")
    group_name: str = Field(..., description="שם הקבוצה")
    description: Optional[str] = Field(None, description="תיאור הקבוצה")
    invite_emails: List[str] = Field(default_factory=list, description="רשימת מיילים להזמנה")


class StudyGroup(BaseModel):
    id: str
    course_id: str
    course_name: str
    group_name: str
    description: Optional[str]
    created_by: str
    created_at: datetime
    updated_at: datetime
    members_count: Optional[int] = 0
    
    class Config:
        from_attributes = True


class GroupInvitationResponse(BaseModel):
    id: str
    group_id: str
    group_name: str
    course_name: str
    inviter_email: str
    inviter_name: Optional[str]
    status: str
    created_at: datetime


class Notification(BaseModel):
    id: str
    type: str
    title: str
    message: str
    link: Optional[str]
    read: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


# Semester Schedule Item models
class SemesterScheduleItemBase(BaseModel):
    course_name: str = Field(..., description="שם הקורס")
    type: str = Field(..., description="סוג: lecture, tutorial, lab, seminar, other")
    days: List[int] = Field(..., description="ימים בשבוע (0=ראשון, 1=שני, וכו')")
    start_time: str = Field(..., description="שעת התחלה (HH:MM)")
    end_time: str = Field(..., description="שעת סיום (HH:MM)")
    location: Optional[str] = Field(None, description="מיקום")


class SemesterScheduleItemCreate(SemesterScheduleItemBase):
    pass


class SemesterScheduleItemUpdate(BaseModel):
    course_name: Optional[str] = None
    type: Optional[str] = None
    days: Optional[List[int]] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None


class SemesterScheduleItem(SemesterScheduleItemBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
