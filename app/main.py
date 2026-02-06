from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.requests import Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from sqlalchemy.orm import Session
from jinja2 import Environment, FileSystemLoader
import os
import shutil
from pathlib import Path
from typing import Optional

from app.database import init_db, get_db, User as DBUser, Course as DBCourse
from app.models import (
    UserCreate, User, Course, TranscriptData, SignUpRequest, SignInRequest,
    ConstraintCreate, Constraint, WeeklyConstraintCreate, WeeklyConstraint,
    ChatMessage, ChatResponse, StudyGroupCreate, StudyGroup,
    GroupInvitationResponse, Notification, Assignment, AssignmentCreate
)
from app.parser import TranscriptParser
from app.supabase_client import supabase, supabase_admin
from app.auth import get_current_user, get_optional_user
from app.agents.supervisor import Supervisor
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta, timezone
import asyncio
import sys
import logging
import json

# OpenAI for schedule refinement
try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logging.warning("OpenAI not installed. LLM-based schedule refinement will not be available.")

# Load environment variables
load_dotenv()

# Configure logging to both console and file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('parser.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# Global cache for LLM debug info (temporary for debugging)
_llm_debug_cache = {}

app = FastAPI(title="Student Planner System", description="סוכן חכם לתכנון מערכת קורסים ולימודים")

# Background scheduler for weekly auto-planning (UTC to avoid local TZ misfires)
scheduler = BackgroundScheduler(timezone="UTC")


@app.on_event("startup")
def _start_scheduler():
    try:
        # Run every Friday at 12:43 (3 minutes from now)
        scheduler.add_job(
            _run_weekly_auto_for_all_users_sync,
            CronTrigger(day_of_week="fri", hour=12, minute=43),
            id="weekly_auto_plan",
            replace_existing=True,
        )
        scheduler.start()
        logging.info("Weekly scheduler started")
    except Exception as e:
        logging.error(f"Failed to start scheduler: {e}")


@app.on_event("shutdown")
def _shutdown_scheduler():
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass

# Create uploads directory
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Templates
jinja_env = Environment(loader=FileSystemLoader("templates"))

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_db()

# Global exception handler to ensure JSON responses for API errors
# Must be defined after app is created
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler to return JSON errors for API endpoints
    """
    import traceback
    
    # Check if this is an API endpoint
    if request.url.path.startswith("/api/"):
        # Try to log the error, but don't fail if logging is not available
        try:
            logging.error(f"❌ Unhandled exception in API endpoint {request.url.path}: {exc}")
            logging.error(f"   Traceback: {traceback.format_exc()}")
        except (NameError, AttributeError) as log_error:
            # If logging is not available, use print
            print(f"Error in exception handler (logging not available): {log_error}")
            print(f"❌ Unhandled exception in API endpoint {request.url.path}: {exc}")
            print(f"   Traceback: {traceback.format_exc()}")
        except Exception as log_error:
            # If logging fails for other reasons, at least return JSON error
            print(f"Error in exception handler logging: {log_error}")
        
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal server error: {str(exc)}"}
        )
    # For non-API endpoints, let FastAPI handle it normally
    raise exc


@app.get("/", response_class=HTMLResponse)
async def main_page(request: Request):
    """Main page - Academic Advisor"""
    template = jinja_env.get_template("index.html")
    return HTMLResponse(content=template.render())


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    """User profile page with transcript upload"""
    template = jinja_env.get_template("semester.html")
    return HTMLResponse(content=template.render())

@app.get("/semester", response_class=HTMLResponse)
async def semester_page(request: Request):
    """Legacy route - redirects to profile"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/profile", status_code=301)

@app.get("/schedule", response_class=HTMLResponse)
async def schedule_page(request: Request):
    """Schedule builder page with weekly calendar"""
    template = jinja_env.get_template("schedule.html")
    return HTMLResponse(content=template.render())

@app.get("/my-courses", response_class=HTMLResponse)
async def my_courses_page(request: Request):
    """My Courses page - displays all courses with semester selection"""
    try:
        # Debug logging
        logging.info("=" * 60)
        logging.info("📚 [MY-COURSES] Page requested")
        logging.info(f"📚 [MY-COURSES] Request URL: {request.url}")
        logging.info(f"📚 [MY-COURSES] Request method: {request.method}")
        logging.info(f"📚 [MY-COURSES] Client host: {request.client.host if request.client else 'Unknown'}")
        
        # Check for Authorization header
        auth_header = request.headers.get("authorization")
        if auth_header:
            logging.info(f"📚 [MY-COURSES] Authorization header found: {auth_header[:20]}...")
        else:
            logging.info("📚 [MY-COURSES] No Authorization header in request")
        
        # Check cookies
        cookies = request.cookies
        if cookies:
            logging.info(f"📚 [MY-COURSES] Cookies: {list(cookies.keys())}")
        else:
            logging.info("📚 [MY-COURSES] No cookies in request")
        
        template = jinja_env.get_template("my_courses.html")
        logging.info("📚 [MY-COURSES] Template loaded successfully")
        logging.info("📚 [MY-COURSES] Returning HTML response")
        logging.info("=" * 60)
        
        return HTMLResponse(content=template.render())
    except Exception as e:
        logging.error(f"❌ [MY-COURSES] Error loading my_courses.html: {e}")
        logging.error(f"❌ [MY-COURSES] Error type: {type(e).__name__}")
        import traceback
        logging.error(f"❌ [MY-COURSES] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error loading page: {str(e)}")


@app.get("/group/{group_id}", response_class=HTMLResponse)
async def group_chat_page(
    group_id: str,
    request: Request,
    current_user: Optional[dict] = Depends(get_optional_user)
):
    """Group chat page - authentication checked in JavaScript"""
    try:
        # Get group details (no auth required for page load, auth checked in JS)
        client = supabase_admin if supabase_admin else supabase
        
        # Get group details
        group_result = client.table("study_groups").select("*").eq("id", group_id).execute()
        
        if not group_result.data:
            raise HTTPException(status_code=404, detail="Group not found")
        
        group = group_result.data[0]
        
        template = jinja_env.get_template("group_chat.html")
        return HTMLResponse(content=template.render(
            group_id=group_id,
            group_name=group.get('group_name', 'קבוצה'),
            course_name=group.get('course_name', 'קורס')
        ))
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error loading group_chat.html: {e}")
        raise HTTPException(status_code=500, detail=f"Error loading page: {str(e)}")

@app.get("/transcript", response_class=HTMLResponse)
async def transcript_page(request: Request):
    """Transcript upload page (legacy - redirects to semester)"""
    template = jinja_env.get_template("landing.html")
    return HTMLResponse(content=template.render())


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login/Signup page"""
    template = jinja_env.get_template("login.html")
    return HTMLResponse(content=template.render())


@app.get("/auth/confirm", response_class=HTMLResponse)
async def confirm_email(request: Request):
    """
    Email confirmation page - handles Supabase email confirmation redirect
    Supabase redirects here with access_token and type parameters in the URL
    
    This endpoint:
    1. Receives the access_token from Supabase after email confirmation
    2. Authenticates the user automatically
    3. Creates a minimal user profile if it doesn't exist
    4. Redirects to the home page with the user authenticated
    """
    # Get token from query params or hash (Supabase can send it either way)
    access_token = request.query_params.get("access_token")
    token_type = request.query_params.get("type")
    error = request.query_params.get("error")
    
    # If not in query params, check hash (Supabase sometimes puts it there)
    if not access_token:
        # Try to get from hash - this is handled by JavaScript in the template
        pass
    
    if access_token and token_type == "email":
        logging.info(f"✅ Email confirmation received: type={token_type}, has_token=True")
        
        try:
            # Verify and decode the token to get user info
            import base64
            import json
            
            parts = access_token.split('.')
            if len(parts) == 3:
                payload_encoded = parts[1]
                # Add padding if needed
                padding = 4 - len(payload_encoded) % 4
                if padding != 4:
                    payload_encoded += '=' * padding
                
                payload_bytes = base64.urlsafe_b64decode(payload_encoded)
                payload = json.loads(payload_bytes.decode('utf-8'))
                
                user_id = payload.get('sub')
                user_email = payload.get('email')
                
                if user_id:
                    logging.info(f"   User confirmed: {user_email} (id: {user_id})")
                    
                    # Ensure user profile exists (create minimal if needed)
                    client = supabase_admin if supabase_admin else supabase
                    if client:
                        try:
                            existing_profile = client.table("user_profiles").select("id").eq("id", user_id).execute()
                            if not existing_profile.data or len(existing_profile.data) == 0:
                                # Create minimal profile
                                profile_data = {
                                    "id": user_id,
                                    "email": user_email,
                                    "name": payload.get('user_metadata', {}).get('name')
                                }
                                client.table("user_profiles").insert(profile_data).execute()
                                logging.info(f"✅ Created minimal user profile for {user_email}")
                            else:
                                logging.info(f"ℹ️ User profile already exists for {user_email}")
                        except Exception as profile_error:
                            logging.warning(f"⚠️ Could not ensure user profile exists: {profile_error}")
                            # Don't fail - user can still proceed
                else:
                    logging.warning("⚠️ No user_id found in token payload")
            else:
                logging.warning(f"⚠️ Invalid token format: expected 3 parts, got {len(parts)}")
        except Exception as token_error:
            logging.error(f"❌ Error processing confirmation token: {token_error}")
            # Don't fail - let the frontend handle it
    elif error:
        logging.warning(f"❌ Email confirmation error: {error}")
    else:
        logging.info("ℹ️ Email confirmation page accessed (no token in query params - might be in hash)")
    
    template = jinja_env.get_template("confirm_email.html")
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
        gemini_api_key = os.getenv('GEMINI_API_KEY') or 'AIzaSyBq5j_h0Sxep-AxIV0jyliAAv7seiYgx2o'
        parser = TranscriptParser(gemini_api_key=gemini_api_key)
        logging.info(f"Starting transcript parsing for file: {file.filename}")
        transcript_data = parser.parse_file(str(file_path), file.content_type)
        logging.info(f"Parsing completed. Found {len(transcript_data.courses)} courses")
        
        # Clean up uploaded file
        os.remove(file_path)
        
        # Convert to dict for JSON response
        return JSONResponse(content=transcript_data.model_dump())
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")


@app.post("/api/save-user")
async def save_user(
    user_data: UserCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Save or update user profile and courses to Supabase
    Requires authentication - user must be signed in
    """
    try:
        user_id = current_user["id"]  # UUID from Supabase auth
        logging.info(f"💾 Saving user data for user_id: {user_id}, email: {current_user.get('email', 'N/A')}")
        
        # Prepare user profile data (timestamps are handled by DB defaults)
        # This will UPDATE the minimal profile created after authentication with full data
        profile_data = {
            "id": user_id,
            "email": current_user.get('email'),  # Ensure email is included
            "name": user_data.name,
            "id_number": user_data.id_number,
            "faculty": user_data.faculty,
            "study_track": user_data.study_track,
            "cumulative_average": user_data.cumulative_average,
            "success_rate": user_data.success_rate,
            "current_semester": user_data.current_semester,
            "current_year": user_data.current_year
        }
        
        # Use service_role client if available (bypasses RLS, safe since we've already authenticated)
        # Otherwise use anon client (requires RLS to be properly configured)
        client = supabase_admin if supabase_admin else supabase
        
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        logging.info(f"   Using {'admin' if supabase_admin else 'anon'} client for save operation")
        
        # Check if profile exists
        try:
            existing_profile = client.table("user_profiles").select("id").eq("id", user_id).execute()
            is_update = len(existing_profile.data) > 0
            logging.info(f"   Profile exists: {is_update}")
        except Exception as e:
            logging.error(f"   Error checking existing profile: {e}")
            raise HTTPException(status_code=500, detail=f"Error checking existing profile: {str(e)}")
        
        # Upsert user profile (Supabase will handle timestamps via DEFAULT)
        try:
            if is_update:
                logging.info(f"   Updating existing profile for user {user_id}")
                update_result = client.table("user_profiles").update(profile_data).eq("id", user_id).execute()
                logging.info(f"   Update result: {len(update_result.data) if update_result.data else 0} rows updated")
            else:
                logging.info(f"   Inserting new profile for user {user_id}")
                insert_result = client.table("user_profiles").insert(profile_data).execute()
                logging.info(f"   Insert result: {len(insert_result.data) if insert_result.data else 0} rows inserted")
        except Exception as e:
            logging.error(f"   Error upserting profile: {e}")
            import traceback
            logging.error(f"   Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Error saving profile: {str(e)}")
        
        # Delete existing courses for this user
        try:
            logging.info(f"   Deleting existing courses for user {user_id}")
            delete_result = client.table("courses").delete().eq("user_id", user_id).execute()
            logging.info(f"   Deleted courses: {len(delete_result.data) if delete_result.data else 0}")
        except Exception as e:
            logging.warning(f"   Error deleting courses (might not exist): {e}")
            # Continue even if delete fails - courses might not exist yet
        
        # Insert new courses
        if user_data.courses:
            try:
                courses_data = []
                for course_data in user_data.courses:
                    courses_data.append({
                        "user_id": user_id,
                        "course_name": course_data.course_name,
                        "course_number": course_data.course_number,
                        "credit_points": course_data.credit_points,
                        "grade": course_data.grade,
                        "letter_grade": course_data.letter_grade,
                        "semester": course_data.semester,
                        "year": course_data.year,
                        "notes": course_data.notes,
                        "is_passed": course_data.is_passed,
                        "retake_count": course_data.retake_count or 0
                    })
                
                logging.info(f"   Inserting {len(courses_data)} courses for user {user_id}")
                courses_result = client.table("courses").insert(courses_data).execute()
                logging.info(f"   Courses inserted: {len(courses_result.data) if courses_result.data else 0}")
                
                # Create course_time_preferences for each new course (default 50/50 split)
                if courses_result.data:
                    try:
                        prefs_data = []
                        for course in courses_result.data:
                            course_number = course.get("course_number")
                            if course_number:
                                # Calculate default hours based on credit points
                                credit_points = course.get("credit_points") or 3
                                total_hours = credit_points * 3
                                default_personal_hours = max(1, int(total_hours * 0.5))  # Default 50%
                                default_group_hours = max(1, total_hours - default_personal_hours)
                                
                                prefs_data.append({
                                    "user_id": user_id,
                                    "course_number": course_number,
                                    "personal_hours_per_week": default_personal_hours,
                                    "group_hours_per_week": default_group_hours
                                })
                        
                        if prefs_data:
                            client.table("course_time_preferences").insert(prefs_data).execute()
                            logging.info(f"   Created course_time_preferences for {len(prefs_data)} courses")
                    except Exception as pref_err:
                        # If preferences already exist, that's okay (upsert would handle it, but we use insert for new courses)
                        logging.warning(f"   Could not create course_time_preferences (may already exist): {pref_err}")
            except Exception as e:
                logging.error(f"   Error inserting courses: {e}")
                import traceback
                logging.error(f"   Traceback: {traceback.format_exc()}")
                raise HTTPException(status_code=500, detail=f"Error saving courses: {str(e)}")
        else:
            logging.info(f"   No courses to save for user {user_id}")
        
        message = "המשתמש והקורסים עודכנו בהצלחה" if is_update else "המשתמש והקורסים נשמרו בהצלחה"
        logging.info(f"✅ Successfully saved user data for {user_id}: {message}")
        return {
            "message": message,
            "user_id": user_id,
            "is_update": is_update,
            "courses_count": len(user_data.courses) if user_data.courses else 0
        }
        
    except HTTPException:
        raise
    except Exception as e:
        # Ensure logging is available
        try:
            logging.error(f"❌ Error saving user to Supabase: {e}")
            logging.error(f"   Error type: {type(e)}")
            import traceback
            logging.error(f"   Traceback: {traceback.format_exc()}")
        except NameError:
            # If logging is not available, use print
            import traceback
            print(f"❌ Error saving user to Supabase: {e}")
            print(f"   Error type: {type(e)}")
            print(f"   Traceback: {traceback.format_exc()}")
        
        raise HTTPException(status_code=500, detail=f"Error saving user: {str(e)}")


@app.get("/api/user-data")
async def get_user_data(
    current_user: dict = Depends(get_current_user)
):
    """
    Get user profile and courses data from Supabase
    Returns data in the same format as transcript parsing
    """
    try:
        print("=" * 60)
        print("[USER-DATA API] /api/user-data endpoint called")
        logging.info("=" * 60)
        logging.info("[USER-DATA API] /api/user-data endpoint called")
        print(f"[USER-DATA API] current_user keys: {list(current_user.keys())}")
        logging.info(f"[USER-DATA API] current_user keys: {list(current_user.keys())}")
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            error_msg = f"User ID not found in current_user: {current_user}"
            print(f"[USER-DATA API] ERROR: {error_msg}")
            logging.error(f"[USER-DATA API] ERROR: {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)
        print(f"[USER-DATA API] Loading user data for user_id: {user_id}")
        logging.info(f"[USER-DATA API] Loading user data for user_id: {user_id}")
        
        # Use service_role client if available, otherwise anon client
        client = supabase_admin if supabase_admin else supabase
        
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Get user profile
        try:
            profile_result = client.table("user_profiles").select("*").eq("id", user_id).execute()
            if not profile_result.data or len(profile_result.data) == 0:
                logging.info(f"   No profile found for user {user_id}; continuing to load courses")
                profile = {}
            else:
                profile = profile_result.data[0]
                logging.info(f"   Profile found: {profile.get('name', 'N/A')}")
                logging.info(f"   Profile data: {profile}")
        except Exception as e:
            logging.error(f"   Error loading profile: {e}")
            raise HTTPException(status_code=500, detail=f"Error loading profile: {str(e)}")
        
        # Get courses
        try:
            courses_result = client.table("courses").select("*").eq("user_id", user_id).execute()
            courses = courses_result.data if courses_result.data else []
            logging.info(f"   Found {len(courses)} courses")
            if courses:
                logging.info(f"   First course: {courses[0]}")
        except Exception as e:
            logging.error(f"   Error loading courses: {e}")
            courses = []

        # Load catalog names to normalize display (avoid mojibake from legacy imports)
        catalog_map = {}
        try:
            catalog_res = client.table("course_catalog").select("course_number,course_name").execute()
            catalog_map = {c["course_number"]: c["course_name"] for c in (catalog_res.data or [])}
        except Exception as e:
            logging.warning(f"   Could not load course catalog for name normalization: {e}")
        
        # Convert to TranscriptData format
        student_info = {
            "name": profile.get("name", ""),
            "id_number": profile.get("id_number", ""),
            "faculty": profile.get("faculty", ""),
            "study_track": profile.get("study_track", ""),
            "cumulative_average": profile.get("cumulative_average"),
            "success_rate": profile.get("success_rate"),
            "current_semester": profile.get("current_semester"),
            "current_year": profile.get("current_year")
        }
        
        # Convert courses to CourseBase format
        courses_list = []
        print("=" * 60)
        print(f"[USER-DATA API] Processing {len(courses)} courses:")
        logging.info(f"[USER-DATA API] Processing {len(courses)} courses:")
        for course in courses:
            normalized_name = course.get("course_name", "")
            catalog_name = catalog_map.get(str(course.get("course_number")).strip())
            if catalog_name:
                normalized_name = catalog_name

            course_data = {
                "id": course.get("id"),  # Include course ID for frontend matching
                "course_name": normalized_name,
                "course_number": course.get("course_number", ""),
                "credit_points": course.get("credit_points"),
                "grade": course.get("grade"),
                "letter_grade": course.get("letter_grade"),
                "semester": course.get("semester"),
                "year": course.get("year"),
                "notes": course.get("notes", ""),
                "is_passed": course.get("is_passed", False),
                "retake_count": course.get("retake_count", 0)
            }
            courses_list.append(course_data)
            course_info = f"   Course: '{course_data['course_name']}' | course_number: '{course_data['course_number']}' | id: '{course_data['id']}' | semester: '{course_data['semester']}'"
            print(course_info)
            logging.info(course_info)
        print("=" * 60)
        
        result = {
            "student_info": student_info,
            "courses": courses_list,
            "metadata": {
                "has_data": True,
                "loaded_from": "database",
                "profile_updated_at": profile.get("updated_at"),
                "courses_count": len(courses_list)
            }
        }
        
        logging.info(f"✅ Successfully loaded user data: {len(courses_list)} courses")
        return JSONResponse(content=result)
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"❌ Error loading user data: {e}")
        import traceback
        logging.error(f"   Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error loading user data: {str(e)}")


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


