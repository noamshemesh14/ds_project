from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

SQLALCHEMY_DATABASE_URL = "sqlite:///./student_planner.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    id_number = Column(String, unique=True, index=True, nullable=False)  # תז
    faculty = Column(String, nullable=True)  # פקולטה
    study_track = Column(String, nullable=True)  # מסלול לימודים
    cumulative_average = Column(Float, nullable=True)  # ממוצע מצטבר
    success_rate = Column(Float, nullable=True)  # אחוזי הצלחה
    current_semester = Column(String, nullable=True)  # סמסטר נוכחי
    current_year = Column(Integer, nullable=True)  # שנה נוכחית
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    courses = relationship("Course", back_populates="user", cascade="all, delete-orphan")


class Course(Base):
    __tablename__ = "courses"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    course_name = Column(String, nullable=False)  # שם קורס
    course_number = Column(String, nullable=True)  # מספר קורס
    credit_points = Column(Float, nullable=True)  # נקודות זכות
    grade = Column(Float, nullable=True)  # ציון
    letter_grade = Column(String, nullable=True)  # ציון אות (A, B, C, etc.)
    semester = Column(String, nullable=True)  # סמסטר שבו נלמד
    year = Column(Integer, nullable=True)  # שנה שבה נלמד
    notes = Column(Text, nullable=True)  # הערות (מועד ב', נכשל, etc.)
    is_passed = Column(Boolean, default=True)  # האם עבר את הקורס
    retake_count = Column(Integer, default=0)  # מספר פעמים שנלמד מחדש
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="courses")


def init_db():
    """Initialize database - create all tables"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

