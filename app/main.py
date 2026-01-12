from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.requests import Request
from sqlalchemy.orm import Session
from jinja2 import Environment, FileSystemLoader
import os
import shutil
from pathlib import Path
from typing import Optional

from app.database import init_db, get_db, User as DBUser, Course as DBCourse
from app.models import UserCreate, User, Course, TranscriptData
from app.parser import TranscriptParser

app = FastAPI(title="Student Planner System", description="סוכן חכם לתכנון מערכת קורסים ולימודים")

# Create uploads directory
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Templates
jinja_env = Environment(loader=FileSystemLoader("templates"))

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_db()


@app.get("/", response_class=HTMLResponse)
async def main_page(request: Request):
    """Main page - Academic Advisor"""
    template = jinja_env.get_template("index.html")
    return HTMLResponse(content=template.render())


@app.get("/semester", response_class=HTMLResponse)
async def semester_page(request: Request):
    """Semester planning page"""
    template = jinja_env.get_template("semester.html")
    return HTMLResponse(content=template.render())


@app.get("/transcript", response_class=HTMLResponse)
async def transcript_page(request: Request):
    """Transcript upload page (legacy - redirects to semester)"""
    template = jinja_env.get_template("landing.html")
    return HTMLResponse(content=template.render())


@app.post("/api/upload-transcript")
async def upload_transcript(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload and parse transcript file
    Returns JSON structure with student and course data
    """
    try:
        # Save uploaded file
        file_path = UPLOAD_DIR / file.filename
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Parse transcript
        parser = TranscriptParser()
        transcript_data = parser.parse_file(str(file_path), file.content_type)
        
        # Clean up uploaded file
        os.remove(file_path)
        
        # Convert to dict for JSON response
        return JSONResponse(content=transcript_data.model_dump())
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")


@app.post("/api/save-user")
async def save_user(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    """
    Save or update user and courses to database
    If user exists (by ID number), updates existing user and replaces all courses
    """
    try:
        # Check if user already exists
        existing_user = db.query(DBUser).filter(DBUser.id_number == user_data.id_number).first()
        
        if existing_user:
            # Update existing user
            existing_user.name = user_data.name
            existing_user.faculty = user_data.faculty
            existing_user.study_track = user_data.study_track
            existing_user.cumulative_average = user_data.cumulative_average
            existing_user.success_rate = user_data.success_rate
            existing_user.current_semester = user_data.current_semester
            existing_user.current_year = user_data.current_year
            
            # Delete all existing courses
            db.query(DBCourse).filter(DBCourse.user_id == existing_user.id).delete()
            
            db_user = existing_user
            is_update = True
        else:
            # Create new user
            db_user = DBUser(
                name=user_data.name,
                id_number=user_data.id_number,
                faculty=user_data.faculty,
                study_track=user_data.study_track,
                cumulative_average=user_data.cumulative_average,
                success_rate=user_data.success_rate,
                current_semester=user_data.current_semester,
                current_year=user_data.current_year
            )
            db.add(db_user)
            is_update = False
        
        db.flush()
        
        # Add courses
        for course_data in user_data.courses:
            db_course = DBCourse(
                user_id=db_user.id,
                course_name=course_data.course_name,
                course_number=course_data.course_number,
                credit_points=course_data.credit_points,
                grade=course_data.grade,
                letter_grade=course_data.letter_grade,
                semester=course_data.semester,
                year=course_data.year,
                notes=course_data.notes,
                is_passed=course_data.is_passed,
                retake_count=course_data.retake_count
            )
            db.add(db_course)
        
        db.commit()
        db.refresh(db_user)
        
        message = "המשתמש והקורסים עודכנו בהצלחה" if is_update else "המשתמש והקורסים נשמרו בהצלחה"
        return {"message": message, "user_id": db_user.id, "is_update": is_update}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error saving user: {str(e)}")


@app.get("/api/user/{user_id}")
async def get_user(user_id: int, db: Session = Depends(get_db)):
    """Get user by ID with all courses"""
    user = db.query(DBUser).filter(DBUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.get("/api/user/by-id-number/{id_number}")
async def get_user_by_id_number(id_number: str, db: Session = Depends(get_db)):
    """Get user by ID number with all courses"""
    user = db.query(DBUser).filter(DBUser.id_number == id_number).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