# User Preferences endpoints
@app.post("/api/user/preferences")
async def save_user_preferences(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    Save user study preferences (raw text from user)
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        body = await request.json()
        study_preferences_raw = body.get("study_preferences_raw", "")
        
        if not study_preferences_raw:
            raise HTTPException(status_code=400, detail="study_preferences_raw is required")
        
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Upsert user profile with raw preferences (create row if missing)
        profile_payload = {
            "id": user_id,
            "study_preferences_raw": study_preferences_raw
        }
        # Preserve email/name if available from token
        user_email = current_user.get("email")
        if user_email:
            profile_payload["email"] = user_email
        user_name = current_user.get("user_metadata", {}).get("name")
        if user_name:
            profile_payload["name"] = user_name

        update_result = client.table("user_profiles").upsert(
            profile_payload,
            on_conflict="id"
        ).execute()
        
        logging.info(f"Saved study preferences for user {user_id}: {len(study_preferences_raw)} chars")
        
        # Get schedule change notes to include in summary
        profile_result = client.table("user_profiles").select("schedule_change_notes").eq("id", user_id).limit(1).execute()
        schedule_notes = []
        if profile_result.data:
            schedule_notes = profile_result.data[0].get("schedule_change_notes", []) or []
        
        # Generate LLM summary of preferences + schedule notes
        summary = await _summarize_user_preferences_with_llm(study_preferences_raw, schedule_notes)
        
        if summary:
            # Save the summary
            client.table("user_profiles").update({
                "study_preferences_summary": summary
            }).eq("id", user_id).execute()
            logging.info(f"Updated preferences summary for user {user_id}")
        
        return JSONResponse(content={
            "message": "Preferences saved successfully",
            "preferences_length": len(study_preferences_raw),
            "summary_generated": summary is not None
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error saving user preferences: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving preferences: {str(e)}")


@app.get("/api/user/preferences")
async def get_user_preferences(current_user: dict = Depends(get_current_user)):
    """
    Get user study preferences
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        profile_result = client.table("user_profiles").select("study_preferences_raw, study_preferences_summary").eq("id", user_id).limit(1).execute()
        
        if not profile_result.data:
            return JSONResponse(content={
                "study_preferences_raw": "",
                "study_preferences_summary": {}
            })
        
        profile = profile_result.data[0]
        return JSONResponse(content={
            "study_preferences_raw": profile.get("study_preferences_raw") or "",
            "study_preferences_summary": profile.get("study_preferences_summary") or {}
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting user preferences: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting preferences: {str(e)}")


# Authentication endpoints
@app.post("/api/auth/signup")
async def signup(request: SignUpRequest):
    """
    Sign up a new user
    """
    try:
        # First, check if user already exists using admin API (if available)
        # This prevents duplicate signups and unnecessary email sends
        if supabase_admin:
            try:
                # Try to get user by email using admin API
                admin_users = supabase_admin.auth.admin.list_users()
                if admin_users and hasattr(admin_users, 'users'):
                    for user in admin_users.users:
                        if user.email and user.email.lower() == request.email.lower():
                            logging.warning(f"⚠️ Signup attempt for EXISTING email: {request.email} - preventing duplicate signup")
                            raise HTTPException(
                                status_code=400, 
                                detail="כתובת האימייל כבר רשומה במערכת. אנא התחבר במקום להירשם."
                            )
                logging.info(f"✅ Email {request.email} is new - proceeding with signup")
            except HTTPException:
                raise  # Re-raise our HTTPException
            except Exception as e:
                # If admin check fails, log and continue (might not have admin access)
                logging.warning(f"Could not check existing user with admin API: {e}. Continuing with signup...")
        
        # Sign up with Supabase
        response = supabase.auth.sign_up({
            "email": request.email,
            "password": request.password,
            "options": {
                "data": {
                    "name": request.name
                },
                "email_redirect_to": "http://localhost:8000/auth/confirm"
            }
        })
        
        # Supabase sometimes returns a user even if email exists but doesn't create a new one
        # Check if this is actually a new user by checking the response
        if response.user:
            # Check if email confirmation is required
            email_confirmed = response.user.email_confirmed_at is not None
            has_session = response.session is not None
            
            # Check if this is a new user or existing user
            # If user was created recently (within last few seconds), it's probably new
            # Otherwise, check if we can verify it's new by checking created_at
            user_created_at = getattr(response.user, 'created_at', None)
            is_new_user = True
            
            # If admin client is available, double-check if user already existed
            if supabase_admin:
                try:
                    admin_users = supabase_admin.auth.admin.list_users()
                    if admin_users and hasattr(admin_users, 'users'):
                        for user in admin_users.users:
                            if user.email and user.email.lower() == request.email.lower():
                                # Check if this user was created before this request
                                if hasattr(user, 'created_at') and user_created_at:
                                    # If created_at is significantly before now, it's an existing user
                                    from datetime import datetime, timezone
                                    if isinstance(user_created_at, str):
                                        # Parse if it's a string
                                        try:
                                            user_created_dt = datetime.fromisoformat(user_created_at.replace('Z', '+00:00'))
                                            now = datetime.now(timezone.utc)
                                            time_diff = (now - user_created_dt).total_seconds()
                                            # If user was created more than 10 seconds ago, it's probably existing
                                            if time_diff > 10:
                                                is_new_user = False
                                                logging.warning(f"⚠️ User {request.email} already exists (created {time_diff} seconds ago)")
                                                raise HTTPException(
                                                    status_code=400,
                                                    detail="כתובת האימייל כבר רשומה במערכת. אנא התחבר במקום להירשם."
                                                )
                                        except:
                                            pass
                except HTTPException:
                    raise
                except Exception as e:
                    # If check fails, assume it's a new user
                    logging.warning(f"Could not verify if user is new: {e}")
            
            if is_new_user:
                logging.info(f"✅ Signup SUCCESS for NEW user {request.email}: user_id={response.user.id}, confirmed={email_confirmed}, has_session={has_session}")
                
                # Create minimal user profile in user_profiles table
                # This allows the user to use features like constraints immediately after signup
                try:
                    client = supabase_admin if supabase_admin else supabase
                    if not client:
                        logging.error("❌ No Supabase client available - cannot create user profile")
                    else:
                        # Check if profile already exists (shouldn't, but just in case)
                        existing_profile = client.table("user_profiles").select("id").eq("id", response.user.id).execute()
                        
                        if not existing_profile.data or len(existing_profile.data) == 0:
                            # Create minimal profile with just the required fields
                            profile_data = {
                                "id": response.user.id,
                                "email": response.user.email,
                                "name": request.name if hasattr(request, 'name') else None
                            }
                            
                            logging.info(f"   Attempting to create profile with data: {profile_data}")
                            result = client.table("user_profiles").insert(profile_data).execute()
                            
                            if result.data:
                                logging.info(f"✅ Created minimal user profile for {request.email} (id: {response.user.id})")
                            else:
                                logging.error(f"❌ Profile insert returned no data for {request.email}")
                        else:
                            logging.info(f"ℹ️ User profile already exists for {request.email}")
                except Exception as profile_error:
                    # Log detailed error but don't fail signup - user can still sign in
                    logging.error(f"❌ Could not create user profile: {profile_error}")
                    logging.error(f"   Error type: {type(profile_error)}")
                    import traceback
                    logging.error(f"   Traceback: {traceback.format_exc()}")
                    logging.warning(f"   User can still sign in, but may need to upload grade sheet first")
            else:
                logging.info(f"⚠️ Signup attempt for EXISTING user {request.email}")
            
            logging.info(f"   User saved to Supabase auth.users (check Authentication > Users in Supabase Dashboard)")
            
            return {
                "user": {
                    "id": response.user.id,
                    "email": response.user.email,
                    "email_confirmed": email_confirmed
                },
                "session": response.session.model_dump() if response.session else None,
                "requires_email_confirmation": not email_confirmed and not has_session,
                "is_new_user": is_new_user
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to create user")
    except HTTPException:
        raise  # Re-raise HTTPExceptions
    except Exception as e:
        error_str = str(e).lower()
        error_msg = str(e)
        logging.error(f"Signup error: {e}")
        logging.error(f"Error type: {type(e)}, Error message: {error_msg}")
        
        # Check for various error types
        if any(keyword in error_str for keyword in ["already", "exists", "registered", "duplicate", "user already"]):
            raise HTTPException(status_code=400, detail="Email already registered. Please sign in instead.")
        
        if "email" in error_str and ("invalid" in error_str or "format" in error_str):
            raise HTTPException(status_code=400, detail="Invalid email format.")
        
        # Check for Supabase-specific error messages
        if hasattr(e, 'message'):
            if "already" in e.message.lower() or "exists" in e.message.lower():
                raise HTTPException(status_code=400, detail="Email already registered. Please sign in instead.")
        
        raise HTTPException(status_code=400, detail=f"Error signing up: {error_msg}")


@app.post("/api/auth/login")
async def login(request: SignInRequest):
    """
    Login endpoint for terminal/CLI usage
    Returns access_token for API authentication
    """
    try:
        response = supabase.auth.sign_in_with_password({
            "email": request.email,
            "password": request.password,
        })
        
        if response.user and response.session:
            return JSONResponse(content={
                "message": "Login successful",
                "access_token": response.session.access_token,
                "user_id": response.user.id
            })
        else:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    except Exception as e:
        error_str = str(e)
        logging.error(f"Login error: {error_str}")
        
        if "invalid" in error_str or "credentials" in error_str or "password" in error_str:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        raise HTTPException(status_code=401, detail=f"Error logging in: {str(e)}")


@app.post("/api/auth/signin")
async def signin(request: SignInRequest):
    """
    Sign in an existing user
    Also ensures a minimal user profile exists in user_profiles table
    """
    try:
        # Sign in with Supabase
        response = supabase.auth.sign_in_with_password({
            "email": request.email,
            "password": request.password
        })
        
        if response.user:
            # Ensure user profile exists (create minimal if needed)
            user_id = response.user.id
            user_email = response.user.email
            
            try:
                client = supabase_admin if supabase_admin else supabase
                if client:
                    existing_profile = client.table("user_profiles").select("id").eq("id", user_id).execute()
                    
                    if not existing_profile.data or len(existing_profile.data) == 0:
                        # Create minimal profile
                        profile_data = {
                            "id": user_id,
                            "email": user_email,
                            "name": response.user.user_metadata.get('name') if hasattr(response.user, 'user_metadata') else None
                        }
                        client.table("user_profiles").insert(profile_data).execute()
                        logging.info(f"✅ Created minimal user profile for {user_email} during signin")
                    else:
                        logging.info(f"ℹ️ User profile already exists for {user_email}")
            except Exception as profile_error:
                # Don't fail signin if profile creation fails
                logging.warning(f"⚠️ Could not ensure user profile exists during signin: {profile_error}")
        
        if response.user:
            return {
                "user": {
                    "id": response.user.id,
                    "email": response.user.email
                },
                "session": response.session.model_dump() if response.session else None,
                "access_token": response.session.access_token if response.session else None
            }
        else:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    except Exception as e:
        error_str = str(e).lower()
        logging.error(f"Signin error: {e}")
        
        # Check for email not confirmed error
        if "email" in error_str and ("confirm" in error_str or "verify" in error_str or "not confirmed" in error_str):
            raise HTTPException(
                status_code=401, 
                detail="Email not confirmed. Please check your email and click the confirmation link before signing in."
            )
        
        # Check for invalid credentials
        if "invalid" in error_str or "credentials" in error_str or "password" in error_str:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        raise HTTPException(status_code=401, detail=f"Error signing in: {str(e)}")


@app.post("/api/auth/signout")
async def signout():
    """
    Sign out the current user
    """
    try:
        supabase.auth.sign_out()
        return {"message": "Signed out successfully"}
    except Exception as e:
        logging.error(f"Signout error: {e}")
        raise HTTPException(status_code=400, detail=f"Error signing out: {str(e)}")


# Constraints endpoints
@app.get("/api/constraints")
async def get_constraints(current_user: dict = Depends(get_current_user)):
    """
    Get all constraints for the current user
    """
    try:
        user_id = current_user["id"]
        client = supabase_admin if supabase_admin else supabase
        
        response = client.table("constraints").select("*").eq("user_id", user_id).execute()
        
        # Convert days string back to array for each constraint
        import json
        constraints_list = []
        for constraint in (response.data or []):
            days_list = []
            try:
                if isinstance(constraint.get("days"), str):
                    days_list = json.loads(constraint["days"])
                elif isinstance(constraint.get("days"), list):
                    days_list = constraint["days"]
                else:
                    days_list = [int(constraint["days"])] if constraint.get("days") else []
            except:
                # Fallback: try to parse as comma-separated string
                if isinstance(constraint.get("days"), str) and ',' in constraint["days"]:
                    days_list = [int(d.strip()) for d in constraint["days"].split(',') if d.strip().isdigit()]
                else:
                    days_list = []
            
            constraint_copy = constraint.copy()
            constraint_copy["days"] = days_list
            constraints_list.append(constraint_copy)
        
        return constraints_list
    except Exception as e:
        logging.error(f"Error fetching constraints: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching constraints: {str(e)}")


@app.post("/api/constraints")
async def create_constraint(
    constraint_data: ConstraintCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new constraint for the current user
    """
    try:
        # Get user_id - try both "id" and "sub" (JWT standard uses "sub")
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User ID not found in token")
        
        # Ensure user profile exists (create minimal if needed)
        client = supabase_admin if supabase_admin else supabase
        if client:
            try:
                existing_profile = client.table("user_profiles").select("id").eq("id", user_id).execute()
                if not existing_profile.data or len(existing_profile.data) == 0:
                    # Create minimal profile
                    profile_data = {
                        "id": user_id,
                        "email": current_user.get("email", ""),
                        "name": current_user.get("name")
                    }
                    client.table("user_profiles").insert(profile_data).execute()
                    logging.info(f"✅ Created minimal user profile for user {user_id}")
            except Exception as profile_error:
                logging.warning(f"⚠️ Could not ensure user profile exists: {profile_error}")
        
        client = supabase_admin if supabase_admin else supabase
        
        # Convert days array to string format for Supabase (TEXT field)
        # Store as JSON string or comma-separated string
        import json
        days_str = json.dumps(constraint_data.days) if isinstance(constraint_data.days, list) else str(constraint_data.days)
        
        constraint_dict = {
            "user_id": user_id,
            "title": constraint_data.title,
            "description": constraint_data.description,
            "days": days_str,
            "start_time": constraint_data.start_time,
            "end_time": constraint_data.end_time,
            "is_hard": getattr(constraint_data, "is_hard", True)
        }
        
        response = client.table("constraints").insert(constraint_dict).execute()
        
        if response.data:
            return {"message": "אילוץ נוצר בהצלחה", "constraint": response.data[0]}
        else:
            raise HTTPException(status_code=400, detail="Failed to create constraint")
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error creating constraint: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating constraint: {str(e)}")


@app.put("/api/constraints/{constraint_id}")
async def update_constraint(
    constraint_id: str,
    constraint_data: ConstraintCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Update an existing constraint
    """
    try:
        user_id = current_user["id"]
        client = supabase_admin if supabase_admin else supabase
        
        # Verify constraint belongs to user
        existing = client.table("constraints").select("id").eq("id", constraint_id).eq("user_id", user_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Constraint not found")
        
        # Convert days array to string format for Supabase (TEXT field)
        import json
        days_str = json.dumps(constraint_data.days) if isinstance(constraint_data.days, list) else str(constraint_data.days)
        
        update_data = {
            "title": constraint_data.title,
            "description": constraint_data.description,
            "days": days_str,
            "start_time": constraint_data.start_time,
            "end_time": constraint_data.end_time,
            "is_hard": getattr(constraint_data, "is_hard", True)
        }
        
        response = client.table("constraints").update(update_data).eq("id", constraint_id).execute()
        
        if response.data:
            return {"message": "אילוץ עודכן בהצלחה", "constraint": response.data[0]}
        else:
            raise HTTPException(status_code=400, detail="Failed to update constraint")
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error updating constraint: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating constraint: {str(e)}")


@app.delete("/api/constraints/{constraint_id}")
async def delete_constraint(
    constraint_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a constraint
    """
    try:
        user_id = current_user["id"]
        client = supabase_admin if supabase_admin else supabase
        
        # Verify constraint belongs to user
        existing = client.table("constraints").select("id").eq("id", constraint_id).eq("user_id", user_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Constraint not found")
        
        delete_result = client.table("constraints").delete().eq("id", constraint_id).execute()
        
        logging.info(f"✅ Constraint {constraint_id} deleted successfully for user {user_id}")
        
        return {"message": "אילוץ נמחק בהצלחה", "deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error deleting constraint: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting constraint: {str(e)}")


# Weekly constraints and weekly plan endpoints
def _parse_days(value):
    import json
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return [int(d.strip()) for d in value.split(',') if d.strip().isdigit()]
    return []


def _time_to_minutes(time_str: str) -> int:
    if not time_str:
        return 0
    # Handle both "HH:MM" and "HH:MM:SS" formats
    parts = time_str.split(":")
    if len(parts) < 2:
        return 0
    hour = int(parts[0])
    minute = int(parts[1])
    return hour * 60 + minute


def _minutes_to_time(minutes: int) -> str:
    hour = minutes // 60
    minute = minutes % 60
    return f"{hour:02d}:{minute:02d}"


def _build_time_slots(start_hour: int = 8, end_hour: int = 20, slot_minutes: int = 60):
    slots = []
    for hour in range(start_hour, end_hour + 1):
        slots.append(f"{hour:02d}:00")
    return slots


def _extract_semester_season(semester_str: str):
    if not semester_str:
        return None
    semester_str = str(semester_str).strip()
    if "חורף" in semester_str or "winter" in semester_str.lower():
        return "חורף"
    if "אביב" in semester_str or "spring" in semester_str.lower():
        return "אביב"
    if "קיץ" in semester_str or "summer" in semester_str.lower():
        return "קיץ"
    return semester_str


def _ensure_group_blocks_for_week(client, user_id: str, week_start: str, available_slots):
    """
    Create group_plan_blocks once per group per week and post an update to the group.
    Returns updated available_slots and the map of course_number -> group info.
    """
    group_members_result = client.table("group_members").select("group_id,status").eq("user_id", user_id).execute()
    group_ids = [gm["group_id"] for gm in (group_members_result.data or []) if gm.get("status") == "approved"]

    group_map = {}
    for group_id in group_ids:
        group_result = client.table("study_groups").select("id,course_id,course_name,group_name").eq("id", group_id).limit(1).execute()
        if group_result.data:
            group = group_result.data[0]
            group_map[group["course_id"]] = {
                "group_id": group["id"],
                "course_name": group.get("course_name"),
                "group_name": group.get("group_name")
            }

            # If group blocks already exist for this week, REMOVE THEM from available_slots and skip creation
            existing_blocks_res = client.table("group_plan_blocks").select("*").eq("group_id", group_id).eq("week_start", week_start).execute()
            if existing_blocks_res.data:
                for block in existing_blocks_res.data:
                    day = block["day_of_week"]
                    time = block["start_time"]
                    if (day, time) in available_slots:
                        available_slots.remove((day, time))
                continue

            # Create a default group session (2 hours) from available slots
            created_blocks = []
            for _ in range(2):
                if not available_slots:
                    break
                day, time = available_slots.pop(0)
                created_blocks.append({
                    "group_id": group_id,
                    "week_start": week_start,
                    "course_number": group.get("course_id"),
                    "day_of_week": day,
                    "start_time": time,
                    "end_time": _minutes_to_time(_time_to_minutes(time) + 60),
                    "created_by": user_id
                })

            if created_blocks:
                client.table("group_plan_blocks").insert(created_blocks).execute()
                try:
                    day_names = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
                    daily_blocks = {}
                    for b in created_blocks:
                        daily_blocks.setdefault(b["day_of_week"], []).append((b["start_time"], b["end_time"]))

                    def _merge_ranges(ranges):
                        ranges_sorted = sorted(ranges, key=lambda r: r[0])
                        merged = []
                        for start, end in ranges_sorted:
                            if not merged:
                                merged.append([start, end])
                                continue
                            last_start, last_end = merged[-1]
                            if start <= last_end:
                                merged[-1][1] = max(last_end, end)
                            else:
                                merged.append([start, end])
                        return merged

                    summary_lines = []
                    for d in sorted(daily_blocks.keys()):
                        merged = _merge_ranges(daily_blocks[d])
                        ranges_str = ", ".join([f"{s}-{e}" for s, e in merged])
                        summary_lines.append(f"{day_names[d]} {ranges_str}")

                    try:
                        d_parts = week_start.split('-')
                        concise_date = f"{d_parts[2]}/{d_parts[1]}"
                    except Exception:
                        concise_date = week_start

                    summary_text = f"פגישות קבוצתיות לשבוע ה-{concise_date}:\n" + "\n".join(summary_lines)

                    # Group updates feed
                    client.table("group_updates").insert({
                        "group_id": group_id,
                        "update_text": summary_text,
                        "update_type": "info"
                    }).execute()

                    # System message in group chat (use a real user_id to avoid NOT NULL issues)
                    # Get first member of the group to use as system user
                    group_members_result = client.table("group_members").select("user_id").eq("group_id", group_id).eq("status", "approved").limit(1).execute()
                    system_user_id = group_members_result.data[0]["user_id"] if group_members_result.data else user_id
                    client.table("group_messages").insert({
                        "group_id": group_id,
                        "user_id": system_user_id,
                        "sender_name": "🤖 סוכן אקדמי",
                        "message": summary_text,
                        "is_system": True
                    }).execute()

                except Exception as update_error:
                    logging.warning(f"Failed to post group update for {group_id}: {update_error}")

    return available_slots, group_map


def _get_week_start(date_obj: datetime) -> str:
    # Week starts on Sunday (0)
    days_since_sunday = (date_obj.weekday() + 1) % 7
    sunday = date_obj - timedelta(days=days_since_sunday)
    return sunday.strftime("%Y-%m-%d")


async def _refine_schedule_with_llm(
    skeleton_blocks: list,
    available_slots: list,
    courses: list,
    user_preferences_raw: str,
    user_preferences_summary: dict,
    time_slots: list,
    force_exact_count: bool = False,
    required_total_override: Optional[int] = None,
    user_id: str = None
) -> dict:
    """
    Use GPT-4o mini to refine the schedule by optimally placing personal study blocks.
    
    Args:
        skeleton_blocks: List of already-placed blocks (group meetings, fixed blocks)
        available_slots: List of (day, time) tuples still available
        courses: List of courses with their requirements
        user_preferences_raw: Raw user text about preferences
        user_preferences_summary: LLM-extracted structured preferences
        time_slots: List of all time slots
        
    Returns:
        dict with 'success', 'blocks' (refined schedule), 'message'
    """
    # #region agent log
    _debug_log_path = r"c:\DS\AcademicPlanner\ds_project\.cursor\debug.log"
    def _debug_log(hyp, msg, data):
        import json as _j
        with open(_debug_log_path, "a", encoding="utf-8") as _f:
            _f.write(_j.dumps({"hypothesisId": hyp, "location": "main.py:_refine_schedule_with_llm", "message": msg, "data": data, "timestamp": int(__import__("time").time()*1000)}) + "\n")
    _debug_log("C", "ENTRY: Input params", {"user_id": user_id, "courses_count": len(courses), "available_slots_count": len(available_slots), "skeleton_blocks_count": len(skeleton_blocks), "prefs_len": len(user_preferences_raw or "")})
    # #endregion
    if not HAS_OPENAI:
        logging.warning("OpenAI not available, skipping LLM refinement")
        return {"success": False, "blocks": [], "message": "OpenAI not configured"}
    
    try:
        openai_api_key = os.getenv('OPENAI_API_KEY')
        if not openai_api_key:
            logging.warning("OPENAI_API_KEY not found in environment")
            return {"success": False, "blocks": [], "message": "OpenAI API key missing"}
        
        base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        if base_url:
            client = OpenAI(api_key=openai_api_key, base_url=base_url)
            logging.info(f"LLM base_url configured: {base_url}")
        else:
            client = OpenAI(api_key=openai_api_key)
        
        # Calculate how many personal blocks are needed per course
        # Use course_time_preferences if available to adjust distribution
        course_requirements = []
        for course in courses:
            course_number = course.get("course_number")
            course_name = course.get("course_name")
            credit_points = course.get("credit_points") or 3
            total_hours = credit_points * 3
            
            # Count group blocks already allocated
            group_hours = sum(1 for b in skeleton_blocks if b.get("course_number") == course_number and b.get("work_type") == "group")
            
            # Try to get user's preferred hours from course_time_preferences
            # This is updated when user requests more/less hours
            personal_hours_preferred = max(1, int(total_hours * 0.5))  # Default 50% of total
            if user_id:
                try:
                    pref_result = client.table("course_time_preferences").select("personal_hours_per_week").eq("user_id", user_id).eq("course_number", course_number).limit(1).execute()
                    if pref_result.data and pref_result.data[0].get("personal_hours_per_week") is not None:
                        # Round to nearest integer when planning
                        personal_hours_preferred = round(float(pref_result.data[0]["personal_hours_per_week"]))
                        logging.info(f"Using course_time_preferences for {course_number}: personal_hours_per_week={personal_hours_preferred} (rounded from {pref_result.data[0]['personal_hours_per_week']})")
                except Exception as pref_err:
                    logging.warning(f"Could not load course_time_preferences: {pref_err}")
            
            # Calculate personal hours needed: preferred hours minus already allocated group hours
            personal_hours_needed = max(0, personal_hours_preferred - group_hours)
            
            course_requirements.append({
                "course_number": course_number,
                "course_name": course_name,
                "credit_points": credit_points,
                "personal_hours_needed": personal_hours_needed,
                "group_hours_allocated": group_hours
            })
        
        required_total = sum(c["personal_hours_needed"] for c in course_requirements)
        if required_total_override is not None:
            required_total = required_total_override

        # Day names for readability
        day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        
        # Build available slots in readable format
        available_slots_readable = [
            {"day": day_names[day], "day_index": day, "time": time}
            for day, time in available_slots
        ]
        
        # Build skeleton blocks in readable format
        skeleton_blocks_readable = [
            {
                "day": day_names[b["day_of_week"]],
                "day_index": b["day_of_week"],
                "start_time": b["start_time"],
                "end_time": b["end_time"],
                "course_name": b.get("course_name"),
                "type": b.get("work_type")
            }
            for b in skeleton_blocks
        ]
        
        # Build the prompt
        system_prompt = """You are a schedule optimization assistant. Your task is to place personal study blocks for courses based on user preferences.

STRICT RULES:
1. You MUST NOT modify or move any blocks in the skeleton (group meetings or fixed blocks)
2. You can ONLY place new personal study blocks in the available slots
3. Each block is exactly 1 hour
4. You must allocate the EXACT number of personal hours required for each course
5. Return ONLY valid JSON, no explanations

CRITICAL - USER PREFERENCES ARE THE TOP PRIORITY:
- The user's preferences may be in Hebrew or English - understand and follow them exactly
- First INTERPRET what the user wants, then APPLY it to the schedule
- Common preferences:
  * Wants breaks/gaps between study sessions = DO NOT place consecutive hours for the same course
  * Wants concentrated/focused study = place multiple hours together
  * Wants even distribution = spread across ALL available days, not just a few
  * Prefers morning = use early time slots
  * Prefers evening = use late time slots
- If the user says they want breaks, you MUST leave at least 1-2 hours gap between study blocks

OUTPUT FORMAT:
{
  "personal_blocks": [
    {
      "course_number": "10401",
      "course_name": "Course Name",
      "day_index": 0,
      "start_time": "09:00"
    }
  ]
}"""
        if force_exact_count:
            system_prompt += f"\nTOTAL PERSONAL BLOCKS REQUIRED: {required_total}\nYou MUST return exactly this number of personal_blocks."

        user_prompt = f"""Please optimally place personal study blocks for the following schedule:

COURSE REQUIREMENTS:
{json.dumps(course_requirements, indent=2)}

ALREADY PLACED BLOCKS (DO NOT MODIFY):
{json.dumps(skeleton_blocks_readable, indent=2)}

AVAILABLE TIME SLOTS:
{json.dumps(available_slots_readable, indent=2)}

USER PREFERENCES (RAW):
{user_preferences_raw or "No specific preferences provided"}

USER PREFERENCES (STRUCTURED):
{json.dumps(user_preferences_summary, indent=2) if user_preferences_summary else "{}"}

TASK:
Place the required personal study blocks for each course in the available slots.

CRITICAL: First, read and understand the USER PREFERENCES above (may be in Hebrew or any language).
Then apply those preferences strictly when placing blocks.

If user mentions wanting breaks or gaps - spread blocks across different days and times, NOT consecutive.
If user mentions wanting focus or concentration - group blocks together.
If no clear preference - distribute evenly across all available days.

Return the JSON with your placement.

Return only the JSON with personal_blocks array."""
        if force_exact_count:
            user_prompt += f"\nTOTAL PERSONAL BLOCKS REQUIRED: {required_total}.\nYou MUST return exactly this number of personal_blocks."

        logging.info(
            f"[LLM] Starting refinement: courses={len(course_requirements)}, "
            f"available_slots={len(available_slots)}, preferences_length={len(user_preferences_raw or '')}, "
            f"required_total={required_total}, force_exact={force_exact_count}"
        )
        # #region agent log
        _debug_log("C", "PRE-LLM: course_requirements", {"required_total": required_total, "course_requirements": course_requirements})
        _debug_log("D", "PRE-LLM: available_slots sample", {"slots_count": len(available_slots), "first_5": available_slots[:5] if available_slots else []})
        # #endregion

        # Call LLM (configurable model)
        model = os.getenv("LLM_MODEL") or "gpt-4o-mini"
        base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        logging.info(f"[LLM] Calling model={model}, base_url={base_url}")
        # #region agent log
        _debug_log("A", "PRE-API: LLM config", {"model": model, "base_url": base_url, "has_api_key": bool(openai_api_key)})

        # gpt-5 family requires temperature=1 with this provider
        temperature = 0.7
        if "gpt-5" in model.lower() or (base_url and "llmod.ai" in base_url.lower()):
            temperature = 1
        logging.info(f"[LLM] Using temperature={temperature}")

        # #region agent log
        _debug_log("B", "PRE-API: Request params", {"temperature": temperature, "max_tokens": 4000, "response_format": "json_object"})
        # #endregion
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=4000,
                response_format={"type": "json_object"}
            )
        except Exception as api_err:
            # #region agent log
            _debug_log("A", "API ERROR", {"error": str(api_err), "error_type": type(api_err).__name__})
            # #endregion
            raise
        
        # Parse response
        content = response.choices[0].message.content
        finish_reason = response.choices[0].finish_reason
        logging.info(f"[LLM] Response received: {len(content) if content else 0} chars, finish_reason={finish_reason}")
        logging.info(f"[LLM] Response (truncated): {(content[:500] if content else 'EMPTY')}")
        # #region agent log
        _debug_log("F", "POST-API: Response metadata", {"content_len": len(content) if content else 0, "finish_reason": finish_reason, "content_preview": (content[:300] if content else "EMPTY")})
        _debug_log("FULL", "LLM FULL RESPONSE", {"user_id": user_id, "user_prefs": user_preferences_raw, "full_response": content, "required_total": required_total})
        # #endregion
        
        # Handle empty content
        if not content or content.strip() == "":
            # #region agent log
            _debug_log("F", "EMPTY CONTENT", {"finish_reason": finish_reason, "full_response_type": type(response).__name__})
            # #endregion
            logging.error(f"[LLM] Empty content returned! finish_reason={finish_reason}")
            return {"success": False, "blocks": [], "message": f"LLM returned empty content (finish_reason={finish_reason})"}
        
        try:
            llm_output = json.loads(content)
        except json.JSONDecodeError as json_err:
            # #region agent log
            _debug_log("E", "JSON PARSE ERROR", {"error": str(json_err), "content": content[:500]})
            # #endregion
            raise
        personal_blocks = llm_output.get("personal_blocks", [])
        
        logging.info(f"[LLM] Proposed {len(personal_blocks)} personal blocks")
        
        # Store debug info (temporary)
        if user_id:
            _llm_debug_cache[user_id] = {
                "timestamp": datetime.utcnow().isoformat(),
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response": content,
                "parsed_blocks": personal_blocks,
                "model": model,
                "temperature": temperature,
                "force_exact_count": force_exact_count,
                "required_total": required_total
            }
        
        # #region agent log
        _debug_log("SUCCESS", "LLM SUCCESS", {"blocks_count": len(personal_blocks), "required_total": required_total})
        # #endregion
        return {
            "success": True,
            "blocks": personal_blocks,
            "required_total": required_total,
            "message": f"LLM refinement successful, proposed {len(personal_blocks)} blocks"
        }
        
    except Exception as e:
        logging.error(f"LLM refinement error: {e}")
        import traceback
        tb = traceback.format_exc()
        logging.error(tb)
        # #region agent log
        _debug_log("FAIL", "LLM EXCEPTION", {"error": str(e), "error_type": type(e).__name__, "traceback": tb[:500]})
        # #endregion
        return {
            "success": False,
            "blocks": [],
            "message": f"LLM refinement failed: {str(e)}"
        }


async def _summarize_user_preferences_with_llm(
    preferences_raw: str,
    schedule_change_notes: list
) -> Optional[dict]:
    """
    Use LLM to summarize user preferences from raw text + schedule change notes.
    
    Args:
        preferences_raw: User's raw preference text
        schedule_change_notes: List of notes from schedule changes (why user needed more/less hours)
        
    Returns:
        dict with structured preferences, or None if failed
    """
    if not HAS_OPENAI:
        logging.warning("OpenAI not available for preferences summary")
        return None
    
    # If no meaningful input, skip
    if not preferences_raw and not schedule_change_notes:
        return None
    
    try:
        # Get LLM configuration
        llm_base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        api_key = os.getenv("OPENAI_API_KEY")
        
        if not api_key:
            logging.warning("No API key for preferences summary")
            return None
        
        openai_client = OpenAI(api_key=api_key, base_url=llm_base_url)
        
        # Build input for LLM - only use the LAST note (most recent) to keep prompt short
        # This prevents token limit issues with reasoning models
        notes_text = ""
        if schedule_change_notes:
            # Only use the most recent note to avoid token limit issues
            last_note = schedule_change_notes[-1] if schedule_change_notes else None
            if last_note and isinstance(last_note, dict):
                course = last_note.get('course', '?')
                change = last_note.get('change', '?')
                explanation = last_note.get('explanation', 'no reason')
                notes_text = f"\\n\\nMost recent schedule change:\\nCourse {course}: {change}\\nExplanation: {explanation}"
        
        system_prompt = """You are a study preferences analyzer. Your task is to classify user explanations and extract structured preferences.

STEP 1: CLASSIFICATION - First, determine what type of update is needed:
- "hours_distribution": The user wants to change how many hours they spend on a course (more/less time needed)
- "general_preferences": The user wants to change study habits, timing, breaks, concentration style, etc.

STEP 2: EXTRACTION - Based on the classification, extract the relevant information:

If classification is "hours_distribution":
- Identify which course(s) the user is referring to
- Determine if they want MORE hours or LESS hours
- Set "hours_change": "more" or "less" in course_notes
- Example: "לא צריך כל כך הרבה שעות" → hours_change: "less"
- Example: "צריך יותר זמן" → hours_change: "more"

If classification is "general_preferences":
- Extract preferences about: study times, break frequency, session length, concentration style
- Update the relevant preference fields
- Example: "פחות הפסקות" → break_preference: "few"
- Example: "אני צריך הפסקות" → break_preference: "frequent"

The user may write in Hebrew or English. Understand the intent and context, not just keywords.

Output ONLY valid JSON with these fields:
{
  "update_type": "hours_distribution" | "general_preferences",  // CRITICAL: First classify the intent
  "preferred_study_times": ["morning", "afternoon", "evening"],  // when they prefer to study (for general_preferences)
  "session_length_preference": "short" | "medium" | "long",  // 1h, 2-3h, or 4h+ (for general_preferences)
  "break_preference": "frequent" | "moderate" | "few",  // how often they want breaks (for general_preferences)
  "concentration_style": "scattered" | "balanced" | "concentrated",  // spread vs grouped sessions (for general_preferences)
  "course_notes": [  // REQUIRED if update_type is "hours_distribution"
    {"course": "10407", "note": "user wants less hours", "hours_change": "less"}  // hours_change: "more" | "less"
  ],
  "general_notes": "summary of preferences (for general_preferences type)"
}"""
        
        user_prompt = f"""User's preferences:
{preferences_raw}
{notes_text}

Extract structured preferences as JSON."""
        
        # LOG: Input to LLM
        logging.info(f"🔍 [LLM CLASSIFICATION] Input to LLM:")
        logging.info(f"   - preferences_raw length: {len(preferences_raw or '')}")
        logging.info(f"   - schedule_change_notes count: {len(schedule_change_notes)}")
        if schedule_change_notes:
            last_note = schedule_change_notes[-1] if schedule_change_notes else {}
            logging.info(f"   - Last note: course={last_note.get('course')}, change={last_note.get('change')}, explanation={last_note.get('explanation', '')[:100]}")
        
        # Set temperature based on model
        temperature = 1 if ("gpt-5" in llm_model.lower() or "llmod.ai" in llm_base_url.lower()) else 0.3
        
        response = openai_client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature,
            max_tokens=2000,  # Increased for models with reasoning tokens (gpt-5)
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        if not content:
            logging.warning(f"⚠️ [LLM CLASSIFICATION] LLM returned empty content")
            logging.warning(f"⚠️ [LLM CLASSIFICATION] Response object: {response}")
            logging.warning(f"⚠️ [LLM CLASSIFICATION] Choices count: {len(response.choices) if response.choices else 0}")
            if response.choices:
                logging.warning(f"⚠️ [LLM CLASSIFICATION] First choice finish_reason: {response.choices[0].finish_reason}")
            return None
        
        try:
            summary = json.loads(content)
        except json.JSONDecodeError as json_err:
            logging.error(f"❌ [LLM CLASSIFICATION] Failed to parse JSON response: {json_err}")
            logging.error(f"❌ [LLM CLASSIFICATION] Content received (first 500 chars): {content[:500]}")
            return None
        
        # LOG: LLM Response
        update_type = summary.get("update_type", "unknown")
        course_notes = summary.get("course_notes", [])
        logging.info(f"✅ [LLM CLASSIFICATION] LLM Response:")
        logging.info(f"   - update_type: {update_type}")
        logging.info(f"   - course_notes count: {len(course_notes)}")
        if course_notes:
            for note in course_notes:
                logging.info(f"   - course_note: course={note.get('course')}, hours_change={note.get('hours_change')}, note={note.get('note', '')[:50]}")
        if update_type == "general_preferences":
            logging.info(f"   - break_preference: {summary.get('break_preference')}")
            logging.info(f"   - preferred_study_times: {summary.get('preferred_study_times')}")
            logging.info(f"   - general_notes: {summary.get('general_notes', '')[:100]}")
        logging.info(f"   - All summary keys: {list(summary.keys())}")
        
        return summary
        
    except Exception as e:
        logging.error(f"Failed to summarize preferences with LLM: {e}")
        return None


def _run_weekly_auto_for_all_users_sync():
    """
    Sync wrapper for APScheduler (APScheduler can't call async functions directly).
    """
    asyncio.run(_run_weekly_auto_for_all_users())


async def _run_weekly_auto_for_all_users(week_start_override: Optional[str] = None):
    """
    Final Refined Global Scheduler Agent:
    1. Clear old data for the week.
    2. Calculate quotas: credits * 3 total. Split 50/50 (remainder to personal).
    3. Global Sync: Find long blocks (2-3h) for group work for ALL members.
    4. Individual Fill: Find long blocks for personal work.
    """
    try:
        client = supabase_admin if supabase_admin else supabase
        if not client:
            logging.error("Weekly scheduler: Supabase client not configured")
            return

        # 1. Determine the week (Next Sunday by default, or override)
        if week_start_override:
            week_start = week_start_override
        else:
            current_week_start = _get_week_start(datetime.utcnow())
            next_week_start_dt = datetime.strptime(current_week_start, "%Y-%m-%d") + timedelta(days=7)
            week_start = next_week_start_dt.strftime("%Y-%m-%d")
        
        logging.info(f"🚀 [GLOBAL AGENT] Starting weekly planning for week {week_start}")

        # 2. Cleanup
        # Since we have cascade deletes, deleting the plans will delete the blocks
        logging.info(f"🧹 [GLOBAL AGENT] Cleaning up old data for week {week_start}")
        try:
            client.table("weekly_plans").delete().eq("week_start", week_start).execute()
            client.table("group_plan_blocks").delete().eq("week_start", week_start).execute()
            # Also clear notifications for this week to avoid duplicates
            client.table("notifications").delete().eq("type", "plan_ready").like("link", f"%week={week_start}%").execute()
        except Exception as cleanup_err:
            logging.warning(f"⚠️ Cleanup warning: {cleanup_err}")

        # 3. Get all users and their active courses (from Supabase only)
        users_result = client.table("user_profiles").select("id").execute()
        users = users_result.data or []
        user_ids = [u["id"] for u in users]
        
        # user_id -> set of (day, time) that are BLOCKED
        user_blocked_slots = {uid: set() for uid in user_ids}
        # user_id -> set of active course_numbers
        user_active_courses = {uid: set() for uid in user_ids}
        time_slots = _build_time_slots()
        
        # Get valid catalog courses
        catalog_res = client.table("course_catalog").select("course_number").execute()
        valid_course_numbers = {c["course_number"] for c in (catalog_res.data or [])}

        for u in users:
            uid = u["id"]
            
            # Fetch user's courses
            courses_res = client.table("courses").select("*").eq("user_id", uid).execute()
            all_u_courses = courses_res.data or []
            
            for c in all_u_courses:
                c_num = str(c.get("course_number")).strip()
                if c_num in valid_course_numbers:
                    user_active_courses[uid].add(c_num)
                else:
                    logging.warning(f"❌ [GLOBAL AGENT] User {uid} has course {c_num} which is NOT in the catalog. Rejecting for planning.")
            
            logging.info(f"   👤 User {uid}: {len(user_active_courses[uid])} VALID courses available for planning")
            
            # Permanent constraints (FETCH THEM HERE!)
            pc_res = client.table("constraints").select("*").eq("user_id", uid).execute()
            for c in (pc_res.data or []):
                for day in _parse_days(c.get("days")):
                    for t in time_slots:
                        if _time_to_minutes(t) >= _time_to_minutes(c["start_time"]) and _time_to_minutes(t) < _time_to_minutes(c["end_time"]):
                            user_blocked_slots[uid].add((day, t))
            
            # Weekly constraints
            wc_res = client.table("weekly_constraints").select("*").eq("user_id", uid).eq("week_start", week_start).execute()
            for c in (wc_res.data or []):
                if c.get("is_hard", True):
                    for day in _parse_days(c.get("days")):
                        for t in time_slots:
                            if _time_to_minutes(t) >= _time_to_minutes(c["start_time"]) and _time_to_minutes(t) < _time_to_minutes(c["end_time"]):
                                user_blocked_slots[uid].add((day, t))

        # 4. Phase 2: Global Group Synchronization
        groups_res = client.table("study_groups").select("*").execute()
        groups = groups_res.data or []
        
        # Load catalog for proper course names
        catalog_res_for_groups = client.table("course_catalog").select("course_number,course_name").execute()
        catalog_name_map = {str(c["course_number"]).strip(): c["course_name"] for c in (catalog_res_for_groups.data or [])}
        
        for group in groups:
            group_id = group["id"]
            course_number = group.get("course_id") # Note: This field is expected to be the course_number
            # ALWAYS use catalog name to avoid gibberish
            course_name = catalog_name_map.get(str(course_number).strip()) or group.get("course_name") or "Group Work"
            
            # Get members
            members_res = client.table("group_members").select("user_id").eq("group_id", group_id).eq("status", "approved").execute()
            all_member_ids = [m["user_id"] for m in (members_res.data or [])]
            
            # Filter members to only those taking this course THIS semester
            member_ids = [mid for mid in all_member_ids if mid in user_active_courses and course_number in user_active_courses[mid]]
            
            if not member_ids:
                logging.info(f"👥 [GLOBAL AGENT] Skipping group {course_name} - no active members in this course")
                continue
            
            # Quota calculation for group: use group_preferences if available
            # This is updated when all members approve a change request
            group_quota = 4  # Default to 4h for group (half of 3*3=9)
            try:
                group_pref_result = client.table("group_preferences").select("preferred_hours_per_week").eq("group_id", group_id).limit(1).execute()
                if group_pref_result.data and group_pref_result.data[0].get("preferred_hours_per_week") is not None:
                    group_quota = group_pref_result.data[0]["preferred_hours_per_week"]
                    logging.info(f"Using group_preferences for group {group_id}: {group_quota}h per week")
            except Exception as gp_err:
                logging.warning(f"Could not load group_preferences: {gp_err}")
            
            # 4. Global Group Synchronization
            allocated_count = 0
            daily_ranges = {} # Track ranges for combined message
            
            for day in range(7):
                if allocated_count >= group_quota: break
                
                # Look for a 2-hour block
                for i in range(len(time_slots) - 1):
                    if allocated_count >= group_quota: break
                    t1, t2 = time_slots[i], time_slots[i+1]
                    
                    # Check all members
                    all_free = True
                    for mid in member_ids:
                        if mid in user_blocked_slots:
                            if (day, t1) in user_blocked_slots[mid] or (day, t2) in user_blocked_slots[mid]:
                                all_free = False
                                break
                    
                    if all_free:
                        # Found a 2h block!
                        new_blocks = []
                        end_t = _minutes_to_time(_time_to_minutes(t2) + 60)
                        
                        for t in [t1, t2]:
                            new_blocks.append({
                                "group_id": group_id,
                                "week_start": week_start,
                                "course_number": course_number,
                                "day_of_week": day,
                                "start_time": t,
                                "end_time": _minutes_to_time(_time_to_minutes(t) + 60),
                                "created_by": member_ids[0]
                            })
                            for mid in member_ids:
                                if mid in user_blocked_slots:
                                    user_blocked_slots[mid].add((day, t))
                        
                        client.table("group_plan_blocks").insert(new_blocks).execute()
                        allocated_count += 2
                        
                        if day not in daily_ranges: daily_ranges[day] = []
                        daily_ranges[day].append(f"{t1}-{end_t}")
                        logging.info(f"👥 [GLOBAL AGENT] Scheduled 2h group for {course_name} on day {day} at {t1}")

            # Post ONE consolidated update if any blocks were scheduled
            if daily_ranges:
                try:
                    day_names = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
                    summary_lines = []
                    for d in sorted(daily_ranges.keys()):
                        summary_lines.append(f"{day_names[d]} {', '.join(daily_ranges[d])}")
                    
                    # Formatting week start date to DD/MM
                    try:
                        d_parts = week_start.split('-')
                        concise_date = f"{d_parts[2]}/{d_parts[1]}"
                    except:
                        concise_date = week_start

                    summary_text = f"פגישות קבוצתיות בשבוע הבא ה-{concise_date}:\n" + "\n".join(summary_lines)
                    
                    # 1. Post to chat as a system message (PRIMARY)
                    logging.info(f"💬 [GLOBAL AGENT] Sending system message to group {group_id} chat")
                    try:
                        system_user_id = member_ids[0] if member_ids else None
                        if not system_user_id:
                            logging.warning(f"⚠️ [GLOBAL AGENT] No member_ids for group {group_id}, skipping system message")
                            raise Exception("No group members available for system message")
                        client.table("group_messages").insert({
                            "group_id": group_id,
                            "user_id": system_user_id,
                            "sender_name": "🤖 סוכן אקדמי",
                            "message": summary_text,
                            "is_system": True
                        }).execute()
                        logging.info(f"✅ [GLOBAL AGENT] System message sent to group {group_id}")
                    except Exception as msg_err:
                        logging.error(f"❌ [GLOBAL AGENT] Failed to send system message to group {group_id}: {msg_err}")
                    
                    # 2. Update Feed (Pink box)
                    logging.info(f"📢 [GLOBAL AGENT] Sending feed update to group {group_id}")
                    try:
                        client.table("group_updates").insert({
                            "group_id": group_id,
                            "update_text": summary_text,
                            "update_type": "info"
                        }).execute()
                        logging.info(f"✅ [GLOBAL AGENT] Feed update sent to group {group_id}")
                    except Exception as feed_err:
                        logging.error(f"❌ [GLOBAL AGENT] Failed to send feed update to group {group_id}: {feed_err}")
                    
                    # 3. Do not send per-group notifications (single plan_ready per user only)
                        
                except Exception as update_err:
                    logging.error(f"💥 [GLOBAL AGENT] Critical error in group update for {group_id}: {update_err}", exc_info=True)

        # 5. Phase 3: Individual User Planning
        logging.info(f"👤 [GLOBAL AGENT] Starting individual planning for {len(user_ids)} users")
        for uid in user_ids:
            try:
                # Check if user has any active courses before planning
                if not user_active_courses[uid]:
                    logging.info(f"   ⏭️ Skipping user {uid} - no active courses")
                    continue

                # #region agent log
                try:
                    import json
                    with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"app/main.py:1951","message":"_run_weekly_auto: calling generate_weekly_plan","data":{"user_id":uid,"week_start":week_start},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                except: pass
                # #endregion
                fake_user = {"id": uid, "sub": uid}
                plan_res = await generate_weekly_plan(week_start, fake_user, notify=False)
                # #region agent log
                try:
                    import json
                    with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"app/main.py:1952","message":"_run_weekly_auto: generate_weekly_plan returned","data":{"user_id":uid,"week_start":week_start,"plan_res_message":plan_res.get("message") if plan_res else None,"has_plan_id":bool(plan_res.get("plan_id") if plan_res else False),"blocks_count":len(plan_res.get("blocks", [])) if plan_res else 0},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                except: pass
                # #endregion
                
                # Only notify if a plan was actually created (even if no blocks were found, but courses exist)
                if plan_res and (plan_res.get("plan_id") or plan_res.get("blocks") is not None):
                    # Notify user that their plan is ready
                    try:
                        notif_data = {
                            "user_id": uid,
                            "type": "plan_ready",
                            "title": "המערכת השבועית שלך מוכנה! 📅",
                            "message": f"הסוכן סיים לתכנן את המערכת שלך לשבוע הבא ({week_start}). מוזמן להסתכל ולעדכן!",
                            "link": f"/schedule?week={week_start}",
                            "read": False
                        }
                        logging.info(f"   🔔 Sending plan_ready notification to user {uid}")
                        client.table("notifications").insert(notif_data).execute()
                    except Exception as notif_err:
                        logging.warning(f"⚠️ Failed to notify user {uid} about plan ready: {notif_err}")
                else:
                    logging.info(f"   ⏭️ No plan created for user {uid}: {plan_res.get('message') if plan_res else 'Unknown'}")
                    
            except Exception as e:
                logging.error(f"❌ [GLOBAL AGENT] Individual plan failed for {uid}: {e}")

        logging.info(f"✅ [GLOBAL AGENT] Weekly planning complete")
    except Exception as e:
        logging.error(f"💥 [GLOBAL AGENT] CRITICAL ERROR: {e}")


@app.get("/api/weekly-constraints")
async def get_weekly_constraints(
    week_start: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        client = supabase_admin if supabase_admin else supabase
        
        # Get weekly constraints (one-time constraints for this week)
        weekly_response = client.table("weekly_constraints").select("*").eq("user_id", user_id).eq("week_start", week_start).execute()
        weekly_constraints_list = []
        for constraint in (weekly_response.data or []):
            constraint_copy = constraint.copy()
            constraint_copy["days"] = _parse_days(constraint.get("days"))
            constraint_copy["is_permanent"] = False  # Mark as weekly (not permanent)
            weekly_constraints_list.append(constraint_copy)
        
        # Get permanent constraints (recurring constraints)
        permanent_response = client.table("constraints").select("*").eq("user_id", user_id).execute()
        permanent_constraints_list = []
        import json
        for constraint in (permanent_response.data or []):
            constraint_copy = constraint.copy()
            # Parse days
            days_list = []
            try:
                if isinstance(constraint.get("days"), str):
                    days_list = json.loads(constraint["days"])
                elif isinstance(constraint.get("days"), list):
                    days_list = constraint["days"]
            except:
                days_list = []
            constraint_copy["days"] = days_list
            constraint_copy["is_permanent"] = True  # Mark as permanent
            permanent_constraints_list.append(constraint_copy)
        
        # Combine both types
        all_constraints = weekly_constraints_list + permanent_constraints_list
        
        return {
            "constraints": all_constraints,
            "weekly_constraints": weekly_constraints_list,
            "permanent_constraints": permanent_constraints_list
        }
    except Exception as e:
        logging.error(f"Error fetching constraints: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching constraints: {str(e)}")


@app.post("/api/weekly-constraints")
async def create_weekly_constraint(
    constraint_data: WeeklyConstraintCreate,
    current_user: dict = Depends(get_current_user)
):
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        client = supabase_admin if supabase_admin else supabase
        import json
        days_str = json.dumps(constraint_data.days) if isinstance(constraint_data.days, list) else str(constraint_data.days)
        constraint_dict = {
            "user_id": user_id,
            "title": constraint_data.title,
            "description": constraint_data.description,
            "days": days_str,
            "start_time": constraint_data.start_time,
            "end_time": constraint_data.end_time,
            "week_start": constraint_data.week_start,
            "is_hard": constraint_data.is_hard
        }
        response = client.table("weekly_constraints").insert(constraint_dict).execute()
        if response.data:
            return {"message": "אילוץ שבועי נוצר בהצלחה", "constraint": response.data[0]}
        raise HTTPException(status_code=400, detail="Failed to create weekly constraint")
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error creating weekly constraint: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating weekly constraint: {str(e)}")


@app.delete("/api/weekly-constraints/{constraint_id}")
async def delete_weekly_constraint(
    constraint_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        client = supabase_admin if supabase_admin else supabase
        existing = client.table("weekly_constraints").select("id").eq("id", constraint_id).eq("user_id", user_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Weekly constraint not found")
        client.table("weekly_constraints").delete().eq("id", constraint_id).execute()
        return {"message": "אילוץ שבועי נמחק בהצלחה", "deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error deleting weekly constraint: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting weekly constraint: {str(e)}")


@app.put("/api/weekly-constraints/{constraint_id}")
async def update_weekly_constraint(
    constraint_id: str,
    constraint_data: WeeklyConstraintCreate,
    current_user: dict = Depends(get_current_user)
):
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        client = supabase_admin if supabase_admin else supabase

        existing = client.table("weekly_constraints").select("id").eq("id", constraint_id).eq("user_id", user_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Weekly constraint not found")

        import json
        days_str = json.dumps(constraint_data.days) if isinstance(constraint_data.days, list) else str(constraint_data.days)
        update_data = {
            "title": constraint_data.title,
            "description": constraint_data.description,
            "days": days_str,
            "start_time": constraint_data.start_time,
            "end_time": constraint_data.end_time,
            "week_start": constraint_data.week_start,
            "is_hard": constraint_data.is_hard
        }
        response = client.table("weekly_constraints").update(update_data).eq("id", constraint_id).execute()
        if response.data:
            return {"message": "אילוץ שבועי עודכן בהצלחה", "constraint": response.data[0]}
        raise HTTPException(status_code=400, detail="Failed to update weekly constraint")
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error updating weekly constraint: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating weekly constraint: {str(e)}")


@app.get("/api/weekly-plan")
async def get_weekly_plan(
    week_start: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        # #region agent log
        import json
        try:
            with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"app/main.py:2093","message":"get_weekly_plan entry","data":{"user_id_from_auth":current_user.get("id") or current_user.get("sub"),"week_start":week_start},"timestamp":int(__import__('time').time()*1000)}) + '\n')
        except: pass
        # #endregion
        user_id = current_user.get("id") or current_user.get("sub")
        # #region agent log
        try:
            with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"app/main.py:2094","message":"user_id extracted","data":{"user_id":user_id},"timestamp":int(__import__('time').time()*1000)}) + '\n')
        except: pass
        # #endregion
        client = supabase_admin if supabase_admin else supabase
        # #region agent log
        try:
            # Check ALL plans for this user to see what week_start values exist
            all_plans_check = client.table("weekly_plans").select("id, week_start").eq("user_id", user_id).order("week_start", desc=True).limit(10).execute()
            # Also check group_plan_blocks for this week
            group_blocks_check = client.table("group_plan_blocks").select("id, group_id, week_start").eq("week_start", week_start).execute()
            # Get user's groups
            user_groups_check = client.table("group_members").select("group_id").eq("user_id", user_id).eq("status", "approved").execute()
            user_group_ids_check = [g["group_id"] for g in (user_groups_check.data or [])]
            user_group_blocks = [gb for gb in (group_blocks_check.data or []) if gb.get("group_id") in user_group_ids_check]
            with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"H","location":"app/main.py:2108","message":"ALL plans and group_plan_blocks for user","data":{"all_plans":all_plans_check.data if all_plans_check.data else [],"requested_week_start":week_start,"total_group_blocks_for_week":len(group_blocks_check.data) if group_blocks_check.data else 0,"user_group_blocks_count":len(user_group_blocks),"user_group_ids":user_group_ids_check},"timestamp":int(__import__('time').time()*1000)}) + '\n')
        except Exception as e:
            try:
                with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"H","location":"app/main.py:2108","message":"ERROR checking all plans and group blocks","data":{"error":str(e)},"timestamp":int(__import__('time').time()*1000)}) + '\n')
            except: pass
        # #endregion
        # Get all plan_ids for this user and week_start
        plans_for_week = client.table("weekly_plans").select("id, user_id, week_start").eq("user_id", user_id).eq("week_start", week_start).execute()
        plan_ids_for_week = [p["id"] for p in (plans_for_week.data or [])]
        
        # Get the first plan for response (or None if no plan)
        plan = plans_for_week.data[0] if plans_for_week.data else None
        
        # Fetch blocks for ALL plans of this week
        blocks = []
        if plan_ids_for_week:
            blocks_result = client.table("weekly_plan_blocks").select("*").in_("plan_id", plan_ids_for_week).order("day_of_week").order("start_time").execute()
            blocks = blocks_result.data or []
            logging.info(f"📋 [GET_WEEKLY_PLAN] Found {len(blocks)} blocks via plan_ids: {plan_ids_for_week}")
            # #region agent log
            try:
                with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"app/main.py:2150","message":"blocks fetched for week","data":{"blocks_count":len(blocks),"plan_ids_count":len(plan_ids_for_week),"week_start":week_start,"plan_ids":plan_ids_for_week},"timestamp":int(__import__('time').time()*1000)}) + '\n')
            except: pass
            # #endregion
        else:
            logging.warning(f"⚠️ [GET_WEEKLY_PLAN] No plan_ids found for user {user_id} and week {week_start}")
        
        # ALSO check for blocks directly by user_id (in case blocks exist but plan is missing or wrong)
        # This is a fallback to ensure we don't miss any blocks
        direct_blocks_result = client.table("weekly_plan_blocks").select("*").eq("user_id", user_id).order("day_of_week").order("start_time").execute()
        all_user_blocks = direct_blocks_result.data or []
        
        # Filter to only blocks that belong to plans with the correct week_start
        if all_user_blocks:
            all_plans_map = {}
            all_plans_result = client.table("weekly_plans").select("id, week_start").eq("user_id", user_id).execute()
            for p in (all_plans_result.data or []):
                all_plans_map[p["id"]] = p["week_start"]
            
            direct_blocks_for_week = []
            for b in all_user_blocks:
                block_plan_id = b.get("plan_id")
                if block_plan_id and all_plans_map.get(block_plan_id) == week_start:
                    # Check if this block is already in blocks (to avoid duplicates)
                    if not any(existing.get("id") == b.get("id") for existing in blocks):
                        direct_blocks_for_week.append(b)
                        logging.info(f"🔍 [GET_WEEKLY_PLAN] Found additional block via direct query: {b.get('course_name')} ({b.get('work_type')}), day={b.get('day_of_week')}, time={b.get('start_time')}, plan_id={block_plan_id}")
            
            if direct_blocks_for_week:
                blocks.extend(direct_blocks_for_week)
                logging.info(f"✅ [GET_WEEKLY_PLAN] Added {len(direct_blocks_for_week)} additional blocks found via direct query")
        
        # Remove duplicates (in case same block was found both ways)
        seen_ids = set()
        unique_blocks = []
        for b in blocks:
            block_id = b.get("id")
            if block_id and block_id not in seen_ids:
                seen_ids.add(block_id)
                unique_blocks.append(b)
        blocks = unique_blocks
        
        # If no blocks found via plan_ids, check directly by user_id (fallback)
        if not blocks:
            logging.warning(f"⚠️ No blocks found via plan_ids for user {user_id} and week {week_start}, checking directly")
            # Check if there are any blocks for this user and week (regardless of plan_id)
            all_user_blocks = client.table("weekly_plan_blocks").select("*").eq("user_id", user_id).execute()
            # Filter by week_start by checking if blocks belong to plans with this week_start
            all_plans = client.table("weekly_plans").select("id, week_start").eq("user_id", user_id).execute()
            plan_week_map = {p["id"]: p["week_start"] for p in (all_plans.data or [])}
            blocks_for_week = [b for b in (all_user_blocks.data or []) if plan_week_map.get(b.get("plan_id")) == week_start]
            if blocks_for_week:
                logging.warning(f"⚠️ Found {len(blocks_for_week)} blocks for week {week_start} but no plan - using these blocks anyway")
                blocks = blocks_for_week
                # Create a dummy plan for response
                if not plan:
                    plan = {"id": None, "user_id": user_id, "week_start": week_start, "source": "orphaned_blocks"}
        
        # For group blocks, add group_id by looking up group_plan_blocks (batch query for performance)
        group_blocks = [b for b in blocks if b.get("work_type") == "group"]
        # #region agent log
        try:
            with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"app/main.py:2103","message":"group blocks identified","data":{"group_blocks_count":len(group_blocks),"total_blocks":len(blocks)},"timestamp":int(__import__('time').time()*1000)}) + '\n')
        except: pass
        # #endregion
        if group_blocks:
            # Get all unique day/time combinations
            day_time_pairs = [(b["day_of_week"], b["start_time"]) for b in group_blocks]
            unique_pairs = list(set(day_time_pairs))
            
            # Batch fetch all group_plan_blocks for this week
            all_group_blocks = client.table("group_plan_blocks").select("group_id, course_number, day_of_week, start_time").eq("week_start", week_start).execute()
            # #region agent log
            try:
                with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"app/main.py:2110","message":"all_group_blocks fetched","data":{"all_group_blocks_count":len(all_group_blocks.data) if all_group_blocks.data else 0,"week_start":week_start},"timestamp":int(__import__('time').time()*1000)}) + '\n')
            except: pass
            # #endregion
            
            # Get all group IDs and batch fetch study_groups
            group_ids_to_check = list(set([gb.get("group_id") for gb in (all_group_blocks.data or [])]))
            groups_map = {}
            if group_ids_to_check:
                groups_result = client.table("study_groups").select("id, course_id").in_("id", group_ids_to_check).execute()
                groups_map = {g["id"]: g.get("course_id") for g in (groups_result.data or [])}
            
            # Match blocks to groups
            # First, get user's group IDs to filter only relevant group_plan_blocks
            user_groups = client.table("group_members").select("group_id").eq("user_id", user_id).eq("status", "approved").execute()
            user_group_ids = [g["group_id"] for g in (user_groups.data or [])]
            
            # Filter group_plan_blocks to only those belonging to user's groups
            relevant_group_blocks = [gb for gb in (all_group_blocks.data or []) if gb.get("group_id") in user_group_ids]
            
            matched_count = 0
            for block in group_blocks:
                matched = False
                block_course = str(block.get("course_number")).strip()
                block_day = block.get("day_of_week")
                block_start = block.get("start_time")
                
                # Normalize time format (remove seconds if present)
                def normalize_time(time_str):
                    if not time_str:
                        return None
                    # Remove seconds if present (HH:MM:SS -> HH:MM)
                    if isinstance(time_str, str) and len(time_str) > 5:
                        return time_str[:5]
                    return time_str
                
                block_start_normalized = normalize_time(block_start)
                
                # Try exact match first (with normalized time)
                for gb in relevant_group_blocks:
                    gb_start_normalized = normalize_time(gb.get("start_time"))
                    if (gb.get("day_of_week") == block_day and 
                        gb_start_normalized == block_start_normalized):
                        group_course = groups_map.get(gb.get("group_id"))
                        if group_course and str(group_course).strip() == block_course:
                            block["group_id"] = gb.get("group_id")
                            matched = True
                            matched_count += 1
                            break
                
                # If no exact match, try matching by course_number and day only (for same group)
                if not matched:
                    for gb in relevant_group_blocks:
                        group_course = groups_map.get(gb.get("group_id"))
                        if group_course and str(group_course).strip() == block_course and gb.get("day_of_week") == block_day:
                            # Check if this group_id already has blocks on this day - if so, this block belongs to it
                            block["group_id"] = gb.get("group_id")
                            matched = True
                            matched_count += 1
                            logging.info(f"✅ Matched group block by course and day: course={block_course}, day={block_day}, group_id={gb.get('group_id')}")
                            break
                
                # #region agent log
                if not matched:
                    try:
                        with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"app/main.py:2127","message":"group block NOT matched","data":{"block_course":block_course,"block_day":block_day,"block_time":block_start,"block_time_normalized":block_start_normalized,"relevant_group_blocks_count":len(relevant_group_blocks)},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                    except: pass
                    logging.warning(f"⚠️ Could not match group block: course={block_course}, day={block_day}, time={block_start} (normalized: {block_start_normalized})")
                # #endregion
        
        # Log detailed info about blocks before returning
        logging.info(f"📊 [GET_WEEKLY_PLAN] Returning {len(blocks)} blocks for user {user_id}, week {week_start}")
        if blocks:
            group_count = len([b for b in blocks if b.get("work_type") == "group"])
            personal_count = len([b for b in blocks if b.get("work_type") == "personal"])
            logging.info(f"   - Group blocks: {group_count}, Personal blocks: {personal_count}")
            # Log sample blocks
            sample_blocks = blocks[:5]
            for b in sample_blocks:
                logging.info(f"   - Sample block: {b.get('course_name')} ({b.get('work_type')}), day={b.get('day_of_week')}, time={b.get('start_time')}, plan_id={b.get('plan_id')}")
        else:
            logging.warning(f"⚠️ [GET_WEEKLY_PLAN] No blocks found for user {user_id}, week {week_start}")
            # Double-check: query directly from Supabase
            direct_check = client.table("weekly_plan_blocks").select("id, course_name, work_type, day_of_week, start_time, plan_id").eq("user_id", user_id).limit(20).execute()
            if direct_check.data:
                logging.warning(f"   But found {len(direct_check.data)} blocks for this user in total (not filtered by week)")
                # Check which plans these blocks belong to
                all_plan_ids = list(set([b.get("plan_id") for b in direct_check.data if b.get("plan_id")]))
                if all_plan_ids:
                    plans_check = client.table("weekly_plans").select("id, week_start").in_("id", all_plan_ids).execute()
                    logging.warning(f"   These blocks belong to plans: {[(p.get('id'), p.get('week_start')) for p in (plans_check.data or [])]}")
        
        # #region agent log
        try:
            with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"ALL","location":"app/main.py:2129","message":"returning result","data":{"blocks_count":len(blocks),"plan_id":plan.get("id") if plan else None,"group_blocks":len([b for b in blocks if b.get("work_type") == "group"]),"personal_blocks":len([b for b in blocks if b.get("work_type") == "personal"])},"timestamp":int(__import__('time').time()*1000)}) + '\n')
        except: pass
        # #endregion
        return {"plan": plan, "blocks": blocks}
    except Exception as e:
        logging.error(f"Error fetching weekly plan: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching weekly plan: {str(e)}")


