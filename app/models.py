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
    id: int
    user_id: int
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
    id: int
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