@app.get("/api/weekly-plan/llm-status")
async def get_weekly_plan_llm_status(
    week_start: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Return LLM usage status for the current user and week.
    Useful to verify preferences were loaded and LLM blocks were applied.
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")

        profile_result = client.table("user_profiles").select("study_preferences_raw").eq("id", user_id).limit(1).execute()
        prefs_raw = ""
        if profile_result.data:
            prefs_raw = profile_result.data[0].get("study_preferences_raw") or ""

        plan_result = client.table("weekly_plans").select("id").eq("user_id", user_id).eq("week_start", week_start).limit(1).execute()
        if not plan_result.data:
            return {
                "week_start": week_start,
                "user_id": user_id,
                "preferences_length": len(prefs_raw),
                "llm_blocks": 0,
                "auto_fallback_blocks": 0,
                "group_blocks": 0,
                "total_blocks": 0,
                "message": "No weekly plan found for this week"
            }

        plan_id = plan_result.data[0]["id"]
        blocks_result = client.table("weekly_plan_blocks").select("source").eq("plan_id", plan_id).execute()
        sources = [b.get("source") for b in (blocks_result.data or [])]
        return {
            "week_start": week_start,
            "user_id": user_id,
            "preferences_length": len(prefs_raw),
            "llm_blocks": sources.count("llm"),
            "auto_fallback_blocks": sources.count("auto_fallback"),
            "group_blocks": sources.count("group"),
            "total_blocks": len(sources)
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error fetching LLM status: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/weekly-schedule")
async def get_weekly_schedule(
    date: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Get weekly schedule for terminal/CLI usage
    Uses schedule_retriever executor
    Returns schedule data for a specific week (defaults to current week)
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        # Use schedule_retriever executor
        from app.agents.executors.schedule_retriever import ScheduleRetriever
        retriever = ScheduleRetriever()
        result = await retriever.execute(user_id=user_id, date=date)
        
        return JSONResponse(content=result)
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error retrieving weekly schedule: {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": str(e),
                "week_start": None,
                "blocks": []
            }
        )


@app.post("/api/execute")
async def execute_agent(
    request_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """
    Main agent execution endpoint for terminal/CLI usage
    Routes user prompt to appropriate executor via supervisor
    """
    try:
        user_prompt = request_data.get("prompt", "")
        if not user_prompt:
            raise HTTPException(status_code=400, detail="Prompt is required")
        
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        # Initialize supervisor and route task
        supervisor = Supervisor()
        result = await supervisor.route_task(
            user_prompt=user_prompt,
            user_id=user_id
        )
        
        # Return pretty-printed JSON
        return Response(
            content=json.dumps(result, indent=2, ensure_ascii=False),
            media_type="application/json"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error executing agent: {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": str(e),
                "response": None,
                "steps": []
            }
        )


@app.get("/api/weekly-plan/llm-debug")
async def get_llm_debug_info(
    current_user: dict = Depends(get_current_user)
):
    """
    Return LLM debug info (prompt & response) for current user. TEMPORARY for debugging.
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        
        if user_id not in _llm_debug_cache:
            return {
                "found": False,
                "message": "No LLM debug info available for this user (no recent LLM call)"
            }
        
        debug_info = _llm_debug_cache[user_id]
        return {
            "found": True,
            **debug_info
        }
    except Exception as e:
        logging.error(f"Error fetching LLM debug info: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/weekly-plan/generate")
async def generate_weekly_plan(
    week_start: str,
    current_user: dict = Depends(get_current_user),
    notify: bool = True
):
    """
    Generate a weekly plan using hard/soft constraints and course credit points.
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        logging.info(f"📋 [GENERATE] Using {'admin' if supabase_admin else 'anon'} client for user {user_id}")

        courses_result = client.table("courses").select("*").eq("user_id", user_id).execute()
        all_courses = courses_result.data or []
        logging.info(f"📚 [GENERATE] User {user_id}: found {len(all_courses)} courses total")
        courses = list(all_courses)
        
        # Validate courses against CATALOG to ensure no "invented" courses are used
        catalog_res = client.table("course_catalog").select("course_number,course_name").execute()
        valid_catalog = {c["course_number"]: c["course_name"] for c in (catalog_res.data or [])}
        
        valid_courses = []
        for c in courses:
            c_num = str(c.get("course_number")).strip()
            if c_num in valid_catalog:
                # Use the official name from catalog
                c["course_name"] = valid_catalog[c_num]
                valid_courses.append(c)
            else:
                logging.error(f"❌ [GENERATE] User {user_id} has course {c_num} which is NOT in the catalog. STRICT REJECTION.")
        
        courses = valid_courses

        if not courses:
            return {"message": "No valid courses (from catalog) available for plan", "plan": None, "blocks": []}

        # Load preferences
        prefs_result = client.table("course_time_preferences").select("*").eq("user_id", user_id).execute()
        prefs_map = {p["course_number"]: p for p in (prefs_result.data or [])}

        # Load constraints
        constraints_result = client.table("constraints").select("*").eq("user_id", user_id).execute()
        permanent_constraints = constraints_result.data or []
        weekly_constraints_result = client.table("weekly_constraints").select("*").eq("user_id", user_id).eq("week_start", week_start).execute()
        weekly_constraints = weekly_constraints_result.data or []

        # Build blocked slots (hard constraints only)
        time_slots = _build_time_slots()
        blocked = set()
        soft_blocked = set()

        for constraint in permanent_constraints:
            for day in _parse_days(constraint.get("days")):
                for time in time_slots:
                    if _time_to_minutes(time) >= _time_to_minutes(constraint["start_time"]) and _time_to_minutes(time) < _time_to_minutes(constraint["end_time"]):
                        blocked.add((day, time))

        for constraint in weekly_constraints:
            for day in _parse_days(constraint.get("days")):
                for time in time_slots:
                    if _time_to_minutes(time) >= _time_to_minutes(constraint["start_time"]) and _time_to_minutes(time) < _time_to_minutes(constraint["end_time"]):
                        if constraint.get("is_hard", True):
                            blocked.add((day, time))
                        else:
                            soft_blocked.add((day, time))

        # Determine available slots FIRST (before group blocks)
        available_slots = [(day, time) for day in range(7) for time in time_slots if (day, time) not in blocked]
        
        # 1. First, identify all group blocks for this user and remove them from available_slots
        group_members_result = client.table("group_members").select("group_id").eq("user_id", user_id).eq("status", "approved").execute()
        user_group_ids = [gm["group_id"] for gm in (group_members_result.data or [])]
        
        # Build course_id -> group_id map for this user
        group_map = {}
        for gid in user_group_ids:
            g_res = client.table("study_groups").select("id,course_id").eq("id", gid).limit(1).execute()
            if g_res.data:
                group_map[g_res.data[0]["course_id"]] = gid

        # Remove ALL existing group slots from availability
        actual_group_blocks = []
        if user_group_ids:
            all_gb_res = client.table("group_plan_blocks").select("*").in_("group_id", user_group_ids).eq("week_start", week_start).execute()
            actual_group_blocks = all_gb_res.data or []
            # #region agent log
            try:
                import json
                with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"app/main.py:2385","message":"generate_weekly_plan: group_plan_blocks fetched","data":{"week_start":week_start,"user_group_ids_count":len(user_group_ids),"actual_group_blocks_count":len(actual_group_blocks)},"timestamp":int(__import__('time').time()*1000)}) + '\n')
            except: pass
            # #endregion
            for gb in actual_group_blocks:
                g_day, g_time = gb["day_of_week"], gb["start_time"]
                if (g_day, g_time) in available_slots:
                    available_slots.remove((g_day, g_time))

        # Compute total hours and weights AFTER group blocks are removed
        total_credits = sum([c.get("credit_points") or 3 for c in courses]) or 1
        total_slots = len(available_slots) 
        if total_slots == 0 and not actual_group_blocks:
            return {"message": "No available slots for plan", "plan": None, "blocks": []}

        # Create plan record - get ALL plans for this week (not just first one)
        existing_plans = client.table("weekly_plans").select("id").eq("user_id", user_id).eq("week_start", week_start).execute()
        # #region agent log
        try:
            import json
            with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"app/main.py:2405","message":"generate_weekly_plan: checking existing plans","data":{"user_id":user_id,"week_start":week_start,"existing_plans_count":len(existing_plans.data) if existing_plans.data else 0,"existing_plan_ids":[p["id"] for p in (existing_plans.data or [])]},"timestamp":int(__import__('time').time()*1000)}) + '\n')
        except: pass
        # #endregion
        if existing_plans.data:
            # Use the first existing plan and delete ALL blocks for ALL plans of this week
            plan_id = existing_plans.data[0]["id"]
            # Delete blocks for ALL plans of this week (not just the first one)
            for plan in existing_plans.data:
                client.table("weekly_plan_blocks").delete().eq("plan_id", plan["id"]).execute()
            # #region agent log
            try:
                with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"app/main.py:2413","message":"generate_weekly_plan: using existing plan","data":{"plan_id":plan_id,"week_start":week_start,"deleted_blocks_for_plans":len(existing_plans.data)},"timestamp":int(__import__('time').time()*1000)}) + '\n')
            except: pass
            # #endregion
        else:
            plan_id = client.table("weekly_plans").insert({"user_id": user_id, "week_start": week_start, "source": "auto"}).execute().data[0]["id"]
            # #region agent log
            try:
                with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"app/main.py:2422","message":"generate_weekly_plan: NEW plan created","data":{"plan_id":plan_id,"week_start":week_start},"timestamp":int(__import__('time').time()*1000)}) + '\n')
            except: pass
            # #endregion

        plan_blocks = []
        # #region agent log
        try:
            import json
            with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"app/main.py:2407","message":"generate_weekly_plan: starting to build plan_blocks","data":{"actual_group_blocks_count":len(actual_group_blocks),"week_start":week_start,"user_id":user_id},"timestamp":int(__import__('time').time()*1000)}) + '\n')
        except: pass
        # #endregion

        # 2. Add the pre-calculated group blocks to the plan
        for gb in actual_group_blocks:
            # Find the course name for this group block
            course_for_group = next((c for c in courses if c["course_number"] == gb["course_number"]), None)
            
            # CRITICAL FIX: If this group block belongs to a course NOT in the filtered 'courses' list, SKIP IT!
            if not course_for_group:
                logging.info(f"⏭️ Skipping group block for course {gb['course_number']} - not in user's courses")
                continue

            course_name = course_for_group["course_name"]
            
            # Use study_groups course_name only if no catalog name exists
            if not course_name:
                g_res = client.table("study_groups").select("course_name").eq("id", gb["group_id"]).limit(1).execute()
                if g_res.data and g_res.data[0].get("course_name"):
                    course_name = g_res.data[0]["course_name"]

            plan_blocks.append({
                "plan_id": plan_id,
                "user_id": user_id,
                "course_number": gb["course_number"],
                "course_name": course_name,
                "work_type": "group",
                "day_of_week": gb["day_of_week"],
                "start_time": gb["start_time"],
                "end_time": gb["end_time"],
                "source": "group",
                "group_id": gb.get("group_id")  # Include group_id for pending requests lookup
            })

        # 3. Load user preferences for LLM refinement
        profile_result = client.table("user_profiles").select("study_preferences_raw, study_preferences_summary").eq("id", user_id).limit(1).execute()
        user_preferences_raw = ""
        user_preferences_summary = {}
        if profile_result.data:
            user_preferences_raw = profile_result.data[0].get("study_preferences_raw") or ""
            user_preferences_summary = profile_result.data[0].get("study_preferences_summary") or {}
        
        logging.info(f"[LLM] User preferences loaded: {len(user_preferences_raw)} chars raw, {len(user_preferences_summary)} keys in summary")
        
        # 4. Try LLM-based personal block placement
        llm_result = await _refine_schedule_with_llm(
            skeleton_blocks=plan_blocks,  # Group blocks already placed
            available_slots=available_slots[:],  # Copy of available slots
            courses=courses,
            user_preferences_raw=user_preferences_raw,
            user_preferences_summary=user_preferences_summary,
            time_slots=time_slots,
            user_id=user_id
        )

        required_total = llm_result.get("required_total")
        if llm_result.get("success") and required_total and len(llm_result.get("blocks") or []) < required_total:
            logging.warning(
                f"[LLM] Returned {len(llm_result.get('blocks') or [])} of required {required_total} blocks. Retrying with strict prompt."
            )
            llm_result = await _refine_schedule_with_llm(
                skeleton_blocks=plan_blocks,
                available_slots=available_slots[:],
                courses=courses,
                user_preferences_raw=user_preferences_raw,
                user_preferences_summary=user_preferences_summary,
                time_slots=time_slots,
                force_exact_count=True,
                required_total_override=required_total,
                user_id=user_id
            )
        
        if llm_result["success"] and llm_result["blocks"]:
            logging.info("Using LLM-refined schedule")
            llm_blocks = llm_result["blocks"]
            applied_llm_blocks = 0
            # Use catalog names ONLY (courses already have catalog names from validation above)
            course_name_map = {str(c.get("course_number")).strip(): valid_catalog.get(str(c.get("course_number")).strip(), c.get("course_name")) for c in courses}
            
            # Validate and add LLM blocks
            for llm_block in llm_blocks:
                day_index = llm_block.get("day_index")
                start_time = llm_block.get("start_time")
                course_number = llm_block.get("course_number")
                course_name = course_name_map.get(str(course_number).strip()) or llm_block.get("course_name")
                
                # Validate slot is actually available
                if (day_index, start_time) in available_slots:
                    plan_blocks.append({
                        "plan_id": plan_id,
                        "user_id": user_id,
                        "course_number": course_number,
                        "course_name": course_name,
                        "work_type": "personal",
                        "day_of_week": day_index,
                        "start_time": start_time,
                        "end_time": _minutes_to_time(_time_to_minutes(start_time) + 60),
                        "source": "llm"
                    })
                    available_slots.remove((day_index, start_time))
                    applied_llm_blocks += 1
                else:
                    logging.warning(f"LLM proposed invalid slot ({day_index}, {start_time}), skipping")
            
            logging.info(f"Applied {applied_llm_blocks} LLM-refined personal blocks")

            # If LLM returned too few blocks, fill remaining deterministically
            logging.info("Checking for remaining personal hours after LLM placement")
            courses.sort(key=lambda x: x.get("credit_points") or 3, reverse=True)
            for course in courses:
                course_number = course.get("course_number")
                # ALWAYS use catalog name
                course_name = valid_catalog.get(str(course_number).strip(), course.get("course_name"))
                credits = course.get("credit_points") or 3
                total_quota = credits * 3
                group_hours = len([b for b in plan_blocks if b['course_number'] == course_number and b['work_type'] == 'group'])
                existing_personal = len([b for b in plan_blocks if b['course_number'] == course_number and b['work_type'] == 'personal'])
                remaining_personal = max(0, total_quota - group_hours - existing_personal)

                if remaining_personal == 0:
                    continue

                logging.info(f"Filling remaining {remaining_personal} personal blocks for {course_name}")
                allocated_personal = 0
                while allocated_personal < remaining_personal:
                    if not available_slots:
                        break
                    best_block = []
                    for i in range(len(available_slots)):
                        current_day, current_time = available_slots[i]
                        temp_block = [(current_day, current_time)]
                        for j in range(1, 3):
                            if i + j < len(available_slots):
                                next_day, next_time = available_slots[i + j]
                                if next_day == current_day:
                                    if _time_to_minutes(next_time) == _time_to_minutes(current_time) + (j * 60):
                                        temp_block.append((next_day, next_time))
                                    else:
                                        break
                                else:
                                    break
                            else:
                                break
                        if len(temp_block) > len(best_block):
                            best_block = temp_block
                            if len(best_block) == 3:
                                break
                    if not best_block:
                        best_block = [available_slots[0]]
                    for d, t in best_block:
                        if allocated_personal >= remaining_personal:
                            break
                        plan_blocks.append({
                            "plan_id": plan_id,
                            "user_id": user_id,
                            "course_number": course_number,
                            "course_name": course_name,
                            "work_type": "personal",
                            "day_of_week": d,
                            "start_time": t,
                            "end_time": _minutes_to_time(_time_to_minutes(t) + 60),
                            "source": "auto_fallback"
                        })
                        available_slots.remove((d, t))
                        allocated_personal += 1
                logging.info(f"Filled {allocated_personal} personal blocks for {course_name}")
        else:
            # FALLBACK: Use deterministic placement if LLM fails
            logging.warning("LLM refinement failed, falling back to deterministic placement")
            logging.warning(f"   Reason: {llm_result.get('message', 'Unknown')}")
            
            # Sort courses by credits to prioritize
            courses.sort(key=lambda x: x.get("credit_points") or 3, reverse=True)

            for course in courses:
                course_number = course.get("course_number")
                # ALWAYS use catalog name
                course_name = valid_catalog.get(str(course_number).strip(), course.get("course_name"))
                credits = course.get("credit_points") or 3
                
                # Calculation: credits * 3 total hours. 
                # Group is already allocated. Calculate remaining personal.
                total_quota = credits * 3
                group_hours = len([b for b in plan_blocks if b['course_number'] == course_number and b['work_type'] == 'group'])
                personal_quota = max(0, total_quota - group_hours)

                if personal_quota == 0: continue

                # Try to find blocks of 2-3 hours for personal work
                allocated_personal = 0
                while allocated_personal < personal_quota:
                    if not available_slots: break
                    
                    # Try to find a 2-3h block
                    best_block = []
                    # Simple greedy: look for consecutive slots in available_slots
                    for i in range(len(available_slots)):
                        current_day, current_time = available_slots[i]
                        temp_block = [(current_day, current_time)]
                        
                        # Look ahead for up to 2 more hours
                        for j in range(1, 3):
                            if i + j < len(available_slots):
                                next_day, next_time = available_slots[i+j]
                                if next_day == current_day:
                                    # Check if they are actually consecutive (1 hour diff)
                                    if _time_to_minutes(next_time) == _time_to_minutes(current_time) + (j * 60):
                                        temp_block.append((next_day, next_time))
                                    else:
                                        break
                                else:
                                    break
                            else:
                                break
                        
                        if len(temp_block) > len(best_block):
                            best_block = temp_block
                            if len(best_block) == 3: break # Found a good 3h block

                    if not best_block:
                        # If no blocks found, just take the first single slot
                        best_block = [available_slots[0]]

                    # Allocate this block
                    for d, t in best_block:
                        if allocated_personal >= personal_quota: break
                        plan_blocks.append({
                            "plan_id": plan_id,
                            "user_id": user_id,
                            "course_number": course_number,
                            "course_name": course_name,
                            "work_type": "personal",
                            "day_of_week": d,
                            "start_time": t,
                            "end_time": _minutes_to_time(_time_to_minutes(t) + 60),
                            "source": "auto_fallback"
                        })
                        available_slots.remove((d, t))
                        allocated_personal += 1

                logging.info(f"   OK Allocated {allocated_personal} personal blocks for {course_name}")
            
        # Log final allocation
        for course in courses:
            course_number = course.get("course_number")
            course_name = course.get("course_name")
            total_blocks = len([b for b in plan_blocks if b['course_number'] == course_number])
            logging.info(f"   OK Total blocks for {course_name}: {total_blocks}")
        
        logging.info(f"Remaining available slots: {len(available_slots)}")

        logging.info(f"Total plan blocks to insert: {len(plan_blocks)}")
        # #region agent log
        try:
            import json
            with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"app/main.py:2656","message":"generate_weekly_plan: BEFORE insert blocks","data":{"plan_blocks_count":len(plan_blocks),"plan_id":plan_id,"week_start":week_start,"has_blocks":len(plan_blocks) > 0},"timestamp":int(__import__('time').time()*1000)}) + '\n')
        except: pass
        # #endregion
        if plan_blocks:
            # Verify all blocks have the correct plan_id and required fields
            required_fields = ["plan_id", "user_id", "course_number", "course_name", "work_type", "day_of_week", "start_time", "end_time"]
            for i, block in enumerate(plan_blocks):
                if block.get("plan_id") != plan_id:
                    logging.error(f"❌ BLOCK {i} HAS WRONG plan_id! Expected {plan_id}, got {block.get('plan_id')}")
                    block["plan_id"] = plan_id  # Fix it
                
                # Check for missing required fields
                missing_fields = [field for field in required_fields if field not in block or block[field] is None]
                if missing_fields:
                    logging.error(f"❌ BLOCK {i} MISSING REQUIRED FIELDS: {missing_fields}")
                    logging.error(f"   Block data: {block}")
            
            # Check for duplicates before inserting
            slot_check = {}
            for block in plan_blocks:
                key = (block['day_of_week'], block['start_time'])
                if key in slot_check:
                    logging.error(f"❌ DUPLICATE SLOT DETECTED! {key} used by both '{slot_check[key]}' and '{block['course_name']}'")
                else:
                    slot_check[key] = block['course_name']
            
            # Remove group_id from blocks before insert (it's not a column in weekly_plan_blocks)
            blocks_to_insert = []
            for block in plan_blocks:
                insert_block = {k: v for k, v in block.items() if k != "group_id"}
                blocks_to_insert.append(insert_block)
            
            # Attempt insert with proper error handling
            inserted_count = 0
            try:
                logging.info(f"🔄 Attempting to insert {len(blocks_to_insert)} blocks (plan_id: {plan_id})")
                insert_result = client.table("weekly_plan_blocks").insert(blocks_to_insert).execute()
                
                if not insert_result.data:
                    error_msg = f"❌ INSERT FAILED! Supabase returned no data. plan_id: {plan_id}, blocks_count: {len(blocks_to_insert)}"
                    logging.error(error_msg)
                    # Log first block as sample
                    if blocks_to_insert:
                        logging.error(f"   Sample block: {blocks_to_insert[0]}")
                    raise Exception(error_msg)
                
                inserted_count = len(insert_result.data)
                if inserted_count != len(blocks_to_insert):
                    logging.warning(f"⚠️ PARTIAL INSERT! Expected {len(blocks_to_insert)} blocks, got {inserted_count}")
                else:
                    logging.info(f"✅ Successfully inserted {inserted_count} blocks (plan_id: {plan_id})")
                
                # Verify inserted blocks have correct plan_id
                sample_plan_ids = [b.get("plan_id") for b in insert_result.data[:3]]
                if sample_plan_ids and not all(pid == plan_id for pid in sample_plan_ids):
                    logging.error(f"❌ INSERTED BLOCKS HAVE WRONG plan_id! Expected {plan_id}, got {sample_plan_ids}")
                
                # #region agent log
                try:
                    with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"app/main.py:2748","message":"generate_weekly_plan: INSERT SUCCESS","data":{"blocks_inserted":inserted_count,"plan_id":plan_id,"expected_count":len(blocks_to_insert)},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                except: pass
                # #endregion
                
            except Exception as insert_err:
                error_msg = f"❌ INSERT EXCEPTION! Error: {str(insert_err)}"
                logging.error(error_msg, exc_info=True)
                # Log sample block for debugging
                if blocks_to_insert:
                    logging.error(f"   Sample block structure: {blocks_to_insert[0]}")
                # #region agent log
                try:
                    with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"app/main.py:2755","message":"generate_weekly_plan: INSERT FAILED","data":{"error":str(insert_err),"plan_id":plan_id,"blocks_count":len(blocks_to_insert)},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                except: pass
                # #endregion
                raise
        else:
            # #region agent log
            try:
                import json
                with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"app/main.py:2668","message":"generate_weekly_plan: NO BLOCKS TO INSERT","data":{"plan_id":plan_id,"week_start":week_start,"plan_blocks_empty":True},"timestamp":int(__import__('time').time()*1000)}) + '\n')
            except: pass
            # #endregion

        # Fetch blocks from DB after insert to return complete data (including group_id for group blocks)
        blocks_result = client.table("weekly_plan_blocks").select("*").eq("plan_id", plan_id).order("day_of_week").order("start_time").execute()
        final_blocks = blocks_result.data or []
        
        # Verify blocks were actually saved
        if plan_blocks and len(final_blocks) == 0:
            logging.error(f"❌ CRITICAL: Blocks were inserted but not found in DB! plan_id: {plan_id}, expected_count: {len(plan_blocks)}")
            # Try to fetch all blocks for this user and week to see if they're there
            all_user_blocks = client.table("weekly_plan_blocks").select("*").eq("user_id", user_id).eq("plan_id", plan_id).execute()
            logging.error(f"   Found {len(all_user_blocks.data or [])} blocks for user {user_id} with plan_id {plan_id}")
        elif plan_blocks and len(final_blocks) != len(plan_blocks):
            logging.warning(f"⚠️ Block count mismatch: inserted {len(plan_blocks)}, found in DB {len(final_blocks)}")
        elif plan_blocks:
            logging.info(f"✅ Verified: {len(final_blocks)} blocks found in DB for plan_id {plan_id}")
        
        # Add group_id to group blocks
        group_blocks = [b for b in final_blocks if b.get("work_type") == "group"]
        if group_blocks:
            all_group_blocks = client.table("group_plan_blocks").select("group_id, course_number, day_of_week, start_time").eq("week_start", week_start).execute()
            user_groups_check = client.table("group_members").select("group_id").eq("user_id", user_id).eq("status", "approved").execute()
            user_group_ids_check = [g["group_id"] for g in (user_groups_check.data or [])]
            if user_group_ids_check:
                groups_result = client.table("study_groups").select("id, course_id").in_("id", user_group_ids_check).execute()
                groups_map = {g["id"]: g.get("course_id") for g in (groups_result.data or [])}
                for block in group_blocks:
                    for gb in (all_group_blocks.data or []):
                        if (gb.get("day_of_week") == block["day_of_week"] and 
                            gb.get("start_time") == block["start_time"]):
                            group_course = groups_map.get(gb.get("group_id"))
                            if group_course and str(group_course).strip() == str(block.get("course_number")).strip():
                                block["group_id"] = gb.get("group_id")
                                break

        if notify:
            try:
                # Delete any existing notification for this week to avoid duplicates
                client.table("notifications").delete().eq("user_id", user_id).eq("type", "plan_ready").like("link", f"%week={week_start}%").execute()
                
                notif_data = {
                    "user_id": user_id,
                    "type": "plan_ready",
                    "title": "המערכת השבועית שלך מוכנה! 📅",
                    "message": f"הסוכן סיים לתכנן את המערכת שלך לשבוע ({week_start}). מוזמן להסתכל ולעדכן!",
                    "link": f"/schedule?week={week_start}",
                    "read": False
                }
                logging.info(f"🔔 Sending plan_ready notification to user {user_id} for week {week_start}")
                result = client.table("notifications").insert(notif_data).execute()
                if result.data:
                    logging.info(f"✅ Notification created successfully: {result.data[0].get('id')}")
                else:
                    logging.warning(f"⚠️ Notification insert returned no data")
            except Exception as notif_err:
                logging.error(f"⚠️ Failed to notify user {user_id} about plan ready: {notif_err}", exc_info=True)

        return {"message": "Weekly plan generated", "plan_id": plan_id, "blocks": final_blocks}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error generating weekly plan: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating weekly plan: {str(e)}")


@app.post("/api/weekly-plan/auto")
async def auto_weekly_plan(
    week_start: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Auto weekly process:
    1) Create group work time and post to groups
    2) Generate the rest of the personal calendar
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")

        # Build an initial availability grid (used only for group time)
        time_slots = _build_time_slots()
        available_slots = [(day, time) for day in range(7) for time in time_slots]
        _ensure_group_blocks_for_week(client, user_id, week_start, available_slots)

        # Generate the rest of the weekly plan (personal + remaining group slots)
        return await generate_weekly_plan(week_start, current_user)
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error running auto weekly plan: {e}")
        raise HTTPException(status_code=500, detail=f"Error running auto weekly plan: {str(e)}")


@app.post("/api/weekly-plan/trigger-now")
async def trigger_weekly_plan_now(
    minutes: int = 2
):
    """
    Schedule the weekly auto plan to run after a short delay (default 2 minutes).
    Useful for testing.
    """
    try:
        run_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        logging.info(f"[SCHEDULER] Manual trigger requested: run in {minutes} minutes at {run_at.isoformat()}")
        scheduler.add_job(
            _run_weekly_auto_for_all_users_sync,
            DateTrigger(run_date=run_at),
            id=f"weekly_auto_plan_manual_{run_at.timestamp()}",
            replace_existing=False,
        )
        logging.info(f"[SCHEDULER] Job scheduled (id=weekly_auto_plan_manual_{run_at.timestamp()})")
        return {"message": f"Weekly auto plan scheduled for {run_at.isoformat()} UTC"}
    except Exception as e:
        logging.error(f"Error scheduling manual weekly plan: {e}")
        raise HTTPException(status_code=500, detail=f"Error scheduling manual weekly plan: {str(e)}")


@app.post("/api/weekly-plan/run-immediately")
async def run_weekly_plan_immediately(week_start: Optional[str] = None):
    """
    Run the weekly auto plan immediately (not scheduled).
    Bypasses APScheduler to avoid misfire issues.
    """
    try:
        await _run_weekly_auto_for_all_users(week_start_override=week_start)
        if week_start:
            return {"message": f"Weekly auto plan executed immediately for all users (week_start={week_start})"}
        return {"message": "Weekly auto plan executed immediately for all users"}
    except Exception as e:
        logging.error(f"Error running weekly plan immediately: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/llm/health")
async def llm_health_check():
    """
    Quick LLM connectivity check (OpenAI-compatible providers).
    """
    try:
        if not HAS_OPENAI:
            return JSONResponse(status_code=503, content={"ok": False, "error": "openai_not_installed"})

        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            return JSONResponse(status_code=503, content={"ok": False, "error": "missing_api_key"})

        base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        model = os.getenv("LLM_MODEL") or "gpt-4o-mini"

        client = OpenAI(api_key=openai_api_key, base_url=base_url) if base_url else OpenAI(api_key=openai_api_key)

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5
        )

        return {
            "ok": True,
            "model": model,
            "base_url": base_url,
            "response": response.choices[0].message.content
        }
    except Exception as e:
        logging.error(f"LLM health check failed: {e}")
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.put("/api/weekly-plan-blocks/{block_id}")
async def update_weekly_plan_block(
    block_id: str,
    update_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """
    Update a weekly plan block (used when user edits the plan).
    Also updates course time preferences based on current plan distribution.
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        client = supabase_admin if supabase_admin else supabase

        existing = client.table("weekly_plan_blocks").select("*").eq("id", block_id).eq("user_id", user_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Plan block not found")

        block = existing.data[0]
        allowed_fields = {"day_of_week", "start_time", "end_time", "work_type", "is_locked"}
        update_payload = {k: v for k, v in update_data.items() if k in allowed_fields}
        if not update_payload:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        update_result = client.table("weekly_plan_blocks").update(update_payload).eq("id", block_id).execute()
        if not update_result.data:
            raise HTTPException(status_code=400, detail="Failed to update plan block")

        # Update course time preferences based on all blocks in this plan
        plan_id = block["plan_id"]
        course_number = block["course_number"]
        blocks_result = client.table("weekly_plan_blocks").select("work_type").eq("plan_id", plan_id).eq("course_number", course_number).execute()
        blocks = blocks_result.data or []
        if blocks:
            new_personal_hours = sum(1 for b in blocks if b.get("work_type") == "personal")
            new_group_hours = sum(1 for b in blocks if b.get("work_type") == "group")
            
            if new_personal_hours > 0 or new_group_hours > 0:
                # Get current preferences for weighted average (80% existing, 20% new)
                current_pref_result = client.table("course_time_preferences").select("personal_hours_per_week, group_hours_per_week").eq("user_id", user_id).eq("course_number", course_number).limit(1).execute()
                if current_pref_result.data and current_pref_result.data[0].get("personal_hours_per_week") is not None:
                    # Convert to float to handle decimal values
                    current_personal_hours = float(current_pref_result.data[0]["personal_hours_per_week"])
                    current_group_hours = float(current_pref_result.data[0].get("group_hours_per_week", 0))
                    
                    # Weighted average: 80% existing, 20% new (keep as decimal)
                    personal_hours = round(0.8 * current_personal_hours + 0.2 * float(new_personal_hours), 2)
                    group_hours = round(0.8 * current_group_hours + 0.2 * float(new_group_hours), 2)
                else:
                    # No existing preferences, use new values (as decimal)
                    personal_hours = float(new_personal_hours)
                    group_hours = float(new_group_hours)

                client.table("course_time_preferences").upsert({
                    "user_id": user_id,
                    "course_number": course_number,
                    "personal_hours_per_week": personal_hours,
                    "group_hours_per_week": group_hours
                }, on_conflict="user_id,course_number").execute()

        return {"message": "Plan block updated", "block": update_result.data[0]}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error updating plan block: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating plan block: {str(e)}")


# Chat endpoint
@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    chat_message: ChatMessage,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))
):
    """
    Chat endpoint - responds to user messages
    This is a basic implementation that can be extended with AI integration
    Authentication is optional for chat
    """
    try:
        # Optional: get user info if authenticated
        user_id = None
        if credentials:
            try:
                token = credentials.credentials
                response = supabase.auth.get_user(token)
                if response.user:
                    user_id = response.user.id
            except:
                pass  # Continue without authentication
        
        user_message = chat_message.message.lower()
        
        # Simple response logic (can be replaced with AI/LLM integration)
        response_text = ""
        
        if any(word in user_message for word in ["שלום", "היי", "הי", "בוקר", "ערב"]):
            response_text = "שלום! איך אני יכול לעזור לך היום?"
        elif any(word in user_message for word in ["קורס", "קורסים", "מערכת"]):
            response_text = "אני יכול לעזור לך עם תכנון מערכת הקורסים. תוכל להעלות גליון ציונים בעמוד 'בניית מערכת' או לשאול אותי שאלות על קורסים ספציפיים."
        elif any(word in user_message for word in ["אילוץ", "אילוצים", "זמן"]):
            response_text = "אתה יכול להוסיף אילוצים קבועים כמו שעות עבודה או אימונים. פשוט לחץ על 'הוסף אילוץ' בחלק האילוצים."
        elif any(word in user_message for word in ["ציון", "ציונים", "ממוצע"]):
            response_text = "אני יכול לעזור לך לבדוק את הציונים והממוצע שלך. תוכל לראות את המידע הזה בטאב 'ציונים'."
        elif any(word in user_message for word in ["דדליין", "מטלה", "הגשה", "בחינה"]):
            response_text = "תוכל לראות את כל המטלות והבחינות הקרובות בטאב 'הגשות'. אני יכול לעזור לך לתכנן את הזמן שלך."
        elif any(word in user_message for word in ["תודה", "תודה רבה"]):
            response_text = "בשמחה! אם יש עוד משהו שאני יכול לעזור, רק תשאל."
        else:
            response_text = "אני כאן כדי לעזור לך עם תכנון הלימודים שלך. תוכל לשאול אותי על קורסים, אילוצים, ציונים, מטלות ועוד. איך אני יכול לעזור?"
        
        return ChatResponse(
            response=response_text,
            conversation_id=chat_message.conversation_id
        )
    except Exception as e:
        logging.error(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing chat message: {str(e)}")


# Manual Schedule Editing & Group Change Request endpoints
@app.post("/api/schedule/block/create")
async def create_schedule_block(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new study block directly (without LLM).
    For group blocks, requires exact group_name match.
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        data = await request.json()
        course_name = data.get("course_name")
        course_number = data.get("course_number")
        day_of_week = data.get("day_of_week")
        start_time = data.get("start_time")
        duration = data.get("duration", 1)
        work_type = data.get("work_type", "personal")
        week_start = data.get("week_start")
        group_name = data.get("group_name")
        
        if not course_name and not course_number:
            raise HTTPException(status_code=400, detail="course_name or course_number is required")
        if day_of_week is None:
            raise HTTPException(status_code=400, detail="day_of_week is required")
        if not start_time:
            raise HTTPException(status_code=400, detail="start_time is required")
        
        # For group blocks, group_name is required
        if work_type == "group" and not group_name:
            raise HTTPException(status_code=400, detail="group_name is required for group blocks")
        
        # Import and use BlockCreator executor directly
        from app.agents.executors.block_creator import BlockCreator
        block_creator = BlockCreator()
        
        result = await block_creator.execute(
            user_id=user_id,
            course_number=course_number,
            course_name=course_name,
            day_of_week=day_of_week,
            start_time=start_time,
            duration=duration,
            work_type=work_type,
            week_start=week_start,
            group_name=group_name
        )
        
        return JSONResponse(content=result)
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error creating block: {e}")
        import traceback
        logging.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error creating block: {str(e)}")


@app.post("/api/schedule/block/move")
async def move_schedule_block(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    Move a schedule block to a new day/time.
    - Personal blocks: Move immediately
    - Group blocks: Create change request (requires approval)
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        body = await request.json()
        block_id = body.get("block_id")
        new_day = body.get("new_day_of_week")
        new_start_time = body.get("new_start_time")
        explanation = body.get("explanation", "")  # Optional: why user moved the block
        original_start_time = body.get("original_start_time")  # Optional: for sub-range selection
        duration_hours = body.get("duration_hours")  # Optional: for sub-range selection
        
        if not all([block_id, new_day is not None, new_start_time]):
            raise HTTPException(status_code=400, detail="block_id, new_day_of_week, and new_start_time are required")
        
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Get the block
        block_result = client.table("weekly_plan_blocks").select("*").eq("id", block_id).limit(1).execute()
        if not block_result.data:
            raise HTTPException(status_code=404, detail="Block not found")
        
        block = block_result.data[0]
        
        # Check if user owns this block
        if block["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Not authorized to move this block")
        
        # Check if it's a group block
        if block.get("work_type") == "group":
            # Cannot move group blocks directly - need to create change request
            return JSONResponse(
                status_code=400,
                content={
                    "error": "group_block",
                    "message": "Group blocks require approval from all members. Please use the group change request system.",
                    "block": block
                }
            )
        
        # It's a personal block - move it immediately
        # First, check for conflicts with hard constraints (both weekly and permanent)
        
        # Get week_start from the block's plan
        plan_result = client.table("weekly_plans").select("week_start").eq("id", block["plan_id"]).limit(1).execute()
        week_start = plan_result.data[0]["week_start"] if plan_result.data else None
        
        conflict_reasons = []
        
        # Define time slots for calculations
        time_slots = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00"]
        
        # First, find all consecutive blocks that will be moved to check conflicts for all of them
        original_day = block.get("day_of_week")
        original_start = block.get("start_time")
        course_number = block.get("course_number")
        work_type = block.get("work_type")
        
        # If sub-range is specified, use it; otherwise move all consecutive blocks
        if original_start_time and duration_hours:
            # User selected a sub-range - move only that range
            sub_range_start = original_start_time
            num_hours_to_move = duration_hours
            
            # Get all blocks for this plan/course/day to find the sub-range
            all_blocks_for_conflict = client.table("weekly_plan_blocks").select("id, start_time, end_time").eq("plan_id", block["plan_id"]).eq("course_number", course_number).eq("work_type", work_type).eq("day_of_week", original_day).order("start_time").execute()
            
            # Find blocks in the sub-range
            consecutive_blocks = []
            sub_range_start_idx = time_slots.index(sub_range_start) if sub_range_start in time_slots else -1
            
            if sub_range_start_idx != -1:
                for i in range(num_hours_to_move):
                    if sub_range_start_idx + i < len(time_slots):
                        target_time = time_slots[sub_range_start_idx + i]
                        for b in (all_blocks_for_conflict.data or []):
                            if b.get("start_time") == target_time and b["id"] not in [cb["id"] for cb in consecutive_blocks]:
                                consecutive_blocks.append(b)
                                break
            
            blocks_to_move_ids = [b["id"] for b in consecutive_blocks] if consecutive_blocks else [block_id]
        else:
            # No sub-range specified - move all consecutive blocks (original behavior)
            # Get all blocks for this plan/course/day to find consecutive ones
            all_blocks_for_conflict = client.table("weekly_plan_blocks").select("id, start_time, end_time").eq("plan_id", block["plan_id"]).eq("course_number", course_number).eq("work_type", work_type).eq("day_of_week", original_day).order("start_time").execute()
            
            # Find consecutive blocks
            consecutive_blocks = []
            starting_block_for_conflict = None
            for b in (all_blocks_for_conflict.data or []):
                if b.get("start_time") == original_start:
                    starting_block_for_conflict = b
                    consecutive_blocks.append(b)
                    break
            
            if starting_block_for_conflict:
                current_end_time = starting_block_for_conflict.get("end_time")
                for b in (all_blocks_for_conflict.data or []):
                    if b["id"] == starting_block_for_conflict["id"]:
                        continue
                    block_start = b.get("start_time")
                    if block_start == current_end_time:
                        consecutive_blocks.append(b)
                        current_end_time = b.get("end_time")
                    elif _time_to_minutes(block_start) > _time_to_minutes(current_end_time):
                        break
            
            # Calculate how many hours will be moved
            num_hours_to_move = len(consecutive_blocks) if consecutive_blocks else 1
            blocks_to_move_ids = [b["id"] for b in consecutive_blocks] if consecutive_blocks else [block_id]
        
        # Calculate time slots for the new location (for conflict checking)
        # time_slots already defined above
        if new_start_time in time_slots:
            new_start_idx = time_slots.index(new_start_time)
        else:
            new_start_minutes = _time_to_minutes(new_start_time)
            closest_idx = 0
            min_diff = abs(_time_to_minutes(time_slots[0]) - new_start_minutes)
            for i, slot in enumerate(time_slots):
                diff = abs(_time_to_minutes(slot) - new_start_minutes)
                if diff < min_diff:
                    min_diff = diff
                    closest_idx = i
            new_start_idx = closest_idx
        
        # Check 1: Weekly hard constraints (for all hours that will be moved)
        if week_start:
            weekly_constraints = client.table("weekly_constraints").select("*").eq("user_id", user_id).eq("week_start", week_start).execute()
            for constraint in (weekly_constraints.data or []):
                if not constraint.get("is_hard", True):
                    continue  # Skip soft constraints
                
                days_array = constraint.get("days", [])
                if isinstance(days_array, str):
                    try:
                        import json
                        days_array = json.loads(days_array)
                    except:
                        days_array = []
                
                if new_day in days_array:
                    c_start = _time_to_minutes(constraint.get("start_time", "00:00"))
                    c_end = _time_to_minutes(constraint.get("end_time", "00:00"))
                    
                    # Check each hour that will be moved
                    for i in range(num_hours_to_move):
                        if new_start_idx + i < len(time_slots):
                            new_time = time_slots[new_start_idx + i]
                            new_end = time_slots[new_start_idx + i + 1] if (new_start_idx + i + 1) < len(time_slots) else "21:00"
                            p_start = _time_to_minutes(new_time)
                            p_end = _time_to_minutes(new_end)
                            
                            if p_start < c_end and p_end > c_start:
                                conflict_reasons.append(f"אילוץ קשיח שבועי: {constraint.get('title', 'אילוץ')} ({constraint.get('start_time')}-{constraint.get('end_time')})")
                                break  # Only report once per constraint
        
        # Check 2: Permanent hard constraints (for all hours that will be moved)
        permanent_constraints = client.table("constraints").select("*").eq("user_id", user_id).execute()
        import json
        for constraint in (permanent_constraints.data or []):
            if not constraint.get("is_hard", True):
                continue  # Skip soft constraints
            
            days_array = constraint.get("days", [])
            if isinstance(days_array, str):
                try:
                    days_array = json.loads(days_array)
                except:
                    days_array = []
            elif not isinstance(days_array, list):
                days_array = []
            
            if new_day in days_array:
                c_start = _time_to_minutes(constraint.get("start_time", "00:00"))
                c_end = _time_to_minutes(constraint.get("end_time", "00:00"))
                
                # Check each hour that will be moved
                for i in range(num_hours_to_move):
                    if new_start_idx + i < len(time_slots):
                        new_time = time_slots[new_start_idx + i]
                        new_end = time_slots[new_start_idx + i + 1] if (new_start_idx + i + 1) < len(time_slots) else "21:00"
                        p_start = _time_to_minutes(new_time)
                        p_end = _time_to_minutes(new_end)
                        
                        if p_start < c_end and p_end > c_start:
                            conflict_reasons.append(f"אילוץ קשיח קבוע: {constraint.get('title', 'אילוץ')} ({constraint.get('start_time')}-{constraint.get('end_time')})")
                            break  # Only report once per constraint
        
        # Check 3: Existing blocks (other courses at the same time)
        # Check conflicts for all hours that will be moved
        if week_start:
            user_plan = client.table("weekly_plans").select("id").eq("user_id", user_id).eq("week_start", week_start).limit(1).execute()
            if user_plan.data:
                user_plan_id = user_plan.data[0]["id"]
                existing_blocks = client.table("weekly_plan_blocks").select("course_name, start_time, end_time").eq("plan_id", user_plan_id).eq("day_of_week", new_day).execute()
                
                # Check conflicts for each hour that will be moved (time_slots and new_start_idx already calculated above)
                for i in range(num_hours_to_move):
                    if new_start_idx + i < len(time_slots):
                        new_time = time_slots[new_start_idx + i]
                        new_end = time_slots[new_start_idx + i + 1] if (new_start_idx + i + 1) < len(time_slots) else "21:00"
                        
                        # Check if this time slot conflicts with existing blocks
                        for existing_block in (existing_blocks.data or []):
                            # Skip if it's one of the blocks we're moving (check by ID if possible, or by time)
                            existing_block_id = existing_block.get("id")
                            if existing_block_id and existing_block_id in blocks_to_move_ids:
                                continue
                            # Also skip if it's at the original location and same course (we're moving it)
                            if existing_block.get("start_time") == original_start and existing_block.get("course_number") == course_number:
                                continue
                            
                            e_start = _time_to_minutes(existing_block.get("start_time", "00:00"))
                            e_end = _time_to_minutes(existing_block.get("end_time", "00:00"))
                            p_start = _time_to_minutes(new_time)
                            p_end = _time_to_minutes(new_end)
                            
                            if p_start < e_end and p_end > e_start:
                                conflict_reasons.append(f"בלוק קיים: {existing_block.get('course_name', 'קורס')} ({existing_block.get('start_time')}-{existing_block.get('end_time')})")
                                break  # Only report once per conflicting block
        
        # If there are conflicts, reject the move
        if conflict_reasons:
            conflict_message = "לא ניתן להזיז את הבלוק - יש התנגשויות:\n" + "\n".join(conflict_reasons)
            raise HTTPException(
                status_code=400,
                detail=conflict_message
            )
        
        # Use the consecutive blocks we already found for conflict checking
        logging.info(f"📦 Moving {len(blocks_to_move_ids)} consecutive blocks starting at {original_start}")
        
        # Use the time_slots and new_start_idx already calculated above for conflict checking
        # Normalize new_start_time to the closest slot if needed
        if new_start_time not in time_slots:
            new_start_time = time_slots[new_start_idx]  # Use the closest slot
        
        # Update all consecutive blocks
        for i, block_id_to_move in enumerate(blocks_to_move_ids):
            if new_start_idx + i < len(time_slots):
                new_time = time_slots[new_start_idx + i]
                new_end = time_slots[new_start_idx + i + 1] if (new_start_idx + i + 1) < len(time_slots) else "21:00"
                
                update_result = client.table("weekly_plan_blocks").update({
                    "day_of_week": new_day,
                    "start_time": new_time,
                    "end_time": new_end,
                    "source": "manual"  # Mark as manually edited
                }).eq("id", block_id_to_move).execute()
                
                if not update_result.data:
                    logging.warning(f"⚠️ Failed to update block {block_id_to_move}")
        
        logging.info(f"✅ User {user_id} moved {len(blocks_to_move_ids)} consecutive personal blocks from day {original_day} {original_start} to day {new_day} {new_start_time}")
        
        # If explanation provided, save it to user preferences for learning
        preferences_updated = False
        if explanation.strip():
            try:
                day_names = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
                profile = client.table("user_profiles").select("study_preferences_raw, schedule_change_notes").eq("id", user_id).limit(1).execute()
                current_prefs = profile.data[0].get("study_preferences_raw", "") if profile.data else ""
                current_notes = profile.data[0].get("schedule_change_notes", []) if profile.data else []
                
                if not isinstance(current_notes, list):
                    current_notes = []
                
                # Add new note (for LLM analysis, but we'll route based on LLM decision)
                new_note = {
                    "date": datetime.now().isoformat(),
                    "course": block.get("course_number", "?"),
                    "change": f"moved from day {block.get('day_of_week')} {block.get('start_time')} to day {new_day} {new_start_time}",
                    "explanation": explanation
                }
                current_notes.append(new_note)
                
                # Save notes first (for LLM to analyze)
                client.table("user_profiles").update({
                    "schedule_change_notes": current_notes
                }).eq("id", user_id).execute()
                
                # ALWAYS call LLM to summarize preferences - this is what we use for scheduling
                # The summary is saved to study_preferences_summary and used when generating schedules
                try:
                    logging.info(f"🔄 [MOVE BLOCK] Calling LLM for classification - course: {block.get('course_number')}, explanation: {explanation[:100] if explanation else 'none'}")
                    summary = await _summarize_user_preferences_with_llm(current_prefs, current_notes)
                    if summary:
                        update_type = summary.get("update_type", "general_preferences")
                        course_number = block.get("course_number")
                        logging.info(f"📊 [MOVE BLOCK] LLM classified as: {update_type} for course {course_number}")
                        
                        if update_type == "hours_distribution":
                            # Update course_time_preferences based on LLM classification
                            course_notes = summary.get("course_notes", [])
                            
                            # Find the note for this course
                            course_note = None
                            for note in course_notes:
                                if str(note.get("course", "")).strip() == str(course_number).strip():
                                    course_note = note
                                    break
                            
                            if course_note:
                                hours_change = course_note.get("hours_change")  # "more" or "less"
                                logging.info(f"📝 [MOVE BLOCK] Found course_note: hours_change={hours_change}, note={course_note.get('note', '')[:50]}")
                                
                                # Get current preferences
                                current_pref_result = client.table("course_time_preferences").select("personal_hours_per_week, group_hours_per_week").eq("user_id", user_id).eq("course_number", course_number).limit(1).execute()
                                
                                if current_pref_result.data and current_pref_result.data[0].get("personal_hours_per_week") is not None:
                                    # Convert to float to handle decimal values
                                    current_personal_hours = float(current_pref_result.data[0]["personal_hours_per_week"])
                                    current_group_hours = float(current_pref_result.data[0].get("group_hours_per_week", 0))
                                    logging.info(f"📊 [MOVE BLOCK] Current preferences: personal={current_personal_hours}h, group={current_group_hours}h")
                                    
                                    # Calculate adjustment based on LLM classification
                                    # If LLM classified as "less", reduce by ~20% (or 1-2 hours minimum)
                                    # If LLM classified as "more", increase by ~20% (or 1-2 hours minimum)
                                    if hours_change == "less":
                                        # Reduce personal hours (keep as decimal)
                                        adjustment = max(1.0, current_personal_hours * 0.2)  # Reduce by 20% or at least 1 hour
                                        new_personal_hours = max(1.0, current_personal_hours - adjustment)
                                        # Keep group hours the same (or adjust proportionally if needed)
                                        new_group_hours = current_group_hours
                                        logging.info(f"➖ [MOVE BLOCK] Reducing hours: adjustment={adjustment}, new_personal_hours={new_personal_hours}")
                                    elif hours_change == "more":
                                        # Increase personal hours (keep as decimal)
                                        adjustment = max(1.0, current_personal_hours * 0.2)  # Increase by 20% or at least 1 hour
                                        new_personal_hours = current_personal_hours + adjustment
                                        # Keep group hours the same (or adjust proportionally if needed)
                                        new_group_hours = current_group_hours
                                        logging.info(f"➕ [MOVE BLOCK] Increasing hours: adjustment={adjustment}, new_personal_hours={new_personal_hours}")
                                    else:
                                        # No specific change direction, use current distribution from blocks
                                        logging.info(f"🔄 [MOVE BLOCK] No specific hours_change direction, using current blocks distribution")
                                        plan_result = client.table("weekly_plans").select("id").eq("user_id", user_id).eq("week_start", week_start).limit(1).execute()
                                        if plan_result.data:
                                            plan_id = plan_result.data[0]["id"]
                                            all_course_blocks = client.table("weekly_plan_blocks").select("work_type").eq("plan_id", plan_id).eq("course_number", course_number).execute()
                                            new_personal_hours = float(sum(1 for b in (all_course_blocks.data or []) if b.get("work_type") == "personal"))
                                            new_group_hours = float(sum(1 for b in (all_course_blocks.data or []) if b.get("work_type") == "group"))
                                            logging.info(f"📊 [MOVE BLOCK] From blocks: personal={new_personal_hours}h, group={new_group_hours}h")
                                        else:
                                            new_personal_hours = current_personal_hours
                                            new_group_hours = current_group_hours
                                    
                                    # Apply weighted average: 80% existing, 20% new (keep as decimal)
                                    personal_hours = round(0.8 * current_personal_hours + 0.2 * new_personal_hours, 2)
                                    group_hours = round(0.8 * current_group_hours + 0.2 * new_group_hours, 2)
                                    logging.info(f"⚖️ [MOVE BLOCK] Weighted average: personal={personal_hours}h (80% of {current_personal_hours} + 20% of {new_personal_hours}), group={group_hours}h")
                                    
                                    # Update course_time_preferences
                                    client.table("course_time_preferences").upsert({
                                        "user_id": user_id,
                                        "course_number": course_number,
                                        "personal_hours_per_week": personal_hours,
                                        "group_hours_per_week": group_hours
                                    }, on_conflict="user_id,course_number").execute()
                                    
                                    logging.info(f"✅ [MOVE BLOCK] Updated course_time_preferences for {course_number}: personal={personal_hours}h (was {current_personal_hours}h, LLM classified as {hours_change}), group={group_hours}h")
                                    preferences_updated = True
                                else:
                                    # No existing preferences, create new ones based on LLM classification
                                    # Get course credit_points to calculate defaults
                                    course_result = client.table("courses").select("credit_points").eq("user_id", user_id).eq("course_number", course_number).limit(1).execute()
                                    credit_points = course_result.data[0].get("credit_points") if course_result.data else 3
                                    total_hours = credit_points * 3
                                    
                                    if hours_change == "less":
                                        default_personal_hours = max(1, int(total_hours * 0.4))  # Less hours
                                    elif hours_change == "more":
                                        default_personal_hours = max(1, int(total_hours * 0.6))  # More hours
                                    else:
                                        default_personal_hours = max(1, int(total_hours * 0.5))  # Default
                                    
                                    default_group_hours = max(1, total_hours - default_personal_hours)
                                    
                                    client.table("course_time_preferences").insert({
                                        "user_id": user_id,
                                        "course_number": course_number,
                                        "personal_hours_per_week": default_personal_hours,
                                        "group_hours_per_week": default_group_hours
                                    }).execute()
                                    
                                    logging.info(f"✅ [MOVE BLOCK] Created course_time_preferences for {course_number}: personal={default_personal_hours}h, group={default_group_hours}h (LLM classified as {hours_change})")
                                    preferences_updated = True
                            else:
                                logging.warning(f"⚠️ [MOVE BLOCK] LLM classified as hours_distribution but no course_notes found for course {course_number}")
                        else:
                            logging.info(f"📝 [MOVE BLOCK] update_type is '{update_type}' - only saving summary, not updating hours")
                        
                        # ALWAYS save the LLM summary to study_preferences_summary
                        # This is what we use when generating schedules (not the raw notes)
                        # The summary contains the classification (update_type) and extracted preferences
                        try:
                            update_result = client.table("user_profiles").update({
                                "study_preferences_summary": summary
                            }).eq("id", user_id).execute()
                            
                            if update_result.data:
                                logging.info(f"💾 [MOVE BLOCK] ✅ Successfully saved study_preferences_summary to database")
                                logging.info(f"   - update_type: {update_type}")
                                logging.info(f"   - summary_keys: {list(summary.keys())}")
                                logging.info(f"   - Updated rows: {len(update_result.data)}")
                                # Verify the update
                                verify_result = client.table("user_profiles").select("study_preferences_summary").eq("id", user_id).limit(1).execute()
                                if verify_result.data:
                                    saved_summary = verify_result.data[0].get("study_preferences_summary")
                                    if saved_summary:
                                        logging.info(f"   - ✅ Verified: study_preferences_summary exists in DB with {len(str(saved_summary))} chars")
                                    else:
                                        logging.warning(f"   - ⚠️ WARNING: study_preferences_summary is NULL in DB after update!")
                            else:
                                logging.error(f"❌ [MOVE BLOCK] Update returned no data - update may have failed")
                        except Exception as update_err:
                            logging.error(f"❌ [MOVE BLOCK] Failed to update study_preferences_summary: {update_err}", exc_info=True)
                        
                        preferences_updated = True
                    else:
                        logging.warning(f"⚠️ [MOVE BLOCK] LLM summary returned None - preferences not updated")
                        logging.warning(f"   - This means the LLM call failed or returned empty content")
                        logging.warning(f"   - Check previous logs for LLM CLASSIFICATION errors")
                            
                except Exception as sum_err:
                    logging.error(f"❌ Failed to update LLM summary: {sum_err}", exc_info=True)
                    # Even if LLM fails, we keep the notes for future summarization
                
            except Exception as pref_err:
                logging.error(f"Failed to update preferences: {pref_err}")
        
        return JSONResponse(content={
            "message": "Block moved successfully",
            "block": update_result.data[0] if update_result.data else {},
            "preferences_updated": preferences_updated
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error moving schedule block: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/schedule/block/resize")
async def resize_schedule_block(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    Resize a personal schedule block (change duration).
    Updates user preferences based on the explanation provided.
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        body = await request.json()
        course_number = body.get("course_number")
        day_of_week = body.get("day_of_week")
        start_time = body.get("start_time")
        old_duration = body.get("old_duration", 1)
        new_duration = body.get("new_duration", 1)
        explanation = body.get("explanation", "")
        week_start = body.get("week_start")
        
        if not all([course_number, day_of_week is not None, start_time, week_start]):
            raise HTTPException(status_code=400, detail="Missing required fields")
        
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        logging.info(f"Resizing block: course={course_number}, day={day_of_week}, time={start_time}, {old_duration}h -> {new_duration}h")
        
        # First, find the plan_id for this week
        plan_result = client.table("weekly_plans").select("id").eq("user_id", user_id).eq("week_start", week_start).limit(1).execute()
        if not plan_result.data:
            raise HTTPException(status_code=404, detail="No plan found for this week")
        plan_id = plan_result.data[0]["id"]
        
        # Find and delete existing blocks for this course at this time
        existing = client.table("weekly_plan_blocks").select("id, start_time").eq("plan_id", plan_id).eq("course_number", course_number).eq("day_of_week", day_of_week).eq("work_type", "personal").execute()
        
        # Find consecutive blocks starting from start_time
        time_slots = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00"]
        start_idx = time_slots.index(start_time) if start_time in time_slots else 0
        
        blocks_to_delete = []
        for block in (existing.data or []):
            block_idx = time_slots.index(block["start_time"]) if block["start_time"] in time_slots else -1
            if block_idx >= start_idx and block_idx < start_idx + old_duration:
                blocks_to_delete.append(block["id"])
        
        # Check for conflicts with hard constraints (both weekly and permanent) before resizing
        conflict_reasons = []
        
        # Calculate the time range that the new blocks would occupy
        new_start_time_obj = time_slots[start_idx] if start_idx < len(time_slots) else None
        new_end_idx = start_idx + new_duration
        new_end_time_obj = time_slots[new_end_idx] if new_end_idx < len(time_slots) else "21:00"
        
        new_start_minutes = _time_to_minutes(new_start_time_obj) if new_start_time_obj else 0
        new_end_minutes = _time_to_minutes(new_end_time_obj) if new_end_time_obj else 0
        
        # Check 1: Weekly hard constraints
        weekly_constraints = client.table("weekly_constraints").select("*").eq("user_id", user_id).eq("week_start", week_start).execute()
        for constraint in (weekly_constraints.data or []):
            if not constraint.get("is_hard", True):
                continue  # Skip soft constraints
            
            days_array = constraint.get("days", [])
            if isinstance(days_array, str):
                try:
                    import json
                    days_array = json.loads(days_array)
                except:
                    days_array = []
            
            if day_of_week in days_array:
                # Check time overlap
                c_start = _time_to_minutes(constraint.get("start_time", "00:00"))
                c_end = _time_to_minutes(constraint.get("end_time", "00:00"))
                
                if new_start_minutes < c_end and new_end_minutes > c_start:
                    conflict_reasons.append(f"אילוץ קשיח שבועי: {constraint.get('title', 'אילוץ')} ({constraint.get('start_time')}-{constraint.get('end_time')})")
        
        # Check 2: Permanent hard constraints
        permanent_constraints = client.table("constraints").select("*").eq("user_id", user_id).execute()
        import json
        for constraint in (permanent_constraints.data or []):
            if not constraint.get("is_hard", True):
                continue  # Skip soft constraints
            
            days_array = constraint.get("days", [])
            if isinstance(days_array, str):
                try:
                    days_array = json.loads(days_array)
                except:
                    days_array = []
            elif not isinstance(days_array, list):
                days_array = []
            
            if day_of_week in days_array:
                # Check time overlap
                c_start = _time_to_minutes(constraint.get("start_time", "00:00"))
                c_end = _time_to_minutes(constraint.get("end_time", "00:00"))
                
                if new_start_minutes < c_end and new_end_minutes > c_start:
                    conflict_reasons.append(f"אילוץ קשיח קבוע: {constraint.get('title', 'אילוץ')} ({constraint.get('start_time')}-{constraint.get('end_time')})")
        
        # Check 3: Conflicts with OTHER blocks (different courses) before resizing
        # Get all blocks for this day to check for overlaps
        all_blocks = client.table("weekly_plan_blocks").select("id, course_number, course_name, start_time, end_time").eq("plan_id", plan_id).eq("day_of_week", day_of_week).execute()
        
        # Check if any OTHER blocks (not the ones we're deleting) overlap with the new time range
        conflicting_blocks = []
        for block in (all_blocks.data or []):
            # Skip blocks we're about to delete (same course at same time)
            if block["id"] in blocks_to_delete:
                continue
            
            # Check if this block overlaps with the new time range
            block_start = block["start_time"]
            block_end = block["end_time"]
            
            # Convert times to minutes for comparison
            new_start_minutes = _time_to_minutes(new_start_time_obj) if new_start_time_obj and isinstance(new_start_time_obj, str) else 0
            new_end_minutes = _time_to_minutes(new_end_time_obj) if isinstance(new_end_time_obj, str) and new_end_time_obj else 0
            block_start_minutes = _time_to_minutes(block_start) if block_start and isinstance(block_start, str) else 0
            block_end_minutes = _time_to_minutes(block_end) if block_end and isinstance(block_end, str) else 0
            
            # Check for overlap: new block overlaps if it starts before other ends AND ends after other starts
            if new_start_minutes < block_end_minutes and new_end_minutes > block_start_minutes:
                conflicting_blocks.append({
                    "course_number": block.get("course_number", "?"),
                    "course_name": block.get("course_name", "קורס"),
                    "start_time": block_start,
                    "end_time": block_end
                })
        
        # Add block conflicts to conflict_reasons
        for conflict in conflicting_blocks:
            conflict_reasons.append(f"בלוק קיים: {conflict['course_name']} ({conflict['start_time']}-{conflict['end_time']})")
        
        # If there are conflicts, reject the resize and inform the user
        if conflict_reasons:
            conflict_message = "לא ניתן להגדיל את הבלוק - יש התנגשויות:\n" + "\n".join(conflict_reasons)
            raise HTTPException(
                status_code=400,
                detail=conflict_message
            )
        
        # No conflicts - proceed with resize
        # Delete old blocks
        for block_id in blocks_to_delete:
            client.table("weekly_plan_blocks").delete().eq("id", block_id).execute()
        
        # Get course name from catalog
        catalog_result = client.table("course_catalog").select("course_name").eq("course_number", course_number).limit(1).execute()
        course_name = catalog_result.data[0]["course_name"] if catalog_result.data else course_number
        
        # Create new blocks with new duration
        for i in range(new_duration):
            new_time = time_slots[start_idx + i] if (start_idx + i) < len(time_slots) else None
            if new_time:
                new_end = time_slots[start_idx + i + 1] if (start_idx + i + 1) < len(time_slots) else "21:00"
                client.table("weekly_plan_blocks").insert({
                    "plan_id": plan_id,
                    "user_id": user_id,
                    "course_number": course_number,
                    "course_name": course_name,
                    "work_type": "personal",
                    "day_of_week": day_of_week,
                    "start_time": new_time,
                    "end_time": new_end
                }).execute()
        
        preferences_updated = False
        
        # ALWAYS update course_time_preferences based on ALL blocks in the plan
        # This ensures the system learns from user behavior even without explanation
        try:
            # Get all blocks for this course in the plan to calculate actual distribution
            all_course_blocks = client.table("weekly_plan_blocks").select("work_type").eq("plan_id", plan_id).eq("course_number", course_number).execute()
            
            new_personal_hours = float(sum(1 for b in (all_course_blocks.data or []) if b.get("work_type") == "personal"))
            new_group_hours = float(sum(1 for b in (all_course_blocks.data or []) if b.get("work_type") == "group"))
            
            # Get current preferences for weighted average (80% existing, 20% new)
            pref_result = client.table("course_time_preferences").select("personal_hours_per_week, group_hours_per_week").eq("user_id", user_id).eq("course_number", course_number).limit(1).execute()
            
            if pref_result.data and pref_result.data[0].get("personal_hours_per_week") is not None:
                # Convert to float to handle decimal values
                current_personal_hours = float(pref_result.data[0]["personal_hours_per_week"])
                current_group_hours = float(pref_result.data[0].get("group_hours_per_week", 0))
                
                # Apply weighted average: 80% existing, 20% new (keep as decimal)
                personal_hours = round(0.8 * current_personal_hours + 0.2 * new_personal_hours, 2)
                group_hours = round(0.8 * current_group_hours + 0.2 * new_group_hours, 2)
                
                client.table("course_time_preferences").upsert({
                    "user_id": user_id,
                    "course_number": course_number,
                    "personal_hours_per_week": personal_hours,
                    "group_hours_per_week": group_hours
                }, on_conflict="user_id,course_number").execute()
                
                logging.info(f"✅ Updated course_time_preferences: personal={personal_hours}h (from {new_personal_hours}h in blocks), group={group_hours}h (from {new_group_hours}h in blocks)")
                preferences_updated = True
            else:
                # Create new entry
                course_result = client.table("courses").select("credit_points").eq("user_id", user_id).eq("course_number", course_number).limit(1).execute()
                credit_points = course_result.data[0].get("credit_points") if course_result.data else 3
                total_hours = credit_points * 3
                default_group_hours = max(1.0, float(total_hours * 0.5))
                
                client.table("course_time_preferences").insert({
                    "user_id": user_id,
                    "course_number": course_number,
                    "personal_hours_per_week": float(new_personal_hours) if new_personal_hours > 0 else float(new_duration),
                    "group_hours_per_week": default_group_hours
                }).execute()
                
                logging.info(f"✅ Created course_time_preferences: personal={new_personal_hours}h, group={default_group_hours}h")
                preferences_updated = True
        except Exception as pref_err:
            logging.warning(f"⚠️ Failed to update course_time_preferences: {pref_err}")
        
        # If explanation provided, update user preferences summary (not raw notes)
        if explanation.strip():
            try:
                # Get current preferences
                profile = client.table("user_profiles").select("study_preferences_raw, schedule_change_notes").eq("id", user_id).limit(1).execute()
                current_prefs = profile.data[0].get("study_preferences_raw", "") if profile.data else ""
                current_notes = profile.data[0].get("schedule_change_notes", []) if profile.data else []
                
                if not isinstance(current_notes, list):
                    current_notes = []
                
                # Add new note (for learning, but we'll use summary for actual scheduling)
                new_note = {
                    "date": datetime.now().isoformat(),
                    "course": course_number,
                    "change": f"{old_duration}h -> {new_duration}h",
                    "explanation": explanation
                }
                current_notes.append(new_note)
                
                # Save notes first (for LLM to analyze)
                client.table("user_profiles").update({
                    "schedule_change_notes": current_notes
                }).eq("id", user_id).execute()
                
                # ALWAYS call LLM to summarize preferences - this is what we use for scheduling
                # The summary is saved to study_preferences_summary and used when generating schedules
                try:
                    logging.info(f"🔄 [RESIZE BLOCK] Calling LLM for classification - course: {course_number}, explanation: {explanation[:100] if explanation else 'none'}")
                    summary = await _summarize_user_preferences_with_llm(current_prefs, current_notes)
                    if summary:
                        update_type = summary.get("update_type", "general_preferences")
                        logging.info(f"📊 [RESIZE BLOCK] LLM classified as: {update_type} for course {course_number}")
                        
                        if update_type == "hours_distribution":
                            logging.info(f"🔧 [RESIZE BLOCK] Processing hours_distribution update for course {course_number}")
                            # Update course_time_preferences based on LLM classification
                            course_notes = summary.get("course_notes", [])
                            
                            # Find the note for this course
                            course_note = None
                            for note in course_notes:
                                if str(note.get("course", "")).strip() == str(course_number).strip():
                                    course_note = note
                                    break
                            
                            if course_note:
                                hours_change = course_note.get("hours_change")  # "more" or "less"
                                logging.info(f"📝 [RESIZE BLOCK] Found course_note: hours_change={hours_change}, note={course_note.get('note', '')[:50]}")
                                
                                # Get current preferences
                                current_pref_result = client.table("course_time_preferences").select("personal_hours_per_week, group_hours_per_week").eq("user_id", user_id).eq("course_number", course_number).limit(1).execute()
                                
                                if current_pref_result.data and current_pref_result.data[0].get("personal_hours_per_week") is not None:
                                    # Convert to float to handle decimal values
                                    current_personal_hours = float(current_pref_result.data[0]["personal_hours_per_week"])
                                    current_group_hours = float(current_pref_result.data[0].get("group_hours_per_week", 0))
                                    logging.info(f"📊 [RESIZE BLOCK] Current preferences: personal={current_personal_hours}h, group={current_group_hours}h")
                                    
                                    # Calculate adjustment based on LLM classification
                                    if hours_change == "less":
                                        adjustment = max(1.0, current_personal_hours * 0.2)  # Keep as decimal
                                        new_personal_hours = max(1.0, current_personal_hours - adjustment)
                                        new_group_hours = current_group_hours
                                        logging.info(f"➖ [RESIZE BLOCK] Reducing hours: adjustment={adjustment}, new_personal_hours={new_personal_hours}")
                                    elif hours_change == "more":
                                        adjustment = max(1.0, current_personal_hours * 0.2)  # Keep as decimal
                                        new_personal_hours = current_personal_hours + adjustment
                                        new_group_hours = current_group_hours
                                        logging.info(f"➕ [RESIZE BLOCK] Increasing hours: adjustment={adjustment}, new_personal_hours={new_personal_hours}")
                                    else:
                                        # Use current distribution from blocks
                                        logging.info(f"🔄 [RESIZE BLOCK] No specific hours_change direction, using current blocks distribution")
                                        all_course_blocks = client.table("weekly_plan_blocks").select("work_type").eq("plan_id", plan_id).eq("course_number", course_number).execute()
                                        new_personal_hours = float(sum(1 for b in (all_course_blocks.data or []) if b.get("work_type") == "personal"))
                                        new_group_hours = float(sum(1 for b in (all_course_blocks.data or []) if b.get("work_type") == "group"))
                                        logging.info(f"📊 [RESIZE BLOCK] From blocks: personal={new_personal_hours}h, group={new_group_hours}h")
                                    
                                    # Apply weighted average: 80% existing, 20% new (keep as decimal)
                                    personal_hours = round(0.8 * current_personal_hours + 0.2 * new_personal_hours, 2)
                                    group_hours = round(0.8 * current_group_hours + 0.2 * new_group_hours, 2)
                                    logging.info(f"⚖️ [RESIZE BLOCK] Weighted average: personal={personal_hours}h (80% of {current_personal_hours} + 20% of {new_personal_hours}), group={group_hours}h")
                                    
                                    # Update course_time_preferences
                                    client.table("course_time_preferences").upsert({
                                        "user_id": user_id,
                                        "course_number": course_number,
                                        "personal_hours_per_week": personal_hours,
                                        "group_hours_per_week": group_hours
                                    }, on_conflict="user_id,course_number").execute()
                                    
                                    logging.info(f"✅ [RESIZE BLOCK] Updated course_time_preferences for {course_number}: personal={personal_hours}h (was {current_personal_hours}h, LLM classified as {hours_change}), group={group_hours}h")
                                    preferences_updated = True
                        
                        # ALWAYS save the LLM summary to study_preferences_summary
                        # This is what we use when generating schedules (not the raw notes)
                        # The summary contains the classification (update_type) and extracted preferences
                        try:
                            update_result = client.table("user_profiles").update({
                                "study_preferences_summary": summary
                            }).eq("id", user_id).execute()
                            
                            if update_result.data:
                                logging.info(f"💾 [RESIZE BLOCK] ✅ Successfully saved study_preferences_summary to database")
                                logging.info(f"   - update_type: {update_type}")
                                logging.info(f"   - summary_keys: {list(summary.keys())}")
                                logging.info(f"   - Updated rows: {len(update_result.data)}")
                                # Verify the update
                                verify_result = client.table("user_profiles").select("study_preferences_summary").eq("id", user_id).limit(1).execute()
                                if verify_result.data:
                                    saved_summary = verify_result.data[0].get("study_preferences_summary")
                                    if saved_summary:
                                        logging.info(f"   - ✅ Verified: study_preferences_summary exists in DB with {len(str(saved_summary))} chars")
                                    else:
                                        logging.warning(f"   - ⚠️ WARNING: study_preferences_summary is NULL in DB after update!")
                            else:
                                logging.error(f"❌ [RESIZE BLOCK] Update returned no data - update may have failed")
                        except Exception as update_err:
                            logging.error(f"❌ [RESIZE BLOCK] Failed to update study_preferences_summary: {update_err}", exc_info=True)
                        
                        preferences_updated = True
                    else:
                        logging.warning(f"⚠️ [RESIZE BLOCK] LLM summary returned None - preferences not updated")
                        logging.warning(f"   - This means the LLM call failed or returned empty content")
                        logging.warning(f"   - Check previous logs for LLM CLASSIFICATION errors")
                except Exception as sum_err:
                    logging.error(f"❌ Failed to update LLM summary: {sum_err}", exc_info=True)
                    # Even if LLM fails, we keep the notes for future summarization
                
            except Exception as pref_err:
                logging.error(f"Failed to update preferences: {pref_err}")
        
        logging.info(f"Successfully resized block: {course_number} {day_of_week} {start_time}")
        
        return JSONResponse(content={
            "message": "Block resized successfully",
            "preferences_updated": preferences_updated
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error resizing block: {e}")
        import traceback
        logging.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/schedule/group-change-request/create")
async def create_group_change_request(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a request to change a group meeting time or duration.
    Requires approval from all group members.
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        body = await request.json()
        group_id = body.get("group_id")
        week_start = body.get("week_start")
        request_type = body.get("request_type", "move")  # 'move' or 'resize'
        original_day = body.get("original_day_of_week")
        original_start = body.get("original_start_time")
        proposed_day = body.get("proposed_day_of_week")
        proposed_start = body.get("proposed_start_time")
        original_duration = body.get("original_duration_hours", 1)
        proposed_duration = body.get("proposed_duration_hours")
        reason = body.get("reason", "")
        hours_explanation = body.get("hours_explanation", "")
        
        # Validate based on request type
        if request_type == "move":
            if not all([group_id, week_start, proposed_day is not None, proposed_start]):
                raise HTTPException(status_code=400, detail="Missing required fields for move request")
        elif request_type == "resize":
            if not all([group_id, week_start, proposed_duration is not None]):
                raise HTTPException(status_code=400, detail="Missing required fields for resize request")
            # For resize, keep the same day/time
            proposed_day = original_day
            proposed_start = original_start
        
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Verify user is member of this group
        member_check = client.table("group_members").select("id").eq("group_id", group_id).eq("user_id", user_id).eq("status", "approved").execute()
        if not member_check.data:
            raise HTTPException(status_code=403, detail="Not a member of this group")
        
        # Calculate end times
        if request_type == "resize":
            original_end = _minutes_to_time(_time_to_minutes(original_start) + (original_duration * 60)) if original_start else None
            proposed_end = _minutes_to_time(_time_to_minutes(proposed_start) + (proposed_duration * 60)) if proposed_start else None
        else:
            original_end = _minutes_to_time(_time_to_minutes(original_start) + 60) if original_start else None
            proposed_end = _minutes_to_time(_time_to_minutes(proposed_start) + 60) if proposed_start else None
        
        # Check for conflicts in requester's schedule BEFORE creating the request
        # This is a warning - the request will still be created, but the requester will be notified
        requester_conflicts = []
        if proposed_day is not None and proposed_start:
            # Get requester's plan for this week
            plan_result = client.table("weekly_plans").select("id").eq("user_id", user_id).eq("week_start", week_start).limit(1).execute()
            if plan_result.data:
                plan_id = plan_result.data[0]["id"]
                
                # Check hard constraints
                constraints_result = client.table("constraints").select("*").eq("user_id", user_id).execute()
                weekly_constraints_result = client.table("weekly_constraints").select("*").eq("user_id", user_id).eq("week_start", week_start).execute()
                all_constraints = (constraints_result.data or []) + (weekly_constraints_result.data or [])
                
                for constraint in all_constraints:
                    if not constraint.get("is_hard", True):
                        continue
                    
                    constraint_days = constraint.get("days", [])
                    if not isinstance(constraint_days, list):
                        try:
                            constraint_days = json.loads(constraint_days) if isinstance(constraint_days, str) else []
                        except:
                            constraint_days = []
                    
                    if proposed_day not in constraint_days:
                        continue
                    
                    # Check time overlap
                    constraint_start = constraint.get("start_time")
                    constraint_end = constraint.get("end_time")
                    if constraint_start and constraint_end:
                        proposed_start_minutes = _time_to_minutes(proposed_start)
                        # For resize, use proposed_duration; for move, use 1 hour
                        duration_minutes = (proposed_duration * 60) if request_type == "resize" and proposed_duration else 60
                        proposed_end_minutes = _time_to_minutes(proposed_end) if proposed_end else proposed_start_minutes + duration_minutes
                        constraint_start_minutes = _time_to_minutes(constraint_start)
                        constraint_end_minutes = _time_to_minutes(constraint_end)
                        
                        if proposed_start_minutes < constraint_end_minutes and proposed_end_minutes > constraint_start_minutes:
                            requester_conflicts.append(f"אילוץ קשיח: {constraint.get('title', 'אילוץ')} ({constraint.get('start_time')}-{constraint.get('end_time')})")
                
                # Check existing blocks (excluding the current group block being changed)
                blocks_result = client.table("weekly_plan_blocks").select("course_name, start_time, end_time, work_type, course_number").eq("plan_id", plan_id).eq("day_of_week", proposed_day).execute()
                for block in (blocks_result.data or []):
                    # Skip the group block we're trying to change
                    if block.get("work_type") == "group":
                        group_info = client.table("study_groups").select("course_id").eq("id", group_id).limit(1).execute()
                        if group_info.data and group_info.data[0].get("course_id") == block.get("course_number"):
                            continue
                    
                    block_start = block.get("start_time")
                    block_end = block.get("end_time")
                    if block_start and block_end:
                        proposed_start_minutes = _time_to_minutes(proposed_start)
                        # For resize, use proposed_duration; for move, use 1 hour
                        duration_minutes = (proposed_duration * 60) if request_type == "resize" and proposed_duration else 60
                        proposed_end_minutes = _time_to_minutes(proposed_end) if proposed_end else proposed_start_minutes + duration_minutes
                        block_start_minutes = _time_to_minutes(block_start)
                        block_end_minutes = _time_to_minutes(block_end)
                        
                        if proposed_start_minutes < block_end_minutes and proposed_end_minutes > block_start_minutes:
                            requester_conflicts.append(f"לוז קיים: {block.get('course_name', 'קורס')} ({block.get('start_time')})")
        
        # Validate that the selected time range contains only consecutive blocks of the same course/group
        if request_type == "move" and original_day is not None and original_start and original_duration:
            # Get all group blocks for this group/day/week
            all_group_blocks = client.table("group_plan_blocks").select("id, start_time, end_time, course_number").eq("group_id", group_id).eq("week_start", week_start).eq("day_of_week", original_day).order("start_time").execute()
            
            # Find the starting block
            starting_block = None
            for block in (all_group_blocks.data or []):
                if block.get("start_time") == original_start:
                    starting_block = block
                    break
            
            if not starting_block:
                raise HTTPException(
                    status_code=400, 
                    detail=f"לא נמצא בלוק שמתחיל ב-{original_start}. אנא בדוק את הזמן הנבחר."
                )
            
            # Verify all blocks in the range are consecutive and belong to the same course/group
            blocks_in_range = [starting_block]
            current_end_time = starting_block.get("end_time")
            expected_course_number = starting_block.get("course_number")
            
            # Find consecutive blocks
            for block in (all_group_blocks.data or []):
                if block["id"] == starting_block["id"]:
                    continue  # Skip the starting block
                
                block_start = block.get("start_time")
                block_course = block.get("course_number")
                
                # Check if this block is consecutive (its start_time equals the current end_time)
                if block_start == current_end_time:
                    # Verify it's the same course/group
                    if block_course != expected_course_number:
                        raise HTTPException(
                            status_code=400,
                            detail=f"הטווח הנבחר מכיל בלוקים של קורסים שונים. לא ניתן להזיז בלוקים של קורסים שונים יחד."
                        )
                    blocks_in_range.append(block)
                    current_end_time = block.get("end_time")
                # Stop if we've found enough blocks or if there's a gap
                elif _time_to_minutes(block_start) > _time_to_minutes(current_end_time):
                    # There's a gap, stop looking
                    break
            
            # Verify we found the right number of blocks
            if len(blocks_in_range) < original_duration:
                raise HTTPException(
                    status_code=400,
                    detail=f"הטווח הנבחר ({original_duration} שעות) מכיל רק {len(blocks_in_range)} בלוקים רצופים. לא ניתן להזיז חלק מבלוק לא רצוף."
                )
            elif len(blocks_in_range) > original_duration:
                # This shouldn't happen, but log it
                logging.warning(f"Found {len(blocks_in_range)} consecutive blocks but only {original_duration} requested. Using requested duration.")
            
            logging.info(f"✅ Validated {original_duration} consecutive blocks starting at {original_start} for group {group_id}")
        
        # Create the change request
        request_data = {
            "group_id": group_id,
            "week_start": week_start,
            "request_type": request_type,
            "original_day_of_week": original_day,
            "original_start_time": original_start,
            "original_end_time": original_end,
            "original_duration_hours": original_duration,
            "proposed_day_of_week": proposed_day,
            "proposed_start_time": proposed_start,
            "proposed_end_time": proposed_end,
            "proposed_duration_hours": proposed_duration,
            "requested_by": user_id,
            "reason": reason,
            "hours_explanation": hours_explanation,
            "status": "pending"
        }
        
        request_result = client.table("group_meeting_change_requests").insert(request_data).execute()
        if not request_result.data:
            raise HTTPException(status_code=500, detail="Failed to create change request")
        
        change_request = request_result.data[0]
        request_id = change_request["id"]
        
        # Get all group members (except requester)
        members_result = client.table("group_members").select("user_id").eq("group_id", group_id).eq("status", "approved").execute()
        member_ids = [m["user_id"] for m in (members_result.data or []) if m["user_id"] != user_id]
        
        # Get group name
        group_result = client.table("study_groups").select("group_name, course_name").eq("id", group_id).limit(1).execute()
        group_name = group_result.data[0].get("group_name", "Group") if group_result.data else "Group"
        
        # Get requester name
        requester_result = client.table("user_profiles").select("name").eq("id", user_id).limit(1).execute()
        requester_name = requester_result.data[0].get("name", "A member") if requester_result.data else "A member"
        
        # Day names for display
        day_names = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
        
        # Build notification message based on request type
        if request_type == "resize":
            title = f"בקשת שינוי משך מפגש: {group_name}"
            message = f"{requester_name} מבקש לשנות את משך המפגש מ-{original_duration} שעות ל-{proposed_duration} שעות."
            if hours_explanation:
                message += f" סיבה: {hours_explanation}"
            message += " נדרש אישור מכל החברים."
        else:
            original_time_str = f"{day_names[original_day]} {original_start}" if original_day is not None else "קיים"
            proposed_time_str = f"{day_names[proposed_day]} {proposed_start}"
            title = f"בקשת שינוי מפגש: {group_name}"
            message = f"{requester_name} מבקש לשנות מפגש מ-{original_time_str} ל-{proposed_time_str}. נדרש אישור מכל החברים."
        
        # Send notifications to all members
        for member_id in member_ids:
            try:
                client.table("notifications").insert({
                    "user_id": member_id,
                    "type": "group_change_request",
                    "title": title,
                    "message": message,
                    "link": f"/schedule?change_request={request_id}",
                    "read": False
                }).execute()
            except Exception as notif_err:
                logging.error(f"Failed to notify member {member_id}: {notif_err}")
        
        logging.info(f"✅ Created group change request {request_id} for group {group_id}")
        
        # Build response message
        response_message = "Change request created. Waiting for approval from all members."
        if requester_conflicts:
            conflict_msg = "\n".join(requester_conflicts)
            response_message += f"\n\n⚠️ שים לב: הזמן החדש מתנגש עם הלוח שלך:\n{conflict_msg}\n\nהבקשה תישלח לחברים, אבל אם תאושר, זה יתנגש עם הלוח שלך."
        
        return JSONResponse(content={
            "message": response_message,
            "request": change_request,
            "members_to_approve": len(member_ids),
            "requester_has_conflicts": len(requester_conflicts) > 0,
            "requester_conflicts": requester_conflicts
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error creating group change request: {e}")
        import traceback
        logging.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/schedule/group-change-request/{request_id}/approve")
async def approve_group_change_request(
    request_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Approve a group meeting change request.
    If all members approve, the change is applied.
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Get the request
        request_result = client.table("group_meeting_change_requests").select("*").eq("id", request_id).limit(1).execute()
        if not request_result.data:
            raise HTTPException(status_code=404, detail="Change request not found")
        
        change_request = request_result.data[0]
        
        if change_request["status"] != "pending":
            raise HTTPException(status_code=400, detail=f"Request is already {change_request['status']}")
        
        # Verify user is member of this group
        group_id = change_request["group_id"]
        member_check = client.table("group_members").select("id").eq("group_id", group_id).eq("user_id", user_id).eq("status", "approved").execute()
        if not member_check.data:
            raise HTTPException(status_code=403, detail="Not a member of this group")
        
        # Check for conflicts BEFORE approving
        week_start = change_request["week_start"]
        proposed_day = change_request["proposed_day_of_week"]
        proposed_start = change_request["proposed_start_time"]
        proposed_duration = change_request.get("proposed_duration_hours", 1)
        request_type = change_request.get("request_type", "move")
        original_day = change_request.get("original_day_of_week")
        original_start = change_request.get("original_start_time")
        original_duration = change_request.get("original_duration_hours", 1)
        
        # For move and resize requests, check if the new time slot has conflicts
        if request_type == "move" or request_type == "resize":
            conflict_reasons = []
            
            # For resize, use original day/start (the meeting stays in place, just duration changes)
            # For move, use proposed day/start (the meeting moves to a new location)
            check_day = original_day if (request_type == "resize" and original_day is not None) else proposed_day
            check_start = original_start if (request_type == "resize" and original_start) else proposed_start
            check_duration = proposed_duration  # Always check the new duration
            
            # Check 1: Weekly constraints (hard constraints)
            weekly_constraints = client.table("weekly_constraints").select("*").eq("user_id", user_id).eq("week_start", week_start).execute()
            for constraint in (weekly_constraints.data or []):
                if not constraint.get("is_hard", True):
                    continue  # Skip soft constraints
                
                days_array = constraint.get("days", [])
                if isinstance(days_array, str):
                    try:
                        days_array = json.loads(days_array)
                    except:
                        days_array = []
                
                if check_day in days_array:
                    # Check time overlap
                    c_start = _time_to_minutes(constraint.get("start_time", "00:00"))
                    c_end = _time_to_minutes(constraint.get("end_time", "00:00"))
                    p_start = _time_to_minutes(check_start) if check_start else 0
                    p_end = p_start + (check_duration * 60) if check_duration else p_start + 60
                    
                    if p_start < c_end and p_end > c_start:
                        conflict_reasons.append(f"אילוץ קשיח שבועי: {constraint.get('title', 'אילוץ')} ({constraint.get('start_time')}-{constraint.get('end_time')})")
            
            # Check 1b: Permanent constraints (hard constraints)
            permanent_constraints = client.table("constraints").select("*").eq("user_id", user_id).execute()
            import json
            for constraint in (permanent_constraints.data or []):
                if not constraint.get("is_hard", True):
                    continue  # Skip soft constraints
                
                days_array = constraint.get("days", [])
                if isinstance(days_array, str):
                    try:
                        days_array = json.loads(days_array)
                    except:
                        days_array = []
                elif not isinstance(days_array, list):
                    days_array = []
                
                if check_day in days_array:
                    # Check time overlap
                    c_start = _time_to_minutes(constraint.get("start_time", "00:00"))
                    c_end = _time_to_minutes(constraint.get("end_time", "00:00"))
                    p_start = _time_to_minutes(check_start) if check_start else 0
                    p_end = p_start + (check_duration * 60) if check_duration else p_start + 60
                    
                    if p_start < c_end and p_end > c_start:
                        conflict_reasons.append(f"אילוץ קשיח קבוע: {constraint.get('title', 'אילוץ')} ({constraint.get('start_time')}-{constraint.get('end_time')})")
            
            # Check 2: Existing blocks (other courses)
            # First get the plan_id for this week
            user_plan = client.table("weekly_plans").select("id").eq("user_id", user_id).eq("week_start", week_start).limit(1).execute()
            if user_plan.data:
                user_plan_id = user_plan.data[0]["id"]
                existing_blocks = client.table("weekly_plan_blocks").select("*").eq("plan_id", user_plan_id).eq("day_of_week", check_day).execute()
            else:
                existing_blocks = type('obj', (object,), {'data': []})()
            
            # Get course_number from group to skip it
            group_info_for_conflict = client.table("study_groups").select("course_id").eq("id", group_id).limit(1).execute()
            group_course_number = group_info_for_conflict.data[0].get("course_id") if group_info_for_conflict.data else None
            
            for block in (existing_blocks.data or []):
                # Skip if it's the same group's block (we're moving/resizing it)
                if block.get("work_type") == "group" and block.get("course_number") == group_course_number:
                    continue
                
                b_start = _time_to_minutes(block.get("start_time", "00:00"))
                # Use end_time if available, otherwise assume 1 hour
                block_end_time = block.get("end_time")
                if block_end_time:
                    b_end = _time_to_minutes(block_end_time)
                else:
                    b_end = b_start + 60  # Each block is 1 hour
                p_start = _time_to_minutes(check_start) if check_start else 0
                p_end = p_start + (check_duration * 60) if check_duration else p_start + 60
                
                if p_start < b_end and p_end > b_start:
                    conflict_reasons.append(f"לוז קיים: {block.get('course_name', 'קורס')} ({block.get('start_time')})")
            
            # If there are conflicts, auto-reject and notify
            if conflict_reasons:
                day_names = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
                conflict_msg = "\\n".join(conflict_reasons)
                
                # Mark as rejected due to conflict
                client.table("group_change_approvals").upsert({
                    "request_id": request_id,
                    "user_id": user_id,
                    "approved": False,
                    "response_note": f"נדחה אוטומטית - התנגשות בלוז: {conflict_msg}"
                }, on_conflict="request_id,user_id").execute()
                
                # Update request status
                client.table("group_meeting_change_requests").update({
                    "status": "rejected",
                    "resolved_at": datetime.now().isoformat()
                }).eq("id", request_id).execute()
                
                # Delete all existing notifications about this change request for all members
                all_members = client.table("group_members").select("user_id").eq("group_id", group_id).eq("status", "approved").execute()
                member_ids = [m["user_id"] for m in (all_members.data or [])]
                request_link_pattern = f"/schedule?change_request={request_id}"
                for mid in member_ids:
                    try:
                        # Delete notifications of type "group_change_request" that link to this request
                        existing_notifications = client.table("notifications").select("id, link").eq("user_id", mid).eq("type", "group_change_request").execute()
                        for notif in (existing_notifications.data or []):
                            # Check if the link contains this request_id
                            notif_link = notif.get("link", "")
                            if request_id in notif_link:
                                client.table("notifications").delete().eq("id", notif["id"]).execute()
                                logging.info(f"🗑️ Deleted notification {notif['id']} for user {mid} (auto-rejected request {request_id} due to conflict)")
                    except Exception as del_err:
                        logging.warning(f"Failed to delete existing notifications for member {mid}: {del_err}")
                
                # Notify the requester about the rejection
                requester_id = change_request.get("requested_by")
                if requester_id:
                    group_result = client.table("study_groups").select("group_name").eq("id", group_id).limit(1).execute()
                    group_name = group_result.data[0].get("group_name", "Group") if group_result.data else "Group"
                    
                    # Create appropriate message based on request type
                    if request_type == "resize":
                        action_text = f"להאריך מפגש ל-{proposed_duration} שעות"
                        time_text = f"ביום {day_names[check_day]} {check_start}"
                    else:
                        action_text = "להזיז מפגש"
                        time_text = f"ליום {day_names[check_day]} {check_start}"
                    
                    client.table("notifications").insert({
                        "user_id": requester_id,
                        "type": "group_change_rejected",
                        "title": f"בקשת שינוי נדחתה: {group_name}",
                        "message": f"הבקשה {action_text} {time_text} נדחתה בגלל התנגשות בלוז של אחד החברים.",
                        "link": f"/schedule?week={week_start}",
                        "read": False
                    }).execute()
                
                raise HTTPException(
                    status_code=400, 
                    detail=f"לא ניתן לאשר - יש התנגשות בלוז שלך:\\n{conflict_msg}"
                )
        
        # No conflicts - record the approval
        try:
            client.table("group_change_approvals").insert({
                "request_id": request_id,
                "user_id": user_id,
                "approved": True
            }).execute()
        except Exception as e:
            # Might already exist
            client.table("group_change_approvals").update({
                "approved": True,
                "responded_at": datetime.now().isoformat()
            }).eq("request_id", request_id).eq("user_id", user_id).execute()
        
        # Mark related notification as read
        try:
            request_link_pattern = f"/schedule?change_request={request_id}"
            client.table("notifications").update({
                "read": True
            }).eq("user_id", user_id).eq("type", "group_change_request").like("link", f"%change_request={request_id}%").execute()
            logging.info(f"✅ Marked notification as read for user {user_id}")
        except Exception as notif_update_err:
            logging.warning(f"⚠️ Could not update notification: {notif_update_err}")
        
        # Check if all members have approved
        # IMPORTANT: The requester doesn't need to approve their own request
        requester_id = change_request.get("requested_by")
        all_members = client.table("group_members").select("user_id").eq("group_id", group_id).eq("status", "approved").execute()
        member_ids = [m["user_id"] for m in (all_members.data or [])]
        
        # Exclude requester from approval check - they already approved by creating the request
        members_needing_approval = [mid for mid in member_ids if mid != requester_id]
        
        approvals = client.table("group_change_approvals").select("user_id, approved").eq("request_id", request_id).execute()
        approval_map = {a["user_id"]: a["approved"] for a in (approvals.data or [])}
        
        # Check if all members (except requester) have approved
        all_responded = all(mid in approval_map for mid in members_needing_approval)
        all_approved = all_responded and all(approval_map.get(mid, False) for mid in members_needing_approval)
        
        logging.info(f"📊 Approval check for request {request_id}: all_responded={all_responded}, all_approved={all_approved}, members_needing_approval={len(members_needing_approval)}, approvals={len(approval_map)}")
        
        if all_approved:
            # Apply the change!
            week_start = change_request["week_start"]
            request_type = change_request.get("request_type", "move")
            proposed_day = change_request["proposed_day_of_week"]
            proposed_start = change_request["proposed_start_time"]
            proposed_end = change_request["proposed_end_time"]
            proposed_duration = change_request.get("proposed_duration_hours")
            
            # Calculate proposed_duration from proposed_start and proposed_end if not provided
            if not proposed_duration and proposed_start and proposed_end:
                # Calculate duration from the time range
                proposed_start_minutes = _time_to_minutes(proposed_start)
                proposed_end_minutes = _time_to_minutes(proposed_end)
                proposed_duration = (proposed_end_minutes - proposed_start_minutes) // 60
                logging.info(f"📊 Calculated proposed_duration from time range: {proposed_start}-{proposed_end} = {proposed_duration} hours")
            
            hours_explanation = change_request.get("hours_explanation", "")
            
            if request_type == "resize" and proposed_duration:
                # Handle resize: update duration of group blocks
                # IMPORTANT: Keep the original time/position, only add/remove blocks at the end
                original_duration = change_request.get("original_duration_hours", 1)
                original_day = change_request.get("original_day_of_week")
                original_start = change_request.get("original_start_time")
                
                # Use original time/position, not proposed (for resize, we keep the same location)
                actual_day = original_day if original_day is not None else proposed_day
                actual_start = original_start if original_start else proposed_start
                
                # Get course info
                group_info = client.table("study_groups").select("course_id, course_name").eq("id", group_id).limit(1).execute()
                course_number = group_info.data[0].get("course_id") if group_info.data else ""
                course_name = group_info.data[0].get("course_name") if group_info.data else ""
                
                # Get existing blocks to preserve their order and position
                existing_group_blocks = client.table("group_plan_blocks").select("*").eq("group_id", group_id).eq("week_start", week_start).eq("day_of_week", actual_day).order("start_time").execute()
                
                time_slots = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00"]
                
                # Find the start index based on existing blocks or original start
                # ALWAYS use original_start to preserve the exact position
                start_idx = time_slots.index(actual_start) if actual_start in time_slots else 0
                
                # Verify existing blocks match the original start (if they exist)
                if existing_group_blocks.data and len(existing_group_blocks.data) > 0:
                    first_block_start = existing_group_blocks.data[0].get("start_time")
                    if first_block_start != actual_start:
                        logging.warning(f"⚠️ Existing blocks start at {first_block_start} but original was {actual_start}. Using original.")
                
                # Calculate how many blocks to add/remove
                duration_diff = proposed_duration - original_duration
                
                if duration_diff > 0:
                    # Need to add blocks - find the last existing block's end time
                    if existing_group_blocks.data and len(existing_group_blocks.data) > 0:
                        last_block = existing_group_blocks.data[-1]
                        last_end = last_block.get("end_time")
                        # Find the index of the last block's end time (which is the start of the next block)
                        if last_end in time_slots:
                            start_idx = time_slots.index(last_end)
                        else:
                            # Calculate from last block's start
                            last_start = last_block.get("start_time")
                            if last_start in time_slots:
                                start_idx = time_slots.index(last_start) + 1
                    
                    # Check for conflicts BEFORE adding blocks - check if the new time slots are free
                    new_start_time = time_slots[start_idx] if start_idx < len(time_slots) else None
                    new_end_time = time_slots[start_idx + duration_diff] if (start_idx + duration_diff) < len(time_slots) else "21:00"
                    
                    if new_start_time:
                        # Check conflicts in group_plan_blocks (other groups at same time)
                        conflicting_group_blocks = client.table("group_plan_blocks").select("group_id, start_time, end_time").eq("week_start", week_start).eq("day_of_week", actual_day).execute()
                        
                        new_start_minutes = _time_to_minutes(new_start_time)
                        new_end_minutes = _time_to_minutes(new_end_time) if new_end_time != "21:00" else _time_to_minutes("21:00")
                        
                        has_group_conflict = False
                        for conflict_block in (conflicting_group_blocks.data or []):
                            # Skip blocks from the same group
                            if conflict_block.get("group_id") == group_id:
                                continue
                            
                            conflict_start = _time_to_minutes(conflict_block.get("start_time", "00:00"))
                            conflict_end = _time_to_minutes(conflict_block.get("end_time", "00:00"))
                            
                            # Check for overlap
                            if new_start_minutes < conflict_end and new_end_minutes > conflict_start:
                                has_group_conflict = True
                                logging.error(f"❌ Group block conflict detected: new blocks {new_start_time}-{new_end_time} overlap with group {conflict_block.get('group_id')} at {conflict_block.get('start_time')}-{conflict_block.get('end_time')}")
                        
                        if has_group_conflict:
                            # This should not happen if approval process worked correctly
                            # But we'll log it and skip adding the blocks to prevent data corruption
                            logging.error(f"❌ Cannot add group blocks due to conflicts. This indicates a bug in the approval process.")
                            raise HTTPException(
                                status_code=400,
                                detail=f"לא ניתן להוסיף בלוקים - יש התנגשות עם קבוצה אחרת. זה באג - אנא דווח על כך."
                            )
                    
                    # Add new blocks starting from start_idx
                    new_group_blocks = []
                    for i in range(duration_diff):
                        new_time = time_slots[start_idx + i] if (start_idx + i) < len(time_slots) else None
                        if new_time:
                            new_end = time_slots[start_idx + i + 1] if (start_idx + i + 1) < len(time_slots) else "21:00"
                            new_group_blocks.append({
                                "group_id": group_id,
                                "week_start": week_start,
                                "course_number": course_number,
                                "day_of_week": actual_day,
                                "start_time": new_time,
                                "end_time": new_end,
                                "created_by": user_id
                            })
                    
                    if new_group_blocks:
                        client.table("group_plan_blocks").insert(new_group_blocks).execute()
                        logging.info(f"✅ Added {len(new_group_blocks)} new group blocks")
                
                elif duration_diff < 0:
                    # Need to remove blocks - remove from the end
                    blocks_to_remove = abs(duration_diff)
                    if existing_group_blocks.data and len(existing_group_blocks.data) >= blocks_to_remove:
                        # Get the last N blocks to remove
                        blocks_to_delete = existing_group_blocks.data[-blocks_to_remove:]
                        for block in blocks_to_delete:
                            client.table("group_plan_blocks").delete().eq("id", block["id"]).execute()
                        logging.info(f"✅ Removed {blocks_to_remove} group blocks from the end")
                
                # Now update each member's weekly_plan_blocks
                for mid in member_ids:
                    # Get or create plan for this member
                    member_plan = client.table("weekly_plans").select("id").eq("user_id", mid).eq("week_start", week_start).limit(1).execute()
                    if member_plan.data:
                        plan_id = member_plan.data[0]["id"]
                    else:
                        plan_result = client.table("weekly_plans").insert({
                            "user_id": mid,
                            "week_start": week_start,
                            "source": "group_update"
                        }).execute()
                        plan_id = plan_result.data[0]["id"] if plan_result.data else None
                    
                    if plan_id:
                        # Get existing member blocks
                        existing_member_blocks = client.table("weekly_plan_blocks").select("*").eq("plan_id", plan_id).eq("work_type", "group").eq("course_number", course_number).eq("day_of_week", actual_day).order("start_time").execute()
                        
                        if duration_diff > 0:
                            # Add new blocks for this member
                            if existing_member_blocks.data and len(existing_member_blocks.data) > 0:
                                last_block = existing_member_blocks.data[-1]
                                last_end = last_block.get("end_time")
                                if last_end in time_slots:
                                    member_start_idx = time_slots.index(last_end)
                                else:
                                    last_start = last_block.get("start_time")
                                    member_start_idx = time_slots.index(last_start) + 1 if last_start in time_slots else start_idx
                            else:
                                member_start_idx = start_idx
                            
                            # Check for conflicts with OTHER blocks (different courses) for this member BEFORE adding
                            new_start_time = time_slots[member_start_idx] if member_start_idx < len(time_slots) else None
                            new_end_time = time_slots[member_start_idx + duration_diff] if (member_start_idx + duration_diff) < len(time_slots) else "21:00"
                            
                            if new_start_time:
                                # Get all blocks for this member on this day (excluding the group blocks we're updating)
                                all_member_blocks = client.table("weekly_plan_blocks").select("*").eq("plan_id", plan_id).eq("day_of_week", actual_day).execute()
                                
                                new_start_minutes = _time_to_minutes(new_start_time)
                                new_end_minutes = _time_to_minutes(new_end_time) if new_end_time != "21:00" else _time_to_minutes("21:00")
                                
                                conflicting_blocks = []
                                for block in (all_member_blocks.data or []):
                                    # Skip the group blocks we're updating (same course, group work type)
                                    if block.get("work_type") == "group" and block.get("course_number") == course_number:
                                        continue
                                    
                                    block_start = _time_to_minutes(block.get("start_time", "00:00"))
                                    block_end = _time_to_minutes(block.get("end_time", "00:00")) if block.get("end_time") else block_start + 60
                                    
                                    # Check for overlap
                                    if new_start_minutes < block_end and new_end_minutes > block_start:
                                        conflicting_blocks.append({
                                            "course_name": block.get("course_name", "קורס"),
                                            "start_time": block.get("start_time"),
                                            "end_time": block.get("end_time"),
                                            "work_type": block.get("work_type", "personal")
                                        })
                                
                                if conflicting_blocks:
                                    # This is a serious issue - conflicts should have been caught during approval
                                    conflict_details = ", ".join([f"{b['course_name']} ({b['start_time']}, {b['work_type']})" for b in conflicting_blocks])
                                    logging.error(f"❌ Member {mid} has CONFLICTS when adding group blocks: {conflict_details}")
                                    # Still add the blocks (they were approved), but this indicates a bug in the approval process
                            
                            new_member_blocks = []
                            for i in range(duration_diff):
                                new_time = time_slots[member_start_idx + i] if (member_start_idx + i) < len(time_slots) else None
                                if new_time:
                                    new_end = time_slots[member_start_idx + i + 1] if (member_start_idx + i + 1) < len(time_slots) else "21:00"
                                    new_member_blocks.append({
                                        "plan_id": plan_id,
                                        "user_id": mid,
                                        "course_number": course_number,
                                        "course_name": course_name,
                                        "work_type": "group",
                                        "day_of_week": actual_day,
                                        "start_time": new_time,
                                        "end_time": new_end,
                                        "source": "group"
                                    })
                            
                            if new_member_blocks:
                                client.table("weekly_plan_blocks").insert(new_member_blocks).execute()
                                logging.info(f"✅ Added {len(new_member_blocks)} blocks for member {mid}")
                        
                        elif duration_diff < 0:
                            # Remove blocks from the end for this member
                            blocks_to_remove = abs(duration_diff)
                            if existing_member_blocks.data and len(existing_member_blocks.data) >= blocks_to_remove:
                                blocks_to_delete = existing_member_blocks.data[-blocks_to_remove:]
                                for block in blocks_to_delete:
                                    client.table("weekly_plan_blocks").delete().eq("id", block["id"]).execute()
                                logging.info(f"✅ Removed {blocks_to_remove} blocks for member {mid}")
                
                logging.info(f"✅ Successfully updated group_plan_blocks and all member weekly_plan_blocks for resize: {original_duration}h -> {proposed_duration}h (kept original position)")
                
                # ALWAYS update group preferences with new hours (even without explanation)
                # This affects future schedule generation
                try:
                    # Get or create group preferences
                    gp = client.table("group_preferences").select("*").eq("group_id", group_id).limit(1).execute()
                    
                    # Check if this is a new block (original_duration = 0 and original_day is None)
                    is_new_block = (original_duration == 0 and original_day is None)
                    
                    if gp.data:
                        current_history = gp.data[0].get("hours_change_history", []) or []
                        if not isinstance(current_history, list):
                            current_history = []
                        
                        # Add to history
                        history_entry = {
                            "date": datetime.now().isoformat(),
                            "old_hours": original_duration,
                            "new_hours": proposed_duration,
                            "approved_by": member_ids
                        }
                        if hours_explanation:
                            history_entry["reason"] = hours_explanation
                        current_history.append(history_entry)
                        
                        current_hours = gp.data[0].get("preferred_hours_per_week", 4)
                        
                        # If this is a new block AND there are no existing group hours (current_hours = 0),
                        # use 100% of the new hours instead of weighted average
                        if is_new_block and current_hours == 0:
                            weighted_hours = proposed_duration
                            logging.info(f"✅ Updated group_preferences: {current_hours}h -> {weighted_hours}h (100% - first group block)")
                        else:
                            # Calculate weighted average: 80% existing, 20% new
                            weighted_hours = int(0.8 * current_hours + 0.2 * proposed_duration)
                            logging.info(f"✅ Updated group_preferences: {current_hours}h -> {weighted_hours}h (weighted average: 80% existing, 20% new)")
                        
                        client.table("group_preferences").update({
                            "preferred_hours_per_week": weighted_hours,
                            "hours_change_history": current_history,
                            "updated_at": datetime.now().isoformat()
                        }).eq("group_id", group_id).execute()
                    else:
                        # Create new group preferences
                        history_entry = {
                            "date": datetime.now().isoformat(),
                            "old_hours": original_duration,
                            "new_hours": proposed_duration,
                            "approved_by": member_ids
                        }
                        if hours_explanation:
                            history_entry["reason"] = hours_explanation
                        
                        # For new group preferences, use proposed_duration directly (no existing value to average)
                        # This is always 100% since there are no existing preferences
                        client.table("group_preferences").insert({
                            "group_id": group_id,
                            "preferred_hours_per_week": proposed_duration,
                            "hours_change_history": [history_entry]
                        }).execute()
                        
                        logging.info(f"✅ Created group_preferences: {proposed_duration}h per week (new group - 100%)")
                        weighted_hours = proposed_duration
                    
                    # IMPORTANT: Also update course_time_preferences.group_hours_per_week for all members
                    # This ensures consistency between group_preferences and course_time_preferences
                    try:
                        # Get course_number from group
                        group_info = client.table("study_groups").select("course_id").eq("id", group_id).limit(1).execute()
                        if group_info.data:
                            course_number = group_info.data[0].get("course_id")
                            
                            # Update course_time_preferences for all members
                            for member_id in member_ids:
                                try:
                                    # Get current course_time_preferences for this member
                                    member_pref_result = client.table("course_time_preferences").select("personal_hours_per_week, group_hours_per_week").eq("user_id", member_id).eq("course_number", course_number).limit(1).execute()
                                    
                                    if member_pref_result.data:
                                        # Convert to float to handle decimal values
                                        current_personal_hours = float(member_pref_result.data[0].get("personal_hours_per_week", 0))
                                        current_group_hours = float(member_pref_result.data[0].get("group_hours_per_week", 0))
                                        
                                        # Check if this is a new block (original_duration = 0 and original_day is None)
                                        # Use the same is_new_block variable from above (it's in the resize section)
                                        # For move section, we need to check again
                                        original_day_for_check = change_request.get("original_day_of_week")
                                        original_duration_for_check = change_request.get("original_duration_hours", 0)
                                        is_new_block_for_member = (original_duration_for_check == 0 and original_day_for_check is None)
                                        
                                        # If this is a new block AND there are no existing group hours (current_group_hours = 0),
                                        # use 100% of the new hours instead of weighted average
                                        if is_new_block_for_member and current_group_hours == 0:
                                            new_group_hours = float(weighted_hours)
                                            logging.info(f"✅ Updated course_time_preferences for member {member_id}, course {course_number}: group_hours={new_group_hours}h (100% - first group block)")
                                        else:
                                            # Apply weighted average: 80% existing, 20% new group hours (keep as decimal)
                                            new_group_hours = round(0.8 * current_group_hours + 0.2 * float(weighted_hours), 2)
                                            logging.info(f"✅ Updated course_time_preferences for member {member_id}, course {course_number}: group_hours={new_group_hours}h (weighted average)")
                                        
                                        # Update with weighted average or 100%
                                        client.table("course_time_preferences").update({
                                            "group_hours_per_week": new_group_hours
                                        }).eq("user_id", member_id).eq("course_number", course_number).execute()
                                    else:
                                        # Create new entry with default personal hours and new group hours
                                        # Get course credit_points to calculate default personal hours
                                        course_result = client.table("courses").select("credit_points").eq("user_id", member_id).eq("course_number", course_number).limit(1).execute()
                                        credit_points = course_result.data[0].get("credit_points") if course_result.data else 3
                                        total_hours = credit_points * 3
                                        default_personal_hours = max(1, int(total_hours * 0.5))
                                        
                                        client.table("course_time_preferences").insert({
                                            "user_id": member_id,
                                            "course_number": course_number,
                                            "personal_hours_per_week": default_personal_hours,
                                            "group_hours_per_week": weighted_hours
                                        }).execute()
                                        
                                        logging.info(f"✅ Created course_time_preferences for member {member_id}, course {course_number}: personal={default_personal_hours}h, group={weighted_hours}h")
                                except Exception as member_err:
                                    logging.warning(f"⚠️ Failed to update course_time_preferences for member {member_id}: {member_err}")
                    except Exception as course_pref_err:
                        logging.warning(f"⚠️ Failed to update course_time_preferences for group members: {course_pref_err}")
                    
                    logging.info(f"✅ Updated group preferences for group {group_id}: {original_duration}h -> {proposed_duration}h per week")
                except Exception as gp_err:
                    logging.error(f"Failed to update group preferences: {gp_err}")
            else:
                # Handle move: update time/day
                # Get original time/day from the request
                original_day = change_request.get("original_day_of_week")
                original_start = change_request.get("original_start_time")
                original_duration = change_request.get("original_duration_hours", 1)
                
                # Calculate original end time
                original_end = _minutes_to_time(_time_to_minutes(original_start) + (original_duration * 60)) if original_start else None
                
                # Calculate proposed_duration from proposed_start and proposed_end
                # Always recalculate from time range if both start and end are provided (more accurate)
                if proposed_start and proposed_end:
                    # Calculate duration from the time range (always use this if both times are provided)
                    proposed_start_minutes = _time_to_minutes(proposed_start)
                    proposed_end_minutes = _time_to_minutes(proposed_end)
                    proposed_duration = (proposed_end_minutes - proposed_start_minutes) // 60
                    logging.info(f"📊 Calculated proposed_duration from time range: {proposed_start}-{proposed_end} = {proposed_duration} hours")
                else:
                    # Fallback to proposed_duration from request or original_duration
                    proposed_duration = change_request.get("proposed_duration_hours") or original_duration
                    logging.info(f"⚠️ No proposed_end provided, using proposed_duration from request or original: {proposed_duration} hours")
                
                # Get course_number from group
                group_info_for_move = client.table("study_groups").select("course_id, course_name").eq("id", group_id).limit(1).execute()
                course_number_for_move = group_info_for_move.data[0].get("course_id") if group_info_for_move.data else ""
                course_name_for_move = group_info_for_move.data[0].get("course_name") if group_info_for_move.data else ""
                
                # Step 1: Delete old group_plan_blocks at original location
                # IMPORTANT: Delete ONLY blocks at the original location (original_day)
                # Do NOT delete blocks at the new location (proposed_day) even if they overlap
                if original_day is not None and original_start:
                    original_start_minutes = _time_to_minutes(original_start)
                    original_end_minutes = _time_to_minutes(original_end) if original_end else original_start_minutes + (original_duration * 60)
                    
                    # Get all blocks for this group/day/week at ORIGINAL location only
                    all_blocks = client.table("group_plan_blocks").select("id, start_time, end_time, day_of_week").eq("group_id", group_id).eq("week_start", week_start).eq("day_of_week", original_day).execute()
                    
                    # Calculate proposed time range for comparison
                    proposed_start_minutes = _time_to_minutes(proposed_start) if proposed_start else None
                    proposed_end_minutes = _time_to_minutes(proposed_end) if proposed_end else (proposed_start_minutes + ((proposed_duration if proposed_duration else 1) * 60) if proposed_start_minutes else None)
                    
                    blocks_to_delete = []
                    for block in (all_blocks.data or []):
                        # Only delete blocks at the original day
                        if block.get("day_of_week") != original_day:
                            continue
                        
                        block_start_minutes = _time_to_minutes(block.get("start_time", "00:00"))
                        block_end_minutes = _time_to_minutes(block.get("end_time", "00:00"))
                        
                        # Check if this block overlaps with the original time range
                        overlaps_original = block_start_minutes < original_end_minutes and block_end_minutes > original_start_minutes
                        
                        # If same day and new location overlaps, don't delete (it's the new block location)
                        if original_day == proposed_day and proposed_start_minutes is not None and proposed_end_minutes is not None:
                            overlaps_new = block_start_minutes < proposed_end_minutes and block_end_minutes > proposed_start_minutes
                            # If block overlaps with new location, it's part of the new blocks, don't delete
                            if overlaps_new:
                                continue
                        
                        if overlaps_original:
                            blocks_to_delete.append(block["id"])
                    
                    # Delete all overlapping blocks at original location
                    if blocks_to_delete:
                        for block_id in blocks_to_delete:
                            client.table("group_plan_blocks").delete().eq("id", block_id).execute()
                        logging.info(f"✅ Deleted {len(blocks_to_delete)} group_plan_blocks at original location (day={original_day}, time={original_start}-{original_end})")
                    else:
                        logging.warning(f"⚠️ No blocks found to delete at original location {original_start} for group {group_id}")
                
                # Step 2: Create new group_plan_blocks at new location
                # IMPORTANT: First check if there are existing blocks at the new location and delete them
                # This prevents duplicates if the request is processed multiple times
                if proposed_day is not None and proposed_start:
                    proposed_start_minutes = _time_to_minutes(proposed_start)
                    proposed_end_minutes = _time_to_minutes(proposed_end) if proposed_end else proposed_start_minutes + ((proposed_duration if proposed_duration else 1) * 60)
                    
                    # Check for existing blocks at new location (same group, same day, overlapping time)
                    existing_at_new_location = client.table("group_plan_blocks").select("id, start_time, end_time").eq("group_id", group_id).eq("week_start", week_start).eq("day_of_week", proposed_day).execute()
                    
                    blocks_to_delete_at_new = []
                    for block in (existing_at_new_location.data or []):
                        block_start_minutes = _time_to_minutes(block.get("start_time", "00:00"))
                        block_end_minutes = _time_to_minutes(block.get("end_time", "00:00"))
                        
                        # Check if this block overlaps with the proposed time range
                        if block_start_minutes < proposed_end_minutes and block_end_minutes > proposed_start_minutes:
                            blocks_to_delete_at_new.append(block["id"])
                    
                    # Delete any existing blocks at new location (prevents duplicates)
                    if blocks_to_delete_at_new:
                        for block_id in blocks_to_delete_at_new:
                            client.table("group_plan_blocks").delete().eq("id", block_id).execute()
                        logging.info(f"✅ Deleted {len(blocks_to_delete_at_new)} existing group_plan_blocks at new location (preventing duplicates)")
                
                time_slots = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00"]
                new_group_blocks = []
                
                # Find the closest time slot or use the proposed_start directly
                if proposed_start:
                    if proposed_start in time_slots:
                        start_idx = time_slots.index(proposed_start)
                    else:
                        # Find the closest time slot
                        proposed_minutes = _time_to_minutes(proposed_start)
                        closest_idx = 0
                        min_diff = abs(_time_to_minutes(time_slots[0]) - proposed_minutes)
                        for i, slot in enumerate(time_slots):
                            diff = abs(_time_to_minutes(slot) - proposed_minutes)
                            if diff < min_diff:
                                min_diff = diff
                                closest_idx = i
                        start_idx = closest_idx
                        logging.info(f"⚠️ proposed_start {proposed_start} not in time_slots, using closest: {time_slots[start_idx]}")
                    
                    # Use calculated proposed_duration (should be set above)
                    duration = proposed_duration if proposed_duration else original_duration
                    logging.info(f"📊 Creating {duration} blocks at new location (proposed_duration={proposed_duration}, original_duration={original_duration}, proposed_end={proposed_end})")
                    
                    # Calculate the end time slot index to ensure we don't exceed proposed_end
                    proposed_end_idx = None
                    if proposed_end:
                        if proposed_end in time_slots:
                            proposed_end_idx = time_slots.index(proposed_end)
                        else:
                            # Find closest time slot
                            proposed_end_minutes = _time_to_minutes(proposed_end)
                            closest_idx = 0
                            min_diff = abs(_time_to_minutes(time_slots[0]) - proposed_end_minutes)
                            for i, slot in enumerate(time_slots):
                                diff = abs(_time_to_minutes(slot) - proposed_end_minutes)
                                if diff < min_diff:
                                    min_diff = diff
                                    closest_idx = i
                            proposed_end_idx = closest_idx
                    
                    for i in range(duration):
                        if start_idx + i < len(time_slots):
                            new_time = time_slots[start_idx + i]
                            # Stop if we've reached or exceeded proposed_end
                            if proposed_end_idx is not None and (start_idx + i) >= proposed_end_idx:
                                break
                            new_end = time_slots[start_idx + i + 1] if (start_idx + i + 1) < len(time_slots) else "21:00"
                            # Ensure end_time doesn't exceed proposed_end
                            if proposed_end and _time_to_minutes(new_end) > _time_to_minutes(proposed_end):
                                new_end = proposed_end
                            new_group_blocks.append({
                                "group_id": group_id,
                                "week_start": week_start,
                                "course_number": course_number_for_move,
                                "day_of_week": proposed_day,
                                "start_time": new_time,
                                "end_time": new_end,
                                "created_by": requester_id
                            })
                
                if new_group_blocks:
                    insert_result = client.table("group_plan_blocks").insert(new_group_blocks).execute()
                    logging.info(f"✅ Created {len(new_group_blocks)} new group_plan_blocks at new location (day={proposed_day}, start={proposed_start})")
                else:
                    logging.error(f"❌ Failed to create group_plan_blocks: proposed_start={proposed_start}, proposed_duration={proposed_duration}")
                
                # Step 3: Update all member's weekly_plan_blocks
                for mid in member_ids:
                    # Get plan_id for this member
                    member_plan = client.table("weekly_plans").select("id").eq("user_id", mid).eq("week_start", week_start).limit(1).execute()
                    if member_plan.data:
                        plan_id = member_plan.data[0]["id"]
                        
                        # Delete old blocks at original location
                        # IMPORTANT: Delete ONLY blocks at the original location (original_day)
                        # Do NOT delete blocks at the new location (proposed_day) even if they overlap
                        if original_day is not None and original_start:
                            original_start_minutes = _time_to_minutes(original_start)
                            original_end_minutes = _time_to_minutes(original_end) if original_end else original_start_minutes + (original_duration * 60)
                            
                            # Get all blocks for this member/day/course at ORIGINAL location only
                            all_member_blocks = client.table("weekly_plan_blocks").select("id, start_time, end_time, day_of_week").eq("plan_id", plan_id).eq("work_type", "group").eq("course_number", course_number_for_move).eq("day_of_week", original_day).execute()
                            
                            # Calculate proposed time range for comparison
                            proposed_start_minutes = _time_to_minutes(proposed_start) if proposed_start else None
                            proposed_end_minutes = _time_to_minutes(proposed_end) if proposed_end else (proposed_start_minutes + ((proposed_duration if proposed_duration else 1) * 60) if proposed_start_minutes else None)
                            
                            blocks_to_delete = []
                            for block in (all_member_blocks.data or []):
                                # Only delete blocks at the original day
                                if block.get("day_of_week") != original_day:
                                    continue
                                
                                block_start_minutes = _time_to_minutes(block.get("start_time", "00:00"))
                                block_end_minutes = _time_to_minutes(block.get("end_time", "00:00"))
                                
                                # Check if this block overlaps with the original time range
                                overlaps_original = block_start_minutes < original_end_minutes and block_end_minutes > original_start_minutes
                                
                                # If same day and new location overlaps, don't delete (it's the new block location)
                                if original_day == proposed_day and proposed_start_minutes is not None and proposed_end_minutes is not None:
                                    overlaps_new = block_start_minutes < proposed_end_minutes and block_end_minutes > proposed_start_minutes
                                    # If block overlaps with new location, it's part of the new blocks, don't delete
                                    if overlaps_new:
                                        continue
                                
                                if overlaps_original:
                                    blocks_to_delete.append(block["id"])
                            
                            # Delete all overlapping blocks at original location
                            if blocks_to_delete:
                                for block_id in blocks_to_delete:
                                    client.table("weekly_plan_blocks").delete().eq("id", block_id).execute()
                                logging.info(f"✅ Deleted {len(blocks_to_delete)} weekly_plan_blocks for member {mid} at original location (day={original_day}, time={original_start}-{original_end})")
                            else:
                                logging.warning(f"⚠️ No blocks found to delete at original location {original_start} for member {mid}")
                        
                        # Create new blocks at new location
                        # IMPORTANT: First check if there are existing blocks at the new location and delete them
                        # This prevents duplicates if the request is processed multiple times
                        if proposed_day is not None and proposed_start:
                            proposed_start_minutes = _time_to_minutes(proposed_start)
                            proposed_end_minutes = _time_to_minutes(proposed_end) if proposed_end else proposed_start_minutes + ((proposed_duration if proposed_duration else 1) * 60)
                            
                            # Check for existing blocks at new location (same course, same day, overlapping time)
                            existing_at_new_location = client.table("weekly_plan_blocks").select("id, start_time, end_time").eq("plan_id", plan_id).eq("work_type", "group").eq("course_number", course_number_for_move).eq("day_of_week", proposed_day).execute()
                            
                            blocks_to_delete_at_new = []
                            for block in (existing_at_new_location.data or []):
                                block_start_minutes = _time_to_minutes(block.get("start_time", "00:00"))
                                block_end_minutes = _time_to_minutes(block.get("end_time", "00:00"))
                                
                                # Check if this block overlaps with the proposed time range
                                if block_start_minutes < proposed_end_minutes and block_end_minutes > proposed_start_minutes:
                                    blocks_to_delete_at_new.append(block["id"])
                            
                            # Delete any existing blocks at new location (prevents duplicates)
                            if blocks_to_delete_at_new:
                                for block_id in blocks_to_delete_at_new:
                                    client.table("weekly_plan_blocks").delete().eq("id", block_id).execute()
                                logging.info(f"✅ Deleted {len(blocks_to_delete_at_new)} existing blocks at new location for member {mid} (preventing duplicates)")
                        
                        new_member_blocks = []
                        if proposed_start:
                            if proposed_start in time_slots:
                                start_idx = time_slots.index(proposed_start)
                            else:
                                # Find the closest time slot
                                proposed_minutes = _time_to_minutes(proposed_start)
                                closest_idx = 0
                                min_diff = abs(_time_to_minutes(time_slots[0]) - proposed_minutes)
                                for i, slot in enumerate(time_slots):
                                    diff = abs(_time_to_minutes(slot) - proposed_minutes)
                                    if diff < min_diff:
                                        min_diff = diff
                                        closest_idx = i
                                start_idx = closest_idx
                            
                            # Use calculated proposed_duration (should be set above)
                            duration = proposed_duration if proposed_duration else original_duration
                            logging.info(f"📊 Creating {duration} blocks for member {mid} at new location (proposed_duration={proposed_duration}, original_duration={original_duration}, proposed_end={proposed_end})")
                            
                            # Calculate the end time slot index to ensure we don't exceed proposed_end
                            proposed_end_idx = None
                            if proposed_end:
                                if proposed_end in time_slots:
                                    proposed_end_idx = time_slots.index(proposed_end)
                                else:
                                    # Find closest time slot
                                    proposed_end_minutes = _time_to_minutes(proposed_end)
                                    closest_idx = 0
                                    min_diff = abs(_time_to_minutes(time_slots[0]) - proposed_end_minutes)
                                    for j, slot in enumerate(time_slots):
                                        diff = abs(_time_to_minutes(slot) - proposed_end_minutes)
                                        if diff < min_diff:
                                            min_diff = diff
                                            closest_idx = j
                                    proposed_end_idx = closest_idx
                            
                            for i in range(duration):
                                if start_idx + i < len(time_slots):
                                    new_time = time_slots[start_idx + i]
                                    # Stop if we've reached or exceeded proposed_end
                                    if proposed_end_idx is not None and (start_idx + i) >= proposed_end_idx:
                                        break
                                    new_end = time_slots[start_idx + i + 1] if (start_idx + i + 1) < len(time_slots) else "21:00"
                                    # Ensure end_time doesn't exceed proposed_end
                                    if proposed_end and _time_to_minutes(new_end) > _time_to_minutes(proposed_end):
                                        new_end = proposed_end
                                    new_member_blocks.append({
                                        "plan_id": plan_id,
                                        "user_id": mid,
                                        "course_number": course_number_for_move,
                                        "course_name": course_name_for_move,
                                        "work_type": "group",
                                        "day_of_week": proposed_day,
                                        "start_time": new_time,
                                        "end_time": new_end,
                                        "source": "group"
                                    })
                        
                        if new_member_blocks:
                            insert_result = client.table("weekly_plan_blocks").insert(new_member_blocks).execute()
                            logging.info(f"✅ Created {len(new_member_blocks)} new weekly_plan_blocks for member {mid} at new location (day={proposed_day}, start={proposed_start})")
                        else:
                            logging.error(f"❌ Failed to create weekly_plan_blocks for member {mid}: proposed_start={proposed_start}, proposed_duration={proposed_duration}")
                    else:
                        logging.warning(f"⚠️ No plan found for member {mid} for week {week_start}")
            
            # Update group preferences and course_time_preferences for move/add new block
            # Check if this is a new block (original_duration = 0 and original_day is None)
            is_new_block_move = (original_duration == 0 and original_day is None)
            
            # ALWAYS update group preferences with new hours (even without explanation)
            # This affects future schedule generation
            try:
                # Get or create group preferences
                gp = client.table("group_preferences").select("*").eq("group_id", group_id).limit(1).execute()
                
                if gp.data:
                    current_history = gp.data[0].get("hours_change_history", []) or []
                    if not isinstance(current_history, list):
                        current_history = []
                    
                    # Add to history
                    history_entry = {
                        "date": datetime.now().isoformat(),
                        "old_hours": original_duration,
                        "new_hours": proposed_duration,
                        "approved_by": member_ids
                    }
                    if hours_explanation:
                        history_entry["reason"] = hours_explanation
                    current_history.append(history_entry)
                    
                    current_hours = gp.data[0].get("preferred_hours_per_week", 4)
                    
                    # If this is a new block AND there are no existing group hours (current_hours = 0),
                    # use 100% of the new hours instead of weighted average
                    if is_new_block_move and current_hours == 0:
                        weighted_hours = proposed_duration
                        logging.info(f"✅ Updated group_preferences: {current_hours}h -> {weighted_hours}h (100% - first group block)")
                    else:
                        # Calculate weighted average: 80% existing, 20% new
                        weighted_hours = int(0.8 * current_hours + 0.2 * proposed_duration)
                        logging.info(f"✅ Updated group_preferences: {current_hours}h -> {weighted_hours}h (weighted average: 80% existing, 20% new)")
                    
                    client.table("group_preferences").update({
                        "preferred_hours_per_week": weighted_hours,
                        "hours_change_history": current_history,
                        "updated_at": datetime.now().isoformat()
                    }).eq("group_id", group_id).execute()
                else:
                    # Create new group preferences
                    history_entry = {
                        "date": datetime.now().isoformat(),
                        "old_hours": original_duration,
                        "new_hours": proposed_duration,
                        "approved_by": member_ids
                    }
                    if hours_explanation:
                        history_entry["reason"] = hours_explanation
                    
                    # For new group preferences, use proposed_duration directly (no existing value to average)
                    # This is always 100% since there are no existing preferences
                    client.table("group_preferences").insert({
                        "group_id": group_id,
                        "preferred_hours_per_week": proposed_duration,
                        "hours_change_history": [history_entry]
                    }).execute()
                    
                    logging.info(f"✅ Created group_preferences: {proposed_duration}h per week (new group - 100%)")
                    weighted_hours = proposed_duration
                
                # IMPORTANT: Also update course_time_preferences.group_hours_per_week for all members
                # This ensures consistency between group_preferences and course_time_preferences
                try:
                    # Get course_number from group
                    group_info = client.table("study_groups").select("course_id").eq("id", group_id).limit(1).execute()
                    if group_info.data:
                        course_number = group_info.data[0].get("course_id")
                        
                        # Update course_time_preferences for all members
                        for member_id in member_ids:
                            try:
                                # Get current course_time_preferences for this member
                                member_pref_result = client.table("course_time_preferences").select("personal_hours_per_week, group_hours_per_week").eq("user_id", member_id).eq("course_number", course_number).limit(1).execute()
                                
                                if member_pref_result.data:
                                    # Convert to float to handle decimal values
                                    current_personal_hours = float(member_pref_result.data[0].get("personal_hours_per_week", 0))
                                    current_group_hours = float(member_pref_result.data[0].get("group_hours_per_week", 0))
                                    
                                    # If this is a new block AND there are no existing group hours (current_group_hours = 0),
                                    # use 100% of the new hours instead of weighted average
                                    if is_new_block_move and current_group_hours == 0:
                                        new_group_hours = float(weighted_hours)
                                        logging.info(f"✅ Updated course_time_preferences for member {member_id}, course {course_number}: group_hours={new_group_hours}h (100% - first group block)")
                                    else:
                                        # Apply weighted average: 80% existing, 20% new group hours (keep as decimal)
                                        new_group_hours = round(0.8 * current_group_hours + 0.2 * float(weighted_hours), 2)
                                        logging.info(f"✅ Updated course_time_preferences for member {member_id}, course {course_number}: group_hours={new_group_hours}h (weighted average)")
                                    
                                    # Update with weighted average or 100%
                                    client.table("course_time_preferences").update({
                                        "group_hours_per_week": new_group_hours
                                    }).eq("user_id", member_id).eq("course_number", course_number).execute()
                                else:
                                    # Create new entry with default personal hours and new group hours
                                    # Get course credit_points to calculate default personal hours
                                    course_result = client.table("courses").select("credit_points").eq("user_id", member_id).eq("course_number", course_number).limit(1).execute()
                                    credit_points = course_result.data[0].get("credit_points") if course_result.data else 3
                                    total_hours = credit_points * 3
                                    default_personal_hours = max(1, int(total_hours * 0.5))
                                    
                                    client.table("course_time_preferences").insert({
                                        "user_id": member_id,
                                        "course_number": course_number,
                                        "personal_hours_per_week": default_personal_hours,
                                        "group_hours_per_week": weighted_hours
                                    }).execute()
                                    
                                    logging.info(f"✅ Created course_time_preferences for member {member_id}, course {course_number}: personal={default_personal_hours}h, group={weighted_hours}h")
                            except Exception as member_err:
                                logging.warning(f"⚠️ Failed to update course_time_preferences for member {member_id}: {member_err}")
                except Exception as course_pref_err:
                    logging.warning(f"⚠️ Failed to update course_time_preferences for group members: {course_pref_err}")
                
                logging.info(f"✅ Updated group preferences for group {group_id}: {original_duration}h -> {proposed_duration}h per week")
            except Exception as gp_err:
                logging.error(f"Failed to update group preferences: {gp_err}")
            
            # Mark request as approved
            client.table("group_meeting_change_requests").update({
                "status": "approved",
                "resolved_at": datetime.now().isoformat()
            }).eq("id", request_id).execute()
            
            # Delete all existing notifications about this change request for all members
            request_link_pattern = f"/schedule?change_request={request_id}"
            for mid in member_ids:
                try:
                    # Delete notifications of type "group_change_request" that link to this request
                    existing_notifications = client.table("notifications").select("id, link").eq("user_id", mid).eq("type", "group_change_request").execute()
                    for notif in (existing_notifications.data or []):
                        # Check if the link contains this request_id
                        notif_link = notif.get("link", "")
                        if request_id in notif_link:
                            client.table("notifications").delete().eq("id", notif["id"]).execute()
                            logging.info(f"🗑️ Deleted notification {notif['id']} for user {mid} (approved request {request_id})")
                except Exception as del_err:
                    logging.warning(f"Failed to delete existing notifications for member {mid}: {del_err}")
            
            # Notify all members
            group_result = client.table("study_groups").select("group_name").eq("id", group_id).limit(1).execute()
            group_name = group_result.data[0].get("group_name", "Group") if group_result.data else "Group"
            
            change_type_msg = "משך המפגש" if request_type == "resize" else "זמן המפגש"
            
            for mid in member_ids:
                try:
                    client.table("notifications").insert({
                        "user_id": mid,
                        "type": "group_change_approved",
                        "title": f"שינוי אושר: {group_name}",
                        "message": f"כל חברי הקבוצה אישרו את השינוי. {change_type_msg} עודכן.",
                        "link": f"/schedule?week={week_start}",
                        "read": False
                    }).execute()
                except Exception as notif_err:
                    logging.error(f"Failed to notify member {mid}: {notif_err}")
            
            logging.info(f"Change request {request_id} approved and applied!")
            
            return JSONResponse(content={
                "message": "All members approved! Change has been applied.",
                "status": "approved"
            })
        else:
            # Calculate approval status
            approved_count = len([a for a in approval_map.values() if a])
            total_needed = len(members_needing_approval)
            logging.info(f"📝 User {user_id} approved request {request_id}. Waiting for others... ({approved_count}/{total_needed})")
            return JSONResponse(content={
                "message": f"Your approval recorded. Waiting for other members ({approved_count}/{total_needed} approved).",
                "status": "pending",
                "approved_count": approved_count,
                "total_members": total_needed,
                "members_needing_approval": members_needing_approval
            })
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error approving change request: {e}")
        import traceback
        logging.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/schedule/group-change-request/{request_id}/reject")
async def reject_group_change_request(
    request_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Reject a group meeting change request.
    One rejection cancels the entire request.
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Get the request
        request_result = client.table("group_meeting_change_requests").select("*").eq("id", request_id).limit(1).execute()
        if not request_result.data:
            raise HTTPException(status_code=404, detail="Change request not found")
        
        change_request = request_result.data[0]
        
        if change_request["status"] != "pending":
            raise HTTPException(status_code=400, detail=f"Request is already {change_request['status']}")
        
        # Verify user is member of this group
        group_id = change_request["group_id"]
        member_check = client.table("group_members").select("id").eq("group_id", group_id).eq("user_id", user_id).eq("status", "approved").execute()
        if not member_check.data:
            raise HTTPException(status_code=403, detail="Not a member of this group")
        
        # Record the rejection
        try:
            client.table("group_change_approvals").insert({
                "request_id": request_id,
                "user_id": user_id,
                "approved": False
            }).execute()
        except Exception:
            client.table("group_change_approvals").update({
                "approved": False,
                "responded_at": "NOW()"
            }).eq("request_id", request_id).eq("user_id", user_id).execute()
        
        # Mark request as rejected
        client.table("group_meeting_change_requests").update({
            "status": "rejected",
            "resolved_at": "NOW()"
        }).eq("id", request_id).execute()
        
        # Get all members to delete their notifications and send new ones
        all_members = client.table("group_members").select("user_id").eq("group_id", group_id).eq("status", "approved").execute()
        member_ids = [m["user_id"] for m in (all_members.data or [])]
        
        # Delete all existing notifications about this change request for all members
        # The link contains the request_id: "/schedule?change_request={request_id}"
        request_link_pattern = f"/schedule?change_request={request_id}"
        for mid in member_ids:
            try:
                # Delete notifications of type "group_change_request" that link to this request
                existing_notifications = client.table("notifications").select("id").eq("user_id", mid).eq("type", "group_change_request").execute()
                for notif in (existing_notifications.data or []):
                    # Check if the link contains this request_id
                    notif_link = notif.get("link", "")
                    if request_id in notif_link:
                        client.table("notifications").delete().eq("id", notif["id"]).execute()
                        logging.info(f"🗑️ Deleted notification {notif['id']} for user {mid} (rejected request {request_id})")
            except Exception as del_err:
                logging.warning(f"Failed to delete existing notifications for member {mid}: {del_err}")
        
        group_result = client.table("study_groups").select("group_name").eq("id", group_id).limit(1).execute()
        group_name = group_result.data[0].get("group_name", "Group") if group_result.data else "Group"
        
        rejector_result = client.table("user_profiles").select("name").eq("id", user_id).limit(1).execute()
        rejector_name = rejector_result.data[0].get("name", "A member") if rejector_result.data else "A member"
        
        for mid in member_ids:
            try:
                client.table("notifications").insert({
                    "user_id": mid,
                    "type": "group_change_rejected",
                    "title": f"שינוי מפגש נדחה: {group_name}",
                    "message": f"{rejector_name} דחה את הבקשה לשנות את מועד המפגש.",
                    "link": "/schedule",
                    "read": False
                }).execute()
            except Exception as notif_err:
                logging.error(f"Failed to notify member {mid}: {notif_err}")
        
        logging.info(f"❌ User {user_id} rejected change request {request_id}")
        
        return JSONResponse(content={
            "message": "Change request rejected.",
            "status": "rejected"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error rejecting change request: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/schedule/group-change-request/{request_id}")
async def get_group_change_request(
    request_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get details of a specific group change request.
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Get the request
        request_result = client.table("group_meeting_change_requests").select("*").eq("id", request_id).limit(1).execute()
        if not request_result.data:
            raise HTTPException(status_code=404, detail="Change request not found")
        
        change_request = request_result.data[0]
        group_id = change_request["group_id"]
        
        # Verify user is member of this group
        member_check = client.table("group_members").select("id").eq("group_id", group_id).eq("user_id", user_id).eq("status", "approved").execute()
        if not member_check.data:
            raise HTTPException(status_code=403, detail="Not a member of this group")
        
        # Get group info
        group_result = client.table("study_groups").select("group_name, course_name, course_id").eq("id", group_id).limit(1).execute()
        group_info = group_result.data[0] if group_result.data else {}
        
        # Get approvals status
        approvals = client.table("group_change_approvals").select("user_id, approved").eq("request_id", request_id).execute()
        
        return JSONResponse(content={
            "request": change_request,
            "group": group_info,
            "approvals": approvals.data or []
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting change request: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/schedule/group-change-requests/pending")
async def get_pending_change_requests(current_user: dict = Depends(get_current_user)):
    """
    Get all pending change requests for groups the user is in.
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Get user's groups
        user_groups = client.table("group_members").select("group_id").eq("user_id", user_id).eq("status", "approved").execute()
        group_ids = [g["group_id"] for g in (user_groups.data or [])]
        
        if not group_ids:
            return JSONResponse(content={"requests": []})
        
        # Get pending requests for these groups
        requests = client.table("group_meeting_change_requests").select("*").in_("group_id", group_ids).eq("status", "pending").execute()
        
        # Batch fetch group names and requester names for performance
        group_ids = list(set([req["group_id"] for req in (requests.data or [])]))
        requester_ids = list(set([req["requested_by"] for req in (requests.data or [])]))
        
        groups_map = {}
        if group_ids:
            groups_result = client.table("study_groups").select("id, group_name").in_("id", group_ids).execute()
            groups_map = {g["id"]: g.get("group_name", "Group") for g in (groups_result.data or [])}
        
        requesters_map = {}
        if requester_ids:
            requesters_result = client.table("user_profiles").select("id, name").in_("id", requester_ids).execute()
            requesters_map = {r["id"]: r.get("name", "Someone") for r in (requesters_result.data or [])}
        
        # Batch fetch approvals for performance
        request_ids = [req["id"] for req in (requests.data or [])]
        approvals_map = {}
        if request_ids:
            approvals_result = client.table("group_change_approvals").select("request_id, user_id, approved").in_("request_id", request_ids).eq("user_id", user_id).execute()
            approvals_map = {a["request_id"]: a["approved"] for a in (approvals_result.data or [])}
        
        # Enrich with group names and approval status
        enriched_requests = []
        for req in (requests.data or []):
            group_name = groups_map.get(req["group_id"], "Group")
            requester_name = requesters_map.get(req["requested_by"], "Someone")
            user_response = approvals_map.get(req["id"])
            is_requester = (user_id == req.get("requested_by"))
            
            enriched_requests.append({
                **req,
                "group_name": group_name,
                "requester_name": requester_name,
                "user_has_responded": user_response is not None and not is_requester,
                "user_approved": user_response if user_response is not None else None,
                "is_requester": is_requester
            })
        
        return JSONResponse(content={"requests": enriched_requests})
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting pending change requests: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/schedule/group-change-requests/by-group/{group_id}")
async def get_pending_change_requests_by_group(
    group_id: str,
    week_start: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Get pending change requests for a specific group.
    Useful for displaying pending requests when clicking on a group block.
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Verify user is member of this group
        member_check = client.table("group_members").select("id").eq("group_id", group_id).eq("user_id", user_id).eq("status", "approved").execute()
        if not member_check.data:
            raise HTTPException(status_code=403, detail="Not a member of this group")
        
        # Build query
        query = client.table("group_meeting_change_requests").select("*").eq("group_id", group_id).eq("status", "pending")
        if week_start:
            query = query.eq("week_start", week_start)
        
        requests = query.execute()
        
        # Get all members once (outside loop for performance)
        all_members = client.table("group_members").select("user_id").eq("group_id", group_id).eq("status", "approved").execute()
        member_ids = [m["user_id"] for m in (all_members.data or [])]
        
        # Get all approvals for all requests at once (batch query for performance)
        request_ids = [req["id"] for req in (requests.data or [])]
        all_approvals = {}
        if request_ids:
            approvals_result = client.table("group_change_approvals").select("request_id, user_id, approved").in_("request_id", request_ids).execute()
            for approval in (approvals_result.data or []):
                req_id = approval["request_id"]
                if req_id not in all_approvals:
                    all_approvals[req_id] = {}
                all_approvals[req_id][approval["user_id"]] = approval["approved"]
        
        # Enrich with approval status
        enriched_requests = []
        for req in (requests.data or []):
            requester_id = req.get("requested_by")
            members_needing_approval = [mid for mid in member_ids if mid != requester_id]
            
            # Get approvals for this request
            approval_map = all_approvals.get(req["id"], {})
            
            # Check if current user is the requester
            is_requester = (user_id == requester_id)
            
            # Check if current user has responded (only if not requester)
            user_response = None if is_requester else approval_map.get(user_id)
            
            approved_count = len([a for a in approval_map.values() if a])
            total_needed = len(members_needing_approval)
            
            enriched_requests.append({
                **req,
                "approved_count": approved_count,
                "total_members": total_needed,
                "user_has_responded": user_response is not None,
                "user_approved": user_response if user_response is not None else None,
                "is_requester": is_requester  # Add flag to indicate if current user is the requester
            })
        
        return JSONResponse(content={"requests": enriched_requests})
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting pending change requests by group: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# Study Groups endpoints
@app.post("/api/groups/create")
async def create_study_group(
    request: Request,
    group_data: StudyGroupCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new study group and invite members"""
    try:
        user_id = current_user.get('sub')
        user_email = current_user.get('email')
        
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        logging.info(f"Creating study group: {group_data.group_name} for course {group_data.course_name}")
        
        # Use service_role client if available (bypasses RLS, safe since we've already authenticated)
        # This is the recommended approach
        if supabase_admin:
            client = supabase_admin
            is_admin = True
            logging.info(f"   ✅ Using admin client (bypasses RLS)")
        else:
            # Fallback: use anon client (will fail if RLS policies don't allow)
            # NOTE: This requires SUPABASE_SERVICE_ROLE_KEY to be set in .env
            client = supabase
            is_admin = False
            logging.error("   ❌ ERROR: SUPABASE_SERVICE_ROLE_KEY not set!")
            logging.error("   ❌ Please add SUPABASE_SERVICE_ROLE_KEY to your .env file")
            logging.error("   ❌ Get it from: Supabase Dashboard > Settings > API > service_role key")
            raise HTTPException(
                status_code=500,
                detail="Server configuration error: SUPABASE_SERVICE_ROLE_KEY is required. Please contact the administrator."
            )
        
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        logging.info(f"   User ID: {user_id}, User email: {user_email}")
        
        # FIRST: Filter out the current user's email (can't invite yourself)
        filtered_emails = []
        self_invite_attempted = False
        
        if not user_email:
            logging.error("   ❌ User email is not available - cannot filter self-invite")
            raise HTTPException(status_code=500, detail="User email not available")
        
        user_email_lower = user_email.strip().lower()
        logging.info(f"   Current user email (normalized): {user_email_lower}")
        
        if group_data.invite_emails:
            logging.info(f"   Checking {len(group_data.invite_emails)} emails against current user email...")
            for email in group_data.invite_emails:
                if not email or not email.strip():
                    continue
                email_normalized = email.strip().lower()
                logging.info(f"   Comparing: '{email_normalized}' == '{user_email_lower}'? {email_normalized == user_email_lower}")
                
                # Skip if it's the current user's email
                if email_normalized == user_email_lower:
                    logging.warning(f"   ⚠️ Skipping {email_normalized} - cannot invite yourself")
                    self_invite_attempted = True
                    continue
                filtered_emails.append(email_normalized)
                logging.info(f"   ✅ Added {email_normalized} to filtered list")
        
        logging.info(f"   After filtering: {len(filtered_emails)} valid emails (removed {len(group_data.invite_emails) - len(filtered_emails)} self-invites)")
        
        # FIRST: Validate all emails before creating the group
        # Check if all emails are registered users
        valid_emails = []
        unregistered_emails = []
        
        if filtered_emails:
            logging.info(f"   Validating {len(filtered_emails)} email addresses (after filtering self-invite)...")
            
            # Get all registered users once
            all_registered_users = {}
            if supabase_admin:
                try:
                    auth_users = supabase_admin.auth.admin.list_users()
                    # Handle different response formats
                    if hasattr(auth_users, 'users'):
                        for u in auth_users.users:
                            if hasattr(u, 'email') and u.email:
                                all_registered_users[u.email.lower()] = u
                    elif isinstance(auth_users, list):
                        for u in auth_users:
                            if hasattr(u, 'email') and u.email:
                                all_registered_users[u.email.lower()] = u
                    else:
                        # Try to iterate directly
                        for u in auth_users:
                            if hasattr(u, 'email') and u.email:
                                all_registered_users[u.email.lower()] = u
                    logging.info(f"   Found {len(all_registered_users)} registered users in system")
                except Exception as list_error:
                    logging.error(f"Error listing users: {list_error}")
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to validate user emails. Please try again."
                    )
            
            # Validate each email
            for email in filtered_emails:
                if not email or not email.strip():
                    continue
                    
                email = email.strip().lower()
                
                # Check if user exists
                if email in all_registered_users:
                    valid_emails.append({
                        "email": email,
                        "user": all_registered_users[email]
                    })
                    logging.info(f"   ✅ {email} is registered")
                else:
                    unregistered_emails.append(email)
                    logging.warning(f"   ❌ {email} is NOT registered")
        
        # If there are unregistered emails, reject the request
        if unregistered_emails:
            error_msg = f"The following emails are not registered in the system: {', '.join(unregistered_emails)}. Only registered users can be invited to groups."
            logging.error(f"   ❌ {error_msg}")
            raise HTTPException(
                status_code=400,
                detail=error_msg
            )
        
        # Allow group creation without invitees (user can invite later)
        # Only reject if user tried to invite themselves and no other valid emails
        if not valid_emails:
            if self_invite_attempted:
                logging.warning(f"   ⚠️ User tried to invite themselves only - allowing group creation without invitees")
            else:
                logging.info(f"   ℹ️ No invitees provided - group will be created without initial members")
        
        # Get creator's current semester and year to validate invitees
        creator_profile = client.table("user_profiles").select("current_semester, current_year").eq("id", user_id).execute()
        creator_semester = None
        creator_year = None
        if creator_profile.data and len(creator_profile.data) > 0:
            creator_semester = creator_profile.data[0].get("current_semester")
            creator_year = creator_profile.data[0].get("current_year")
            logging.info(f"   Creator's semester: {creator_semester}, year: {creator_year}")
        
        # Validate that each invitee is enrolled in the course for the selected semester
        course_number = group_data.course_id  # course_id is actually course_number
        eligible_emails = []
        ineligible_emails = []
        
        # Helper function to extract semester season (e.g., "חורף" from "חורף תשפ"ו")
        def extract_semester_season(semester_str):
            if not semester_str:
                return None
            semester_str = str(semester_str).strip()
            # Common Hebrew semester names
            if "חורף" in semester_str or "winter" in semester_str.lower():
                return "חורף"
            elif "אביב" in semester_str or "spring" in semester_str.lower():
                return "אביב"
            elif "קיץ" in semester_str or "summer" in semester_str.lower():
                return "קיץ"
            return semester_str  # Return as-is if no match
        
        if creator_semester and creator_year and course_number:
            creator_semester_season = extract_semester_season(creator_semester)
            logging.info(f"   Validating invitees for course {course_number} in semester {creator_semester} (season: {creator_semester_season}) year {creator_year}")
            
            for email_data in valid_emails:
                email = email_data["email"]
                invitee_user_id = email_data["user"].id
                
                # Check if invitee has this course in the same semester/year
                invitee_courses = client.table("courses").select("*").eq("user_id", invitee_user_id).eq("course_number", course_number).execute()
                
                has_course_in_semester = False
                if invitee_courses.data:
                    logging.info(f"   🔍 Checking {len(invitee_courses.data)} courses for {email}")
                    for course in invitee_courses.data:
                        course_semester = course.get("semester")
                        course_year = course.get("year")
                        course_semester_season = extract_semester_season(course_semester) if course_semester else None
                        
                        # Match by semester season (not exact string) and year
                        semester_matches = course_semester_season == creator_semester_season if course_semester_season and creator_semester_season else False
                        year_matches = not creator_year or not course_year or course_year == creator_year
                        
                        logging.info(f"   🔍 Course: semester='{course_semester}' (season: {course_semester_season}), year={course_year}")
                        logging.info(f"   🔍 Match: semester={semester_matches}, year={year_matches}")
                        
                        if semester_matches and year_matches:
                            has_course_in_semester = True
                            logging.info(f"   ✅ {email} is enrolled in course {course_number} for {creator_semester_season} {creator_year}")
                            break
                else:
                    logging.warning(f"   ⚠️ {email} has no courses with course_number={course_number}")
                
                if has_course_in_semester:
                    eligible_emails.append(email_data)
                else:
                    ineligible_emails.append(email)
                    logging.warning(f"   ❌ {email} is NOT enrolled in course {course_number} for {creator_semester_season} {creator_year}")
        else:
            # If creator doesn't have semester/year set, allow all (backward compatibility)
            logging.warning(f"   ⚠️ Creator's semester/year not set - allowing all invitees (backward compatibility)")
            eligible_emails = valid_emails
        
        # If there are ineligible emails, reject them
        if ineligible_emails:
            creator_semester_season = extract_semester_season(creator_semester) if creator_semester else None
            error_msg = f"The following users are not enrolled in course {group_data.course_name} (course number: {course_number}) for the selected semester ({creator_semester_season or creator_semester} {creator_year}): {', '.join(ineligible_emails)}. Please make sure they have this course in their courses list for the same semester and year."
            logging.error(f"   ❌ {error_msg}")
            logging.error(f"   💡 Debug: Creator semester='{creator_semester}' (season: {creator_semester_season}), year={creator_year}")
            raise HTTPException(
                status_code=400,
                detail=error_msg
            )
        
        # If no eligible emails after validation AND there were invitees, reject
        # But allow group creation without invitees (user can invite later)
        if not eligible_emails and valid_emails:
            error_msg = "None of the invited users are enrolled in this course for the selected semester."
            logging.error(f"   ❌ {error_msg}")
            raise HTTPException(
                status_code=400,
                detail=error_msg
            )
        
        # If no invitees at all, that's fine - group can be created without members
        if not valid_emails:
            logging.info(f"   ℹ️ No invitees provided - group will be created without initial members")
        
        # NOW create the group (only if all emails are valid and eligible)
        logging.info(f"   ✅ All {len(eligible_emails)} invitees are eligible. Creating group...")
        group_result = client.table("study_groups").insert({
            "course_id": group_data.course_id,
            "course_name": group_data.course_name,
            "group_name": group_data.group_name,
            "description": group_data.description,
            "created_by": user_id
        }).execute()
        
        if not group_result.data:
            raise HTTPException(status_code=500, detail="Failed to create group")
        
        group = group_result.data[0]
        group_id = group['id']
        
        # Create group_preferences with default values
        try:
            client.table("group_preferences").insert({
                "group_id": group_id,
                "preferred_hours_per_week": 4,  # Default 4 hours per week
                "hours_change_history": []
            }).execute()
            logging.info(f"✅ Created group_preferences for group {group_id}")
        except Exception as gp_err:
            # If preferences already exist, that's okay
            logging.warning(f"⚠️ Could not create group_preferences (may already exist): {gp_err}")
        
        # Add creator as an approved member of the group
        try:
            creator_member_data = {
                "group_id": group_id,
                "user_id": user_id,
                "status": "approved"
            }
            client.table("group_members").insert(creator_member_data).execute()
            logging.info(f"✅ Added creator {user_id} as approved member of group {group_id}")
        except Exception as creator_member_error:
            # Check if already exists (might happen if retrying)
            existing = client.table("group_members").select("*").eq("group_id", group_id).eq("user_id", user_id).execute()
            if not existing.data:
                logging.error(f"❌ Failed to add creator as member: {creator_member_error}")
                # Don't fail the whole operation, but log the error
            else:
                logging.info(f"ℹ️ Creator already exists as member")
        
        # Create invitations for each ELIGIBLE email
        invitations_created = []
        invitations_failed = []
        
        for email_data in eligible_emails:
            email = email_data["email"]
            user_check = email_data["user"]
            
            try:
                # Create invitation (user is already validated and eligible)
                invitation_data = {
                    "group_id": group_id,
                    "inviter_id": user_id,
                    "invitee_email": email,
                    "invitee_user_id": user_check.id,  # Always set if user exists
                    "status": "pending"
                }
                
                # Create notification immediately for registered users
                try:
                    client.table("notifications").insert({
                        "user_id": user_check.id,
                        "type": "group_invitation",
                        "title": f"הזמנה לקבוצת לימוד: {group_data.group_name}",
                        "message": f"{user_email} הזמין אותך להצטרף לקבוצת לימוד בקורס {group_data.course_name}",
                        "link": f"/my-courses?group={group_id}",
                        "read": False
                    }).execute()
                except Exception as notif_error:
                    logging.warning(f"Failed to create notification for {email}: {notif_error}")
                
                invitation_result = client.table("group_invitations").insert(invitation_data).execute()
                
                if invitation_result.data:
                    invitation_id = invitation_result.data[0]['id']
                    invitations_created.append(email)
                    logging.info(f"✅ Created invitation for registered user: {email}")
                    
                    # Update notification with invitation_id if it was created
                    try:
                        client.table("notifications").update({
                            "link": f"/my-courses?group={group_id}&invitation={invitation_id}"
                        }).eq("user_id", user_check.id).eq("type", "group_invitation").eq("link", f"/my-courses?group={group_id}").order("created_at", desc=True).limit(1).execute()
                    except Exception as update_error:
                        logging.warning(f"Failed to update notification with invitation_id: {update_error}")
                else:
                    invitations_failed.append(email)
                    logging.error(f"❌ Failed to create invitation for {email}")
                    
            except Exception as e:
                logging.error(f"Error inviting {email}: {e}")
                import traceback
                logging.error(f"   Traceback: {traceback.format_exc()}")
                invitations_failed.append(email)
        
        result = {
            "group": group,
            "invitations_created": invitations_created,
            "invitations_failed": invitations_failed,
            "message": f"Group created successfully. {len(invitations_created)} invitations sent."
        }
        
        # Add info if user tried to invite themselves
        if self_invite_attempted:
            result["info"] = "Note: You cannot invite yourself to a group. Your email was automatically excluded."
        
        if invitations_failed:
            if result.get("info"):
                result["warning"] = f"Some invitations failed: {', '.join(invitations_failed)}"
            else:
                result["warning"] = f"Some invitations failed: {', '.join(invitations_failed)}"
        
        return JSONResponse(content=result)
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error creating study group: {e}")
        import traceback
        logging.error(f"   Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error creating study group: {str(e)}")


@app.get("/api/groups/my-groups")
async def get_my_groups(current_user: dict = Depends(get_current_user)):
    """Get all groups the user is a member of"""
    try:
        print("=" * 60)
        print("[GROUPS API] /api/groups/my-groups endpoint called")
        logging.info("=" * 60)
        logging.info("[GROUPS API] /api/groups/my-groups endpoint called")
        user_id = current_user.get('sub')
        print(f"[GROUPS API] User ID: {user_id}")
        logging.info(f"[GROUPS API] User ID: {user_id}")
        
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        # Use admin client to bypass RLS
        client = supabase_admin if supabase_admin else supabase
        
        # Get groups where user is a member
        members_result = client.table("group_members").select("group_id").eq("user_id", user_id).eq("status", "approved").execute()
        member_group_ids = [m['group_id'] for m in (members_result.data or [])]
        
        # Get groups created by user
        created_groups = client.table("study_groups").select("*").eq("created_by", user_id).execute()
        created_group_ids = [g['id'] for g in (created_groups.data or [])]
        
        # Combine group IDs
        all_group_ids = list(set(member_group_ids + created_group_ids))
        
        # Get all groups
        all_groups = {}
        if all_group_ids:
            groups_result = client.table("study_groups").select("*").in_("id", all_group_ids).execute()
            print(f"[GROUPS API] Found {len(groups_result.data or [])} groups in database")
            logging.info(f"[GROUPS API] Found {len(groups_result.data or [])} groups in database")
            for group in (groups_result.data or []):
                all_groups[group['id']] = group
                group_info = f"   Group from DB: '{group.get('group_name')}' | course_id: '{group.get('course_id')}' (type: {type(group.get('course_id')).__name__}) | course_name: '{group.get('course_name')}'"
                print(group_info)
                logging.info(group_info)
        
        # Get member counts and member details
        # Use admin client to bypass RLS and get all members
        client_to_use = supabase_admin if supabase_admin else supabase
        
        for group_id in all_groups:
            try:
                # Get all members of this group (using admin client to bypass RLS)
                members_result = client_to_use.table("group_members").select("id, user_id, status").eq("group_id", group_id).eq("status", "approved").execute()
                all_groups[group_id]['members_count'] = len(members_result.data or [])
                
                # Get member user details (email/name from auth.users)
                member_user_ids = [m['user_id'] for m in (members_result.data or [])]
                if member_user_ids and supabase_admin:
                    try:
                        # Get user emails from auth.users using admin client
                        members_list = []
                        for member_user_id in member_user_ids:
                            try:
                                user_info = supabase_admin.auth.admin.get_user_by_id(member_user_id)
                                if hasattr(user_info, 'user') and user_info.user:
                                    email = getattr(user_info.user, 'email', None) or getattr(user_info.user, 'user_metadata', {}).get('email', 'Unknown')
                                    members_list.append({
                                        "user_id": member_user_id,
                                        "email": email
                                    })
                            except Exception as user_err:
                                logging.warning(f"Could not get user info for {member_user_id}: {user_err}")
                                members_list.append({
                                    "user_id": member_user_id,
                                    "email": "Unknown"
                                })
                        all_groups[group_id]['members'] = members_list
                    except Exception as members_err:
                        logging.warning(f"Could not get member details: {members_err}")
                        all_groups[group_id]['members'] = []
                else:
                    # If no admin client, just return user_ids
                    all_groups[group_id]['members'] = [{"user_id": uid, "email": "Unknown"} for uid in member_user_ids]
            except Exception as group_err:
                logging.warning(f"Could not get members for group {group_id}: {group_err}")
                all_groups[group_id]['members_count'] = 0
                all_groups[group_id]['members'] = []
        
        # Log all groups with their course_id and course_name for debugging
        groups_list = list(all_groups.values())
        print("=" * 60)
        print(f"[GROUPS API] Returning {len(groups_list)} groups:")
        logging.info(f"[GROUPS API] Returning {len(groups_list)} groups:")
        for group in groups_list:
            group_info = f"   - Group: '{group.get('group_name')}' | course_id: '{group.get('course_id')}' | course_name: '{group.get('course_name')}'"
            print(group_info)
            logging.info(group_info)
        print("=" * 60)
        
        return JSONResponse(content={"groups": groups_list})
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting groups: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting groups: {str(e)}")


@app.get("/api/notifications")
async def get_notifications(current_user: dict = Depends(get_current_user)):
    """Get all notifications for the current user"""
    try:
        user_id = current_user.get('sub')
        
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        client = supabase_admin if supabase_admin else supabase
        notifications_result = client.table("notifications").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(50).execute()
        
        return JSONResponse(content={"notifications": notifications_result.data or []})
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting notifications: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting notifications: {str(e)}")


@app.post("/api/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Mark a notification as read"""
    try:
        user_id = current_user.get('sub')
        
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        client = supabase_admin if supabase_admin else supabase
        result = client.table("notifications").update({"read": True}).eq("id", notification_id).eq("user_id", user_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Notification not found")
        
        return JSONResponse(content={"success": True})
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error marking notification as read: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating notification: {str(e)}")


@app.get("/api/groups/invitations/by-group/{group_id}")
async def get_invitation_by_group(
    group_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get pending invitation for current user by group_id"""
    try:
        user_id = current_user.get('sub')
        
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        # Find pending invitation for this user and group
        # Try by user_id first
        result = supabase.table("group_invitations").select("*").eq("group_id", group_id).eq("invitee_user_id", user_id).eq("status", "pending").order("created_at", desc=True).limit(1).execute()
        
        # If not found, try by email (get user email from auth)
        if not result.data or len(result.data) == 0:
            user_email = current_user.get('email')
            if user_email:
                result = supabase.table("group_invitations").select("*").eq("group_id", group_id).eq("invitee_email", user_email).eq("status", "pending").order("created_at", desc=True).limit(1).execute()
        
        if result.data and len(result.data) > 0:
            return JSONResponse(content={"invitation_id": result.data[0]['id']})
        else:
            # Log for debugging
            logging.warning(f"No invitation found for user {user_id} in group {group_id}")
            raise HTTPException(status_code=404, detail="Invitation not found")
            
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting invitation by group: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting invitation: {str(e)}")


@app.get("/api/groups/invitations/by-notification/{notification_id}")
async def get_invitation_by_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get invitation ID from notification"""
    try:
        user_id = current_user.get('sub')
        user_email = current_user.get('email')
        
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        logging.info(f"🔍 Looking for invitation by notification_id={notification_id}, user_id={user_id}, email={user_email}")
        
        # Get notification
        notif_result = supabase.table("notifications").select("*").eq("id", notification_id).eq("user_id", user_id).execute()
        
        if not notif_result.data or len(notif_result.data) == 0:
            logging.warning(f"❌ Notification not found: notification_id={notification_id}, user_id={user_id}")
            raise HTTPException(status_code=404, detail="Notification not found")
        
        notification = notif_result.data[0]
        link = notification.get('link', '')
        logging.info(f"📋 Found notification: link={link}")
        
        # Try to extract invitation_id from link
        import re
        invitation_match = re.search(r'invitation=([^&]+)', link)
        if invitation_match:
            invitation_id = invitation_match.group(1)
            logging.info(f"✅ Found invitation_id in link: {invitation_id}")
            return JSONResponse(content={"invitation_id": invitation_id})
        
        # If not in link, try to find by group_id
        group_match = re.search(r'group=([^&]+)', link)
        if group_match:
            group_id = group_match.group(1)
            logging.info(f"🔍 Looking for invitation by group_id={group_id}")
            
            # Find invitation by group and user - try user_id first
            result = supabase.table("group_invitations").select("*").eq("group_id", group_id).eq("invitee_user_id", user_id).eq("status", "pending").execute()
            
            logging.info(f"📊 Search by user_id: found {len(result.data) if result.data else 0} invitations")
            
            if not result.data or len(result.data) == 0:
                # Try by email
                if user_email:
                    logging.info(f"🔍 Trying to find by email: {user_email}")
                    result = supabase.table("group_invitations").select("*").eq("group_id", group_id).eq("invitee_email", user_email).eq("status", "pending").execute()
                    logging.info(f"📊 Search by email: found {len(result.data) if result.data else 0} invitations")
            
            # If still not found, try without status filter (maybe it's not pending?)
            if not result.data or len(result.data) == 0:
                logging.info(f"🔍 Trying without status filter")
                result = supabase.table("group_invitations").select("*").eq("group_id", group_id).eq("invitee_user_id", user_id).execute()
                if not result.data or len(result.data) == 0:
                    result = supabase.table("group_invitations").select("*").eq("group_id", group_id).eq("invitee_email", user_email).execute()
                logging.info(f"📊 Search without status: found {len(result.data) if result.data else 0} invitations")
            
            if result.data and len(result.data) > 0:
                # Get the most recent one
                invitation = result.data[0]
                logging.info(f"✅ Found invitation: id={invitation['id']}, status={invitation.get('status')}")
                return JSONResponse(content={"invitation_id": invitation['id']})
        
        logging.warning(f"❌ Invitation not found for notification_id={notification_id}")
        raise HTTPException(status_code=404, detail="Invitation not found")
            
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting invitation by notification: {e}")
        import traceback
        logging.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error getting invitation: {str(e)}")


@app.post("/api/groups/invitations/{invitation_id}/accept")
async def accept_invitation(
    invitation_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Accept a group invitation"""
    try:
        user_id = current_user.get('sub')
        
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        logging.info(f"🔵 Accepting invitation {invitation_id} for user {user_id}")
        
        # Use service_role client if available (bypasses RLS, safe since we've already authenticated)
        if supabase_admin:
            client = supabase_admin
            logging.info(f"   ✅ Using admin client (bypasses RLS)")
        else:
            client = supabase
            logging.warning("   ⚠️ Using anon client - RLS policies must allow this operation")
        
        # Validate invitation_id is not null or empty
        if not invitation_id or invitation_id.strip().lower() in ["null", "none", ""]:
            logging.error(f"❌ Invalid invitation_id: {invitation_id}")
            raise HTTPException(status_code=400, detail="Invalid invitation ID")
        
        # Get invitation (using the selected client)
        invitation_result = client.table("group_invitations").select("*").eq("id", invitation_id).eq("invitee_user_id", user_id).eq("status", "pending").execute()
        
        if not invitation_result.data:
            logging.warning(f"❌ Invitation {invitation_id} not found for user {user_id} or already processed.")
            raise HTTPException(status_code=404, detail="Invitation not found or already processed")
        
        invitation = invitation_result.data[0]
        group_id = invitation.get('group_id')
        inviter_id_raw = invitation.get('inviter_id')
        
        # Normalize inviter_id - handle None, "null", "None", etc.
        # Convert to None if it's any form of null/empty
        inviter_id = None
        if inviter_id_raw is not None:
            inviter_id_str = str(inviter_id_raw).strip()
            inviter_id_lower = inviter_id_str.lower()
            # Only keep if it's a valid non-null value
            if inviter_id_lower and inviter_id_lower not in ["null", "none", ""]:
                inviter_id = inviter_id_str
            else:
                inviter_id = None
                logging.info(f"ℹ️ Normalized inviter_id from '{inviter_id_raw}' to None")
        
        logging.info(f"📋 Invitation data: group_id={group_id} (type: {type(group_id)}), user_id={user_id} (type: {type(user_id)}), inviter_id={inviter_id} (type: {type(inviter_id)})")
        
        # Validate that we have required data
        if not group_id or group_id is None:
            logging.error(f"❌ Invalid group_id: {group_id}")
            raise HTTPException(status_code=400, detail="Invalid invitation: missing or invalid group_id")
        
        # Check if group_id is a string "null"
        group_id_str = str(group_id).strip()
        if group_id_str.lower() in ["null", "none", ""]:
            logging.error(f"❌ Invalid group_id (string null): {group_id}")
            raise HTTPException(status_code=400, detail="Invalid invitation: missing or invalid group_id")
        
        if not user_id or user_id is None:
            logging.error(f"❌ Invalid user_id: {user_id}")
            raise HTTPException(status_code=400, detail="Invalid user_id")
        
        # Check if user_id is a string "null"
        user_id_str = str(user_id).strip()
        if user_id_str.lower() in ["null", "none", ""]:
            logging.error(f"❌ Invalid user_id (string null): {user_id}")
            raise HTTPException(status_code=400, detail="Invalid user_id")
        
        # Update invitation status FIRST (before inserting member, so RLS policy can check it)
        client.table("group_invitations").update({
            "status": "accepted",
            "responded_at": "now()"
        }).eq("id", invitation_id).execute()
        logging.info(f"✅ Updated invitation status to accepted")
        
        # Add user to group members - build data carefully, ensure all values are valid UUIDs
        # First, validate all UUIDs are valid format
        import re
        uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)
        
        # Validate group_id and user_id are valid UUIDs (already normalized above)
        if not uuid_pattern.match(group_id_str):
            logging.error(f"❌ Invalid group_id format: {group_id_str}")
            raise HTTPException(status_code=400, detail="Invalid group_id format")
        
        if not uuid_pattern.match(user_id_str):
            logging.error(f"❌ Invalid user_id format: {user_id_str}")
            raise HTTPException(status_code=400, detail="Invalid user_id format")
        
        # Build member_data - SIMPLIFIED: Only include required fields, skip invited_by entirely if invalid
        member_data = {
            "group_id": group_id_str,
            "user_id": user_id_str,
            "status": "approved"
        }
        
        # Only add invited_by if we have a valid UUID
        # Skip entirely if None, empty, or "null" string
        if inviter_id and inviter_id is not None:
            inviter_str = str(inviter_id).strip()
            if inviter_str and inviter_str.lower() not in ["null", "none", ""]:
                if uuid_pattern.match(inviter_str):
                    member_data["invited_by"] = inviter_str
                    logging.info(f"✅ Added inviter_id: {inviter_str}")
                else:
                    logging.warning(f"⚠️ Invalid inviter_id format, skipping invited_by")
            else:
                logging.info(f"ℹ️ inviter_id is null/empty, skipping invited_by")
        
        logging.info(f"📋 Final member_data: {member_data}")
        logging.info(f"   Keys: {list(member_data.keys())}")
        
        # Check if member already exists (using the selected client)
        existing = client.table("group_members").select("*").eq("group_id", group_id_str).eq("user_id", user_id_str).execute()
        
        if existing.data and len(existing.data) > 0:
            # Update existing member - only update status
            logging.info(f"🔄 Updating existing member")
            logging.info(f"   Existing: {existing.data[0]}")
            update_data = {"status": "approved"}
            try:
                result = client.table("group_members").update(update_data).eq("group_id", group_id_str).eq("user_id", user_id_str).execute()
                logging.info(f"✅ Successfully updated member: {result.data}")
            except Exception as update_err:
                logging.error(f"❌ Update error: {update_err}")
                raise
        else:
            # Insert new member (using the selected client)
            logging.info(f"➕ Inserting new member")
            logging.info(f"   Data to insert: {member_data}")
            try:
                result = client.table("group_members").insert(member_data).execute()
                logging.info(f"✅ Successfully inserted member: {result.data}")
            except Exception as insert_err:
                logging.error(f"❌ Insert error: {insert_err}")
                logging.error(f"   Error type: {type(insert_err)}")
                if hasattr(insert_err, 'message'):
                    logging.error(f"   Error message: {insert_err.message}")
                raise
        
        # Mark notification as read and update it to show it was accepted
        try:
            client.table("notifications").update({
                "read": True
            }).eq("id", notification_id).eq("user_id", user_id).execute()
            logging.info(f"✅ Marked notification as read")
        except Exception as notif_update_err:
            logging.warning(f"⚠️ Could not update notification: {notif_update_err}")
        
        return JSONResponse(content={"success": True, "message": "Invitation accepted"})
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error accepting invitation: {e}")
        raise HTTPException(status_code=500, detail=f"Error accepting invitation: {str(e)}")


@app.post("/api/groups/invitations/{invitation_id}/reject")
async def reject_invitation(
    invitation_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Reject a group invitation"""
    try:
        user_id = current_user.get('sub')
        
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        # Update invitation status
        result = supabase.table("group_invitations").update({
            "status": "rejected",
            "responded_at": "now()"
        }).eq("id", invitation_id).eq("invitee_user_id", user_id).eq("status", "pending").execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Invitation not found or already processed")
        
        # Mark related notifications as read
        try:
            client = supabase_admin if supabase_admin else supabase
            if client:
                # Find and mark notifications related to this invitation
                client.table("notifications").update({
                    "read": True
                }).eq("user_id", user_id).eq("type", "group_invitation").like("link", f"%invitation={invitation_id}%").execute()
                logging.info(f"✅ Marked related notifications as read")
        except Exception as notif_update_err:
            logging.warning(f"⚠️ Could not update notifications: {notif_update_err}")
        
        return JSONResponse(content={"success": True, "message": "Invitation rejected"})
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error rejecting invitation: {e}")
        raise HTTPException(status_code=500, detail=f"Error rejecting invitation: {str(e)}")


@app.post("/api/notifications/{notification_id}/approve")
async def approve_from_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Approve a request directly from a notification.
    Works for both group invitations and group change requests.
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Get notification
        notif_result = client.table("notifications").select("*").eq("id", notification_id).eq("user_id", user_id).execute()
        if not notif_result.data:
            raise HTTPException(status_code=404, detail="Notification not found")
        
        notification = notif_result.data[0]
        notif_type = notification.get("type")
        link = notification.get("link", "")
        
        # Extract IDs from link
        import re
        
        if notif_type == "group_invitation":
            # Extract invitation_id or group_id from link
            invitation_match = re.search(r'invitation=([^&]+)', link)
            if invitation_match:
                invitation_id = invitation_match.group(1)
                # Use existing accept endpoint logic
                return await accept_invitation(invitation_id, current_user)
            else:
                # Try to find by group_id
                group_match = re.search(r'group=([^&]+)', link)
                if group_match:
                    group_id = group_match.group(1)
                    # Find invitation by group
                    inv_result = client.table("group_invitations").select("id").eq("group_id", group_id).eq("invitee_user_id", user_id).eq("status", "pending").order("created_at", desc=True).limit(1).execute()
                    if inv_result.data:
                        invitation_id = inv_result.data[0]["id"]
                        return await accept_invitation(invitation_id, current_user)
            
            raise HTTPException(status_code=404, detail="Invitation not found")
        
        elif notif_type == "group_change_request":
            # Extract request_id from link
            request_match = re.search(r'change_request=([^&]+)', link)
            if request_match:
                request_id = request_match.group(1)
                # Use existing approve endpoint logic
                return await approve_group_change_request(request_id, current_user)
            
            raise HTTPException(status_code=404, detail="Change request not found")
        
        else:
            raise HTTPException(status_code=400, detail=f"Notification type '{notif_type}' does not support approval")
    
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error approving from notification: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/notifications/{notification_id}/reject")
async def reject_from_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Reject a request directly from a notification.
    Works for both group invitations and group change requests.
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Get notification
        notif_result = client.table("notifications").select("*").eq("id", notification_id).eq("user_id", user_id).execute()
        if not notif_result.data:
            raise HTTPException(status_code=404, detail="Notification not found")
        
        notification = notif_result.data[0]
        notif_type = notification.get("type")
        link = notification.get("link", "")
        
        # Extract IDs from link
        import re
        
        if notif_type == "group_invitation":
            # Extract invitation_id or group_id from link
            invitation_match = re.search(r'invitation=([^&]+)', link)
            if invitation_match:
                invitation_id = invitation_match.group(1)
                # Use existing reject endpoint logic
                return await reject_invitation(invitation_id, current_user)
            else:
                # Try to find by group_id
                group_match = re.search(r'group=([^&]+)', link)
                if group_match:
                    group_id = group_match.group(1)
                    # Find invitation by group
                    inv_result = client.table("group_invitations").select("id").eq("group_id", group_id).eq("invitee_user_id", user_id).eq("status", "pending").order("created_at", desc=True).limit(1).execute()
                    if inv_result.data:
                        invitation_id = inv_result.data[0]["id"]
                        return await reject_invitation(invitation_id, current_user)
            
            raise HTTPException(status_code=404, detail="Invitation not found")
        
        elif notif_type == "group_change_request":
            # Extract request_id from link
            request_match = re.search(r'change_request=([^&]+)', link)
            if request_match:
                request_id = request_match.group(1)
                # Use existing reject endpoint logic
                return await reject_group_change_request(request_id, current_user)
            
            raise HTTPException(status_code=404, detail="Change request not found")
        
        else:
            raise HTTPException(status_code=400, detail=f"Notification type '{notif_type}' does not support rejection")
    
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error rejecting from notification: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.delete("/api/groups/{group_id}")
async def delete_group(
    group_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a study group (only creator can delete)"""
    try:
        user_id = current_user.get('sub')
        
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        # Use service_role client if available (bypasses RLS)
        client = supabase_admin if supabase_admin else supabase
        
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        if not supabase_admin:
            logging.error("   ❌ ERROR: SUPABASE_SERVICE_ROLE_KEY not set!")
            raise HTTPException(
                status_code=500,
                detail="Server configuration error: SUPABASE_SERVICE_ROLE_KEY is required for deleting groups."
            )
        
        # Verify user is the creator
        group_result = client.table("study_groups").select("created_by").eq("id", group_id).execute()
        
        if not group_result.data:
            raise HTTPException(status_code=404, detail="Group not found")
        
        if group_result.data[0]['created_by'] != user_id:
            raise HTTPException(status_code=403, detail="Only group creator can delete the group")
        
        # Delete related data first (to ensure clean deletion)
        # Delete group members
        try:
            client.table("group_members").delete().eq("group_id", group_id).execute()
            logging.info(f"   ✅ Deleted group members for group {group_id}")
        except Exception as members_err:
            logging.warning(f"   ⚠️ Could not delete group members: {members_err}")
        
        # Delete group invitations
        try:
            client.table("group_invitations").delete().eq("group_id", group_id).execute()
            logging.info(f"   ✅ Deleted group invitations for group {group_id}")
        except Exception as inv_err:
            logging.warning(f"   ⚠️ Could not delete group invitations: {inv_err}")
        
        # Delete group messages
        try:
            client.table("group_messages").delete().eq("group_id", group_id).execute()
            logging.info(f"   ✅ Deleted group messages for group {group_id}")
        except Exception as msg_err:
            logging.warning(f"   ⚠️ Could not delete group messages: {msg_err}")
        
        # Delete group updates
        try:
            client.table("group_updates").delete().eq("group_id", group_id).execute()
            logging.info(f"   ✅ Deleted group updates for group {group_id}")
        except Exception as updates_err:
            logging.warning(f"   ⚠️ Could not delete group updates: {updates_err}")
        
        # Delete notifications related to this group
        try:
            client.table("notifications").delete().like("link", f"%group={group_id}%").execute()
            logging.info(f"   ✅ Deleted notifications for group {group_id}")
        except Exception as notif_err:
            logging.warning(f"   ⚠️ Could not delete notifications: {notif_err}")
        
        # Finally, delete the group itself (cascade should handle it, but we're being explicit)
        delete_result = client.table("study_groups").delete().eq("id", group_id).execute()
        
        logging.info(f"✅ Group {group_id} deleted by user {user_id}")
        
        return JSONResponse(content={"success": True, "message": "Group deleted successfully"})
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error deleting group: {e}")
        import traceback
        logging.error(f"   Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error deleting group: {str(e)}")


@app.delete("/api/notifications")
async def clear_notifications(
    current_user: dict = Depends(get_current_user),
    read_only: bool = False
):
    """Clear notifications for current user (all or only read ones)"""
    try:
        user_id = current_user.get('sub')
        
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        # Use service_role client if available
        client = supabase_admin if supabase_admin else supabase
        
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Delete notifications
        if read_only:
            # Delete only read notifications
            result = client.table("notifications").delete().eq("user_id", user_id).eq("read", True).execute()
            deleted_count = len(result.data) if result.data else 0
            message = f"Deleted {deleted_count} read notification(s)"
            logging.info(f"✅ {message} for user {user_id}")
        else:
            # Delete all notifications
            result = client.table("notifications").delete().eq("user_id", user_id).execute()
            deleted_count = len(result.data) if result.data else 0
            message = f"Deleted {deleted_count} notification(s)"
            logging.info(f"✅ {message} for user {user_id}")
        
        return JSONResponse(content={"success": True, "message": message, "deleted_count": deleted_count})
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error clearing notifications: {e}")
        import traceback
        logging.error(f"   Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error clearing notifications: {str(e)}")


@app.delete("/api/notifications/{notification_id}")
async def delete_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a specific notification"""
    try:
        user_id = current_user.get('sub')
        
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        # Use service_role client if available
        client = supabase_admin if supabase_admin else supabase
        
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Delete notification (only if it belongs to user)
        result = client.table("notifications").delete().eq("id", notification_id).eq("user_id", user_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Notification not found")
        
        logging.info(f"✅ Notification {notification_id} deleted by user {user_id}")
        
        return JSONResponse(content={"success": True, "message": "Notification deleted"})
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error deleting notification: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting notification: {str(e)}")


# Group Messages endpoints
@app.get("/api/groups/{group_id}/updates")
async def get_group_updates(
    group_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Fetch updates/notifications for a specific group"""
    try:
        user_id = current_user.get('sub')
        client = supabase_admin if supabase_admin else supabase
        
        # Verify user is a member of the group
        member_res = client.table("group_members").select("*").eq("group_id", group_id).eq("user_id", user_id).execute()
        if not member_res.data:
            raise HTTPException(status_code=403, detail="Not a member of this group")
            
        # Fetch updates
        updates_res = client.table("group_updates").select("*").eq("group_id", group_id).order("created_at", desc=True).limit(20).execute()
        
        return {"updates": updates_res.data or []}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error fetching group updates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/groups/{group_id}/messages")
async def get_group_messages(
    group_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get all messages for a group"""
    try:
        user_id = current_user.get('sub')
        
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        # Verify user is a member
        client = supabase_admin if supabase_admin else supabase
        member_check = client.table("group_members").select("*").eq("group_id", group_id).eq("user_id", user_id).eq("status", "approved").execute()
        
        if not member_check.data:
            # Check if user is the creator
            group_check = client.table("study_groups").select("created_by").eq("id", group_id).execute()
            if not group_check.data or group_check.data[0]['created_by'] != user_id:
                raise HTTPException(status_code=403, detail="You are not a member of this group")
        
        # Get messages
        messages_result = client.table("group_messages").select("*").eq("group_id", group_id).order("created_at", desc=False).limit(100).execute()
        
        return JSONResponse(content={"messages": messages_result.data or []})
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting group messages: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting messages: {str(e)}")


@app.post("/api/groups/{group_id}/messages")
async def send_group_message(
    group_id: str,
    message_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Send a message to a group"""
    try:
        user_id = current_user.get('sub')
        user_email = current_user.get('email', 'Unknown')
        
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        message_text = message_data.get('message', '').strip()
        if not message_text:
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        # Verify user is a member
        client = supabase_admin if supabase_admin else supabase
        member_check = client.table("group_members").select("*").eq("group_id", group_id).eq("user_id", user_id).eq("status", "approved").execute()
        
        if not member_check.data:
            # Check if user is the creator
            group_check = client.table("study_groups").select("created_by").eq("id", group_id).execute()
            if not group_check.data or group_check.data[0]['created_by'] != user_id:
                raise HTTPException(status_code=403, detail="You are not a member of this group")
        
        # Insert message
        # Note: is_agent column must be added to the database first
        # Run: ALTER TABLE group_messages ADD COLUMN IF NOT EXISTS is_agent BOOLEAN DEFAULT FALSE;
        message_result = client.table("group_messages").insert({
            "group_id": group_id,
            "user_id": user_id,
            "message": message_text
            # "is_agent": False  # Uncomment after adding column to database
        }).execute()
        
        if not message_result.data:
            raise HTTPException(status_code=500, detail="Failed to send message")
        
        # Check if message should trigger AI agent response
        # Trigger AI agent if message contains question words or ends with ?
        should_trigger_agent = any(word in message_text.lower() for word in ['?', 'מה', 'איך', 'מתי', 'למה', 'איפה', 'מי', 'איזה']) or message_text.strip().endswith('?')
        
        if should_trigger_agent:
            # Send to AI agent in background (don't wait for response)
            import asyncio
            asyncio.create_task(generate_agent_response(group_id, message_text, user_email))
        
        return JSONResponse(content={"success": True, "message": message_result.data[0]})
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error sending group message: {e}")
        raise HTTPException(status_code=500, detail=f"Error sending message: {str(e)}")


async def generate_agent_response(group_id: str, user_message: str, user_email: str):
    """Generate AI agent response for group chat"""
    try:
        # Get group context
        client = supabase_admin if supabase_admin else supabase
        group_result = client.table("study_groups").select("*").eq("id", group_id).execute()
        
        if not group_result.data:
            return
        
        group = group_result.data[0]
        course_name = group.get('course_name', 'הקורס')
        group_name = group.get('group_name', 'הקבוצה')
        
        # Simple AI response (can be enhanced with actual AI/LLM)
        user_message_lower = user_message.lower()
        
        if any(word in user_message_lower for word in ["שלום", "היי", "הי", "בוקר", "ערב"]):
            response_text = f"שלום! ברוכים הבאים ל-{group_name}. איך אני יכול לעזור לכם היום?"
        elif any(word in user_message_lower for word in ["מתי", "מתי הבחינה", "מתי המבחן"]):
            response_text = "אני יכול לעזור לכם לתכנן את לוח הזמנים. תוכלו לשאול אותי על תאריכי בחינות, מטלות ועוד."
        elif any(word in user_message_lower for word in ["מה", "מה הקורס", "מה נלמד"]):
            response_text = f"הקורס {course_name} הוא חלק מהתוכנית שלכם. איך אני יכול לעזור לכם עם הקורס הזה?"
        elif any(word in user_message_lower for word in ["איך", "איך ללמוד", "איך להתכונן"]):
            response_text = "אני יכול לעזור לכם לתכנן את הלמידה. תוכלו לשאול אותי על שיטות למידה, תכנון זמן ועוד."
        elif "?" in user_message or any(word in user_message_lower for word in ["למה", "איפה", "מי", "איזה"]):
            response_text = "זו שאלה מעניינת! אני כאן כדי לעזור לכם. תוכלו לשאול אותי על הקורס, המטלות, הבחינות ועוד."
        else:
            response_text = f"תודה על ההודעה! אני כאן כדי לעזור לכם עם {course_name}. איך אני יכול לעזור?"
        
        # Insert agent message
        # Note: is_agent column must be added to the database first
        agent_message_result = client.table("group_messages").insert({
            "group_id": group_id,
            "user_id": None,  # Agent doesn't have a user_id
            "message": response_text
            # "is_agent": True  # Uncomment after adding column to database
        }).execute()
        
        logging.info(f"✅ AI agent responded to message in group {group_id}")
        
    except Exception as e:
        logging.error(f"Error generating agent response: {e}")
        import traceback
        logging.error(f"   Traceback: {traceback.format_exc()}")


@app.get("/api/groups/{group_id}/members")
async def get_group_members(
    group_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get all members of a group"""
    try:
        user_id = current_user.get('sub')
        
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        # Verify user is a member
        client = supabase_admin if supabase_admin else supabase
        member_check = client.table("group_members").select("*").eq("group_id", group_id).eq("user_id", user_id).eq("status", "approved").execute()
        
        if not member_check.data:
            # Check if user is the creator
            group_check = client.table("study_groups").select("created_by").eq("id", group_id).execute()
            if not group_check.data or group_check.data[0]['created_by'] != user_id:
                raise HTTPException(status_code=403, detail="You are not a member of this group")
        
        # Get all members
        members_result = client.table("group_members").select("user_id, status").eq("group_id", group_id).eq("status", "approved").execute()
        
        # Get user emails
        members_list = []
        if members_result.data and supabase_admin:
            for member in members_result.data:
                member_user_id = member['user_id']
                try:
                    user_info = supabase_admin.auth.admin.get_user_by_id(member_user_id)
                    if hasattr(user_info, 'user') and user_info.user:
                        email = getattr(user_info.user, 'email', None) or 'Unknown'
                        members_list.append({
                            "user_id": member_user_id,
                            "email": email
                        })
                except Exception as user_err:
                    logging.warning(f"Could not get user info for {member_user_id}: {user_err}")
                    members_list.append({
                        "user_id": member_user_id,
                        "email": "Unknown"
                    })
        else:
            # Fallback: just return user_ids
            members_list = [{"user_id": m['user_id'], "email": "Unknown"} for m in (members_result.data or [])]
        
        return JSONResponse(content={"members": members_list})
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting group members: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting members: {str(e)}")


# ==================== ASSIGNMENTS API ====================

@app.get("/api/assignments/sample")
async def get_sample_assignments():
    """
    Get sample assignments for courses
    Returns mock data of assignments with deadlines
    """
    from datetime import datetime, timedelta
    
    today = datetime.now()
    
    # Mock assignments data for each course
    sample_assignments = {
        "1": [  # מבוא למדעי המחשב
            {
                "id": "a1",
                "course_id": "1",
                "title": "תרגיל 1: משתנים וקלט",
                "description": "כתוב תוכנית בפייתון לקלט ועיבוד משתנים",
                "due_date": (today + timedelta(days=7)).strftime("%Y-%m-%d"),
                "priority": "high",
                "is_completed": False
            },
            {
                "id": "a2",
                "course_id": "1",
                "title": "תרגיל 2: לולאות וביטויים",
                "description": "פתרון תרגילים על לולאות",
                "due_date": (today + timedelta(days=14)).strftime("%Y-%m-%d"),
                "priority": "medium",
                "is_completed": False
            },
            {
                "id": "a3",
                "course_id": "1",
                "title": "מבחן מחצה",
                "description": "מבחן על כל החומר עד כה",
                "due_date": (today + timedelta(days=21)).strftime("%Y-%m-%d"),
                "priority": "high",
                "is_completed": False
            }
        ],
        "2": [  # מבני נתונים
            {
                "id": "a4",
                "course_id": "2",
                "title": "מימוש LinkedList",
                "description": "מימוש מבנה LinkedList עם פעולות בסיסיות",
                "due_date": (today + timedelta(days=10)).strftime("%Y-%m-%d"),
                "priority": "high",
                "is_completed": False
            },
            {
                "id": "a5",
                "course_id": "2",
                "title": "תרגיל Stack ו-Queue",
                "description": "מימוש וקריאה תודעה של Stack ו-Queue",
                "due_date": (today + timedelta(days=17)).strftime("%Y-%m-%d"),
                "priority": "medium",
                "is_completed": False
            }
        ],
        "3": [  # אלגוריתמים
            {
                "id": "a6",
                "course_id": "3",
                "title": "ניתוח מורכבות אלגוריתמים",
                "description": "חישוב Big O complexity לאלגוריתמים שונים",
                "due_date": (today + timedelta(days=12)).strftime("%Y-%m-%d"),
                "priority": "medium",
                "is_completed": False
            }
        ],
        "4": [  # מסדי נתונים
            {
                "id": "a7",
                "course_id": "4",
                "title": "שאילתות SQL בסיסיות",
                "description": "כתוב שאילתות SELECT, INSERT, UPDATE",
                "due_date": (today + timedelta(days=8)).strftime("%Y-%m-%d"),
                "priority": "high",
                "is_completed": False
            },
            {
                "id": "a8",
                "course_id": "4",
                "title": "עיצוב ER Diagram",
                "description": "עיצוב מודל ER לבסיס נתונים",
                "due_date": (today + timedelta(days=15)).strftime("%Y-%m-%d"),
                "priority": "medium",
                "is_completed": True
            }
        ],
        "5": [  # תכנות מונחה עצמים
            {
                "id": "a9",
                "course_id": "5",
                "title": "מבנה OOP בסיסי",
                "description": "יצירת Classes, Inheritance ו-Polymorphism",
                "due_date": (today + timedelta(days=9)).strftime("%Y-%m-%d"),
                "priority": "high",
                "is_completed": False
            }
        ],
        "6": [  # רשתות מחשבים
            {
                "id": "a10",
                "course_id": "6",
                "title": "פרוטוקולי TCP/IP",
                "description": "מטלה על פרוטוקולים תקשורת",
                "due_date": (today + timedelta(days=11)).strftime("%Y-%m-%d"),
                "priority": "medium",
                "is_completed": False
            }
        ]
    }
    
    # Add days_remaining calculation
    for course_assignments in sample_assignments.values():
        for assignment in course_assignments:
            due_date = datetime.strptime(assignment["due_date"], "%Y-%m-%d")
            days_remaining = (due_date - today).days
            assignment["days_remaining"] = days_remaining
    
    return JSONResponse(content={"assignments": sample_assignments})


@app.get("/api/course-catalog")
async def get_course_catalog():
    """
    Get all courses from the course catalog
    Returns list of all available courses
    """
    try:
        client = supabase_admin if supabase_admin else supabase
        
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Get all courses from catalog
        result = client.table("course_catalog").select("*").order("course_number", desc=False).execute()
        
        courses = result.data if result.data else []
        logging.info(f"📚 [CATALOG] Found {len(courses)} courses in catalog")
        
        return JSONResponse(content={"courses": courses})
        
    except Exception as e:
        logging.error(f"❌ [CATALOG] Error loading course catalog: {e}")
        import traceback
        logging.error(f"   Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error loading course catalog: {str(e)}")


@app.get("/api/assignments")
async def get_assignments():
    """
    Get all assignments from Supabase (not user-specific)
    Returns assignments grouped by course_catalog_id (with course info)
    """
    try:
        logging.info(f"📝 [ASSIGNMENTS] Loading all assignments")
        
        # Use service_role client if available, otherwise anon client
        client = supabase_admin if supabase_admin else supabase
        
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Get all assignments (no user filter)
        result = client.table("assignments").select("*").order("due_date", desc=False).execute()
        
        assignments = result.data if result.data else []
        logging.info(f"📝 [ASSIGNMENTS] Found {len(assignments)} assignments")
        
        # Get all course catalog entries for mapping (by course_number AND by id)
        course_catalog_result = client.table("course_catalog").select("*").execute()
        course_catalog_map_by_id = {}
        course_catalog_map_by_number = {}
        if course_catalog_result.data:
            for course in course_catalog_result.data:
                course_catalog_map_by_id[course["id"]] = course
                course_number = course.get("course_number")
                if course_number:
                    course_catalog_map_by_number[str(course_number).strip()] = course
            logging.info(f"📝 [ASSIGNMENTS] Loaded {len(course_catalog_map_by_id)} courses from catalog")
            print(f"📝 [ASSIGNMENTS] Loaded {len(course_catalog_map_by_id)} courses from catalog, {len(course_catalog_map_by_number)} by course_number")
        
        # Attach course info to each assignment
        # Priority: 1) course_number from assignment -> find in course_catalog by course_number
        #           2) course_catalog_id -> find in course_catalog by id
        for assignment in assignments:
            assignment_course_number = assignment.get("course_number")  # Direct field in assignments
            course_catalog_id = assignment.get("course_catalog_id")
            
            course_info = None
            final_course_number = None
            
            # First try: match by course_number directly from assignment
            if assignment_course_number:
                assignment_course_number_str = str(assignment_course_number).strip()
                if assignment_course_number_str in course_catalog_map_by_number:
                    course_info = course_catalog_map_by_number[assignment_course_number_str]
                    final_course_number = assignment_course_number_str
                    print(f"✅ [ASSIGNMENTS] Assignment '{assignment.get('title')}' -> matched by course_number: {final_course_number}")
                    logging.info(f"📝 [ASSIGNMENTS] Assignment {assignment.get('id')} matched by course_number: {final_course_number}")
                else:
                    print(f"⚠️ [ASSIGNMENTS] Assignment '{assignment.get('title')}' has course_number '{assignment_course_number_str}' but not found in course_catalog")
            
            # Second try: match by course_catalog_id
            if not course_info and course_catalog_id:
                if course_catalog_id in course_catalog_map_by_id:
                    course_info = course_catalog_map_by_id[course_catalog_id]
                    final_course_number = course_info.get("course_number")
                    if final_course_number:
                        final_course_number = str(final_course_number).strip()
                    print(f"✅ [ASSIGNMENTS] Assignment '{assignment.get('title')}' -> matched by course_catalog_id: {course_catalog_id}, course_number: {final_course_number}")
                    logging.info(f"📝 [ASSIGNMENTS] Assignment {assignment.get('id')} matched by course_catalog_id: {course_catalog_id}")
            
            if course_info and final_course_number:
                assignment["course_catalog"] = course_info
                assignment["course_number"] = final_course_number  # Ensure assignment has course_number
                print(f"   ✅ Final: course_number={final_course_number}, course_name={course_info.get('course_name')}")
                logging.info(f"📝 [ASSIGNMENTS] Attached course info: course_number={final_course_number}, course_name={course_info.get('course_name')}")
            else:
                assignment["course_catalog"] = {}
                print(f"❌ [ASSIGNMENTS] Assignment '{assignment.get('title')}' could not be matched:")
                print(f"   - course_number from assignment: {assignment_course_number}")
                print(f"   - course_catalog_id: {course_catalog_id}")
                logging.warning(f"📝 [ASSIGNMENTS] Assignment {assignment.get('id')} could not be matched to course_catalog")
        
        logging.info(f"📝 [ASSIGNMENTS] Processed {len(assignments)} assignments with course info")
        
        # Debug: log first assignment structure
        if assignments:
            logging.info(f"📝 [ASSIGNMENTS] First assignment structure: {assignments[0]}")
        
        # Group assignments by course_number (use course_number from assignment, which we set above)
        assignments_by_course = {}
        for assignment in assignments:
            # Get course_number from assignment (we set it in the previous loop)
            course_number = assignment.get("course_number")
            
            # If not set, try to get from course_catalog
            if not course_number:
                course_catalog_info = assignment.get("course_catalog", {})
                if isinstance(course_catalog_info, dict):
                    course_number = course_catalog_info.get("course_number")
            
            if not course_number:
                logging.warning(f"📝 [ASSIGNMENTS] Assignment {assignment.get('id')} has no course_number! Skipping...")
                print(f"⚠️ [ASSIGNMENTS] Assignment '{assignment.get('title')}' has no course_number - cannot match with user courses!")
                continue
            
            # Normalize course_number to string
            key = str(course_number).strip()
            
            logging.info(f"📝 [ASSIGNMENTS] Using key (course_number): {key} for assignment {assignment.get('title')}")
            print(f"📝 [ASSIGNMENTS] Assignment '{assignment.get('title')}' -> key: {key} (course_number)")
            
            if key not in assignments_by_course:
                assignments_by_course[key] = []
            
            # Calculate days_remaining
            from datetime import datetime
            if assignment.get("due_date"):
                due_date = datetime.strptime(assignment["due_date"], "%Y-%m-%d") if isinstance(assignment["due_date"], str) else assignment["due_date"]
                today = datetime.now()
                days_remaining = (due_date - today).days
                assignment["days_remaining"] = days_remaining
            
            # Add course info to assignment (use course_catalog if available)
            course_catalog_info = assignment.get("course_catalog", {})
            if course_catalog_info:
                assignment["course_info"] = course_catalog_info
            
            assignments_by_course[key].append(assignment)
        
        print("=" * 60)
        print(f"📝 [ASSIGNMENTS] Grouped into {len(assignments_by_course)} courses: {list(assignments_by_course.keys())}")
        logging.info(f"📝 [ASSIGNMENTS] Grouped into {len(assignments_by_course)} courses: {list(assignments_by_course.keys())}")
        
        # Debug: log the final structure
        for key, assignments_list in assignments_by_course.items():
            print(f"📝 [ASSIGNMENTS] Key '{key}': {len(assignments_list)} assignments")
            logging.info(f"📝 [ASSIGNMENTS] Key '{key}': {len(assignments_list)} assignments")
            if assignments_list:
                first = assignments_list[0]
                course_info = first.get('course_info') or first.get('course_catalog') or {}
                course_number = course_info.get('course_number')
                course_name = course_info.get('course_name')
                print(f"   First assignment: '{first.get('title')}', course_number: {course_number}, course_name: {course_name}")
                logging.info(f"📝 [ASSIGNMENTS]   First assignment: {first.get('title')}, course_number: {course_number}, course_name: {course_name}")
        print("=" * 60)
        
        return JSONResponse(content={"assignments": assignments_by_course})
        
    except Exception as e:
        logging.error(f"❌ [ASSIGNMENTS] Error loading assignments: {e}")
        import traceback
        logging.error(f"   Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error loading assignments: {str(e)}")


@app.post("/api/assignments")
async def create_assignment(assignment_data: dict):
    """
    Create a new assignment (not user-specific)
    Requires: course_catalog_id (or course_number), title, due_date
    """
    try:
        logging.info(f"📝 [ASSIGNMENTS] Creating assignment")
        
        client = supabase_admin if supabase_admin else supabase
        
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Get course_catalog_id from course_number if provided
        course_catalog_id = assignment_data.get("course_catalog_id")
        course_number = assignment_data.get("course_number")
        
        if not course_catalog_id and course_number:
            # Find course by course_number
            course_result = client.table("course_catalog").select("id").eq("course_number", course_number).limit(1).execute()
            if course_result.data and len(course_result.data) > 0:
                course_catalog_id = course_result.data[0]["id"]
            else:
                raise HTTPException(status_code=404, detail=f"Course with number {course_number} not found in catalog")
        
        if not course_catalog_id:
            raise HTTPException(status_code=400, detail="course_catalog_id or course_number is required")
        
        # Prepare assignment data (no user_id)
        new_assignment = {
            "course_catalog_id": course_catalog_id,
            "title": assignment_data.get("title"),
            "description": assignment_data.get("description"),
            "due_date": assignment_data.get("due_date"),
            "priority": assignment_data.get("priority", "medium"),
            "is_completed": assignment_data.get("is_completed", False)
        }
        
        # Insert assignment
        result = client.table("assignments").insert(new_assignment).execute()
        
        if result.data:
            logging.info(f"📝 [ASSIGNMENTS] Created assignment: {result.data[0].get('id')}")
            return JSONResponse(content={"assignment": result.data[0]}, status_code=201)
        else:
            raise HTTPException(status_code=500, detail="Failed to create assignment")
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"❌ [ASSIGNMENTS] Error creating assignment: {e}")
        import traceback
        logging.error(f"   Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error creating assignment: {str(e)}")


@app.patch("/api/assignments/{assignment_id}")
async def update_assignment_status(assignment_id: str, status_data: dict):
    """
    Update assignment completion status
    Requires: is_completed (bool)
    """
    try:
        logging.info(f"📝 [ASSIGNMENTS] Updating assignment {assignment_id} status")
        
        client = supabase_admin if supabase_admin else supabase
        
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        is_completed = status_data.get("is_completed", False)
        
        # Update assignment
        result = client.table("assignments").update({
            "is_completed": is_completed
        }).eq("id", assignment_id).execute()
        
        if result.data and len(result.data) > 0:
            logging.info(f"📝 [ASSIGNMENTS] Updated assignment {assignment_id} to is_completed={is_completed}")
            print(f"✅ [ASSIGNMENTS] Updated assignment {assignment_id} to is_completed={is_completed}")
            return JSONResponse(content={"assignment": result.data[0]}, status_code=200)
        else:
            raise HTTPException(status_code=404, detail="Assignment not found")
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"❌ [ASSIGNMENTS] Error updating assignment: {e}")
        print(f"❌ [ASSIGNMENTS] Error updating assignment: {e}")
        import traceback
        logging.error(f"   Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error updating assignment: {str(e)}")


@app.get("/api/assignments/course/{course_id}")
async def get_course_assignments(course_id: str):
    """Get assignments for a specific course"""
    from datetime import datetime, timedelta
    
    today = datetime.now()
    
    # Same mock assignments data
    sample_assignments = {
        "1": [  # מבוא למדעי המחשב
            {
                "id": "a1",
                "course_id": "1",
                "title": "תרגיל 1: משתנים וקלט",
                "description": "כתוב תוכנית בפייתון לקלט ועיבוד משתנים",
                "due_date": (today + timedelta(days=7)).strftime("%Y-%m-%d"),
                "priority": "high",
                "is_completed": False
            },
            {
                "id": "a2",
                "course_id": "1",
                "title": "תרגיל 2: לולאות וביטויים",
                "description": "פתרון תרגילים על לולאות",
                "due_date": (today + timedelta(days=14)).strftime("%Y-%m-%d"),
                "priority": "medium",
                "is_completed": False
            },
            {
                "id": "a3",
                "course_id": "1",
                "title": "מבחן מחצה",
                "description": "מבחן על כל החומר עד כה",
                "due_date": (today + timedelta(days=21)).strftime("%Y-%m-%d"),
                "priority": "high",
                "is_completed": False
            }
        ],
        "2": [  # מבני נתונים
            {
                "id": "a4",
                "course_id": "2",
                "title": "מימוש LinkedList",
                "description": "מימוש מבנה LinkedList עם פעולות בסיסיות",
                "due_date": (today + timedelta(days=10)).strftime("%Y-%m-%d"),
                "priority": "high",
                "is_completed": False
            },
            {
                "id": "a5",
                "course_id": "2",
                "title": "תרגיל Stack ו-Queue",
                "description": "מימוש וקריאה תודעה של Stack ו-Queue",
                "due_date": (today + timedelta(days=17)).strftime("%Y-%m-%d"),
                "priority": "medium",
                "is_completed": False
            }
        ],
        "3": [  # אלגוריתמים
            {
                "id": "a6",
                "course_id": "3",
                "title": "ניתוח מורכבות אלגוריתמים",
                "description": "חישוב Big O complexity לאלגוריתמים שונים",
                "due_date": (today + timedelta(days=12)).strftime("%Y-%m-%d"),
                "priority": "medium",
                "is_completed": False
            }
        ],
        "4": [  # מסדי נתונים
            {
                "id": "a7",
                "course_id": "4",
                "title": "שאילתות SQL בסיסיות",
                "description": "כתוב שאילתות SELECT, INSERT, UPDATE",
                "due_date": (today + timedelta(days=8)).strftime("%Y-%m-%d"),
                "priority": "high",
                "is_completed": False
            },
            {
                "id": "a8",
                "course_id": "4",
                "title": "עיצוב ER Diagram",
                "description": "עיצוב מודל ER לבסיס נתונים",
                "due_date": (today + timedelta(days=15)).strftime("%Y-%m-%d"),
                "priority": "medium",
                "is_completed": True
            }
        ],
        "5": [  # תכנות מונחה עצמים
            {
                "id": "a9",
                "course_id": "5",
                "title": "מבנה OOP בסיסי",
                "description": "יצירת Classes, Inheritance ו-Polymorphism",
                "due_date": (today + timedelta(days=9)).strftime("%Y-%m-%d"),
                "priority": "high",
                "is_completed": False
            }
        ],
        "6": [  # רשתות מחשבים
            {
                "id": "a10",
                "course_id": "6",
                "title": "פרוטוקולי TCP/IP",
                "description": "מטלה על פרוטוקולים תקשורת",
                "due_date": (today + timedelta(days=11)).strftime("%Y-%m-%d"),
                "priority": "medium",
                "is_completed": False
            }
        ]
    }
    
    # Get assignments for the course
    course_assignments = sample_assignments.get(course_id, [])
    
    # Add days_remaining calculation
    for assignment in course_assignments:
        due_date = datetime.strptime(assignment["due_date"], "%Y-%m-%d")
        days_remaining = (due_date - today).days
        assignment["days_remaining"] = days_remaining
    
    return JSONResponse(content={"assignments": course_assignments})
