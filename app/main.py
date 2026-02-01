from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
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
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta
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

app = FastAPI(title="Student Planner System", description="סוכן חכם לתכנון מערכת קורסים ולימודים")

# Background scheduler for weekly auto-planning
scheduler = BackgroundScheduler()


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
        
        # TODO: In the future, we can call LLM here to extract structured preferences
        # and update study_preferences_summary column
        
        return JSONResponse(content={
            "message": "Preferences saved successfully",
            "preferences_length": len(study_preferences_raw)
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
    hour, minute = time_str.split(":")
    return int(hour) * 60 + int(minute)


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
                    system_user_id = member_ids[0] if member_ids else user_id
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
    time_slots: list
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
        course_requirements = []
        for course in courses:
            course_number = course.get("course_number")
            course_name = course.get("course_name")
            credit_points = course.get("credit_points") or 3
            total_hours = credit_points * 3
            
            # Count group blocks already allocated
            group_hours = sum(1 for b in skeleton_blocks if b.get("course_number") == course_number and b.get("work_type") == "group")
            personal_hours_needed = max(0, (total_hours // 2) - group_hours)
            
            course_requirements.append({
                "course_number": course_number,
                "course_name": course_name,
                "credit_points": credit_points,
                "personal_hours_needed": personal_hours_needed,
                "group_hours_allocated": group_hours
            })
        
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
5. Optimize placement based on user preferences (preferred times, days, session lengths, breaks)
6. Return ONLY valid JSON, no explanations

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
Place the required personal study blocks for each course in the available slots, optimizing for:
1. User's preferred study times and days
2. Appropriate session lengths (avoid too many single-hour blocks if user prefers longer sessions)
3. Adequate breaks between sessions
4. Even distribution across the week
5. Grouping blocks for the same course when beneficial

Return only the JSON with personal_blocks array."""

        # Call LLM (configurable model)
        model = os.getenv("LLM_MODEL") or "gpt-4o-mini"
        base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        logging.info(f"Calling LLM for schedule refinement (model={model}, base_url={base_url})")

        # gpt-5 family requires temperature=1 with this provider
        temperature = 0.7
        if "gpt-5" in model.lower():
            temperature = 1

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature,
            max_tokens=2000,
            response_format={"type": "json_object"}
        )
        
        # Parse response
        content = response.choices[0].message.content
        logging.info(f"LLM response received: {len(content)} chars")
        logging.info(f"LLM response (truncated): {content[:500]}")
        
        llm_output = json.loads(content)
        personal_blocks = llm_output.get("personal_blocks", [])
        
        logging.info(f"LLM proposed {len(personal_blocks)} personal blocks")
        
        return {
            "success": True,
            "blocks": personal_blocks,
            "message": f"LLM refinement successful, proposed {len(personal_blocks)} blocks"
        }
        
    except Exception as e:
        logging.error(f"LLM refinement error: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return {
            "success": False,
            "blocks": [],
            "message": f"LLM refinement failed: {str(e)}"
        }


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
        
        for group in groups:
            group_id = group["id"]
            course_number = group.get("course_id") # Note: This field is expected to be the course_number
            course_name = group.get("course_name") or "Group Work"
            
            # Get members
            members_res = client.table("group_members").select("user_id").eq("group_id", group_id).eq("status", "approved").execute()
            all_member_ids = [m["user_id"] for m in (members_res.data or [])]
            
            # Filter members to only those taking this course THIS semester
            member_ids = [mid for mid in all_member_ids if mid in user_active_courses and course_number in user_active_courses[mid]]
            
            if not member_ids:
                logging.info(f"👥 [GLOBAL AGENT] Skipping group {course_name} - no active members in this course")
                continue
            
            # Quota calculation for group: assume 3 credits if not found
            group_quota = 4 # Default to 4h for group (half of 3*3=9)
            
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

                fake_user = {"id": uid, "sub": uid}
                plan_res = await generate_weekly_plan(week_start, fake_user, notify=False)
                
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
        response = client.table("weekly_constraints").select("*").eq("user_id", user_id).eq("week_start", week_start).execute()
        constraints_list = []
        for constraint in (response.data or []):
            constraint_copy = constraint.copy()
            constraint_copy["days"] = _parse_days(constraint.get("days"))
            constraints_list.append(constraint_copy)
        return {"constraints": constraints_list}
    except Exception as e:
        logging.error(f"Error fetching weekly constraints: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching weekly constraints: {str(e)}")


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
        user_id = current_user.get("id") or current_user.get("sub")
        client = supabase_admin if supabase_admin else supabase
        plan_result = client.table("weekly_plans").select("*").eq("user_id", user_id).eq("week_start", week_start).limit(1).execute()
        if not plan_result.data:
            return {"plan": None, "blocks": []}
        plan = plan_result.data[0]
        blocks_result = client.table("weekly_plan_blocks").select("*").eq("plan_id", plan["id"]).order("day_of_week").order("start_time").execute()
        return {"plan": plan, "blocks": blocks_result.data or []}
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
            for gb in actual_group_blocks:
                g_day, g_time = gb["day_of_week"], gb["start_time"]
                if (g_day, g_time) in available_slots:
                    available_slots.remove((g_day, g_time))

        # Compute total hours and weights AFTER group blocks are removed
        total_credits = sum([c.get("credit_points") or 3 for c in courses]) or 1
        total_slots = len(available_slots) 
        if total_slots == 0 and not actual_group_blocks:
            return {"message": "No available slots for plan", "plan": None, "blocks": []}

        # Create plan record
        existing_plan = client.table("weekly_plans").select("id").eq("user_id", user_id).eq("week_start", week_start).execute()
        if existing_plan.data:
            plan_id = existing_plan.data[0]["id"]
            client.table("weekly_plan_blocks").delete().eq("plan_id", plan_id).execute()
        else:
            plan_id = client.table("weekly_plans").insert({"user_id": user_id, "week_start": week_start, "source": "auto"}).execute().data[0]["id"]

        plan_blocks = []

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
                "source": "group"
            })

        # 3. Load user preferences for LLM refinement
        profile_result = client.table("user_profiles").select("study_preferences_raw, study_preferences_summary").eq("id", user_id).limit(1).execute()
        user_preferences_raw = ""
        user_preferences_summary = {}
        if profile_result.data:
            user_preferences_raw = profile_result.data[0].get("study_preferences_raw") or ""
            user_preferences_summary = profile_result.data[0].get("study_preferences_summary") or {}
        
        logging.info(f"📋 User preferences loaded: {len(user_preferences_raw)} chars raw, {len(user_preferences_summary)} keys in summary")
        
        # 4. Try LLM-based personal block placement
        llm_result = await _refine_schedule_with_llm(
            skeleton_blocks=plan_blocks,  # Group blocks already placed
            available_slots=available_slots[:],  # Copy of available slots
            courses=courses,
            user_preferences_raw=user_preferences_raw,
            user_preferences_summary=user_preferences_summary,
            time_slots=time_slots
        )
        
        if llm_result["success"] and llm_result["blocks"]:
            logging.info("Using LLM-refined schedule")
            llm_blocks = llm_result["blocks"]
            applied_llm_blocks = 0
            
            # Validate and add LLM blocks
            for llm_block in llm_blocks:
                day_index = llm_block.get("day_index")
                start_time = llm_block.get("start_time")
                course_number = llm_block.get("course_number")
                course_name = llm_block.get("course_name")
                
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
                course_name = course.get("course_name")
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
                course_name = course.get("course_name")
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
        if plan_blocks:
            # Check for duplicates before inserting
            slot_check = {}
            for block in plan_blocks:
                key = (block['day_of_week'], block['start_time'])
                if key in slot_check:
                    logging.error(f"❌ DUPLICATE SLOT DETECTED! {key} used by both '{slot_check[key]}' and '{block['course_name']}'")
                else:
                    slot_check[key] = block['course_name']
            
            client.table("weekly_plan_blocks").insert(plan_blocks).execute()
            logging.info(f"Inserted {len(plan_blocks)} blocks successfully")

        if notify:
            try:
                notif_data = {
                    "user_id": user_id,
                    "type": "plan_ready",
                    "title": "המערכת השבועית שלך מוכנה! 📅",
                    "message": f"הסוכן סיים לתכנן את המערכת שלך לשבוע ({week_start}). מוזמן להסתכל ולעדכן!",
                    "link": f"/schedule?week={week_start}",
                    "read": False
                }
                logging.info(f"🔔 Sending plan_ready notification to user {user_id}")
                client.table("notifications").insert(notif_data).execute()
            except Exception as notif_err:
                logging.warning(f"⚠️ Failed to notify user {user_id} about plan ready: {notif_err}")

        return {"message": "Weekly plan generated", "plan_id": plan_id, "blocks": plan_blocks}
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
        run_at = datetime.utcnow() + timedelta(minutes=minutes)
        scheduler.add_job(
            _run_weekly_auto_for_all_users_sync,
            DateTrigger(run_date=run_at),
            id=f"weekly_auto_plan_manual_{run_at.timestamp()}",
            replace_existing=False,
        )
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
        total = len(blocks) if blocks else 0
        if total > 0:
            personal_count = sum(1 for b in blocks if b.get("work_type") == "personal")
            group_count = sum(1 for b in blocks if b.get("work_type") == "group")
            personal_ratio = personal_count / total
            group_ratio = group_count / total

            client.table("course_time_preferences").upsert({
                "user_id": user_id,
                "course_number": course_number,
                "personal_ratio": personal_ratio,
                "group_ratio": group_ratio
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
        # Calculate new end time (1 hour after start)
        new_end_time = _minutes_to_time(_time_to_minutes(new_start_time) + 60)
        
        # Update the block
        update_result = client.table("weekly_plan_blocks").update({
            "day_of_week": new_day,
            "start_time": new_start_time,
            "end_time": new_end_time,
            "source": "manual"  # Mark as manually edited
        }).eq("id", block_id).execute()
        
        logging.info(f"✅ User {user_id} moved personal block {block_id} to day {new_day} at {new_start_time}")
        
        return JSONResponse(content={
            "message": "Block moved successfully",
            "block": update_result.data[0] if update_result.data else {}
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error moving schedule block: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/schedule/group-change-request/create")
async def create_group_change_request(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a request to change a group meeting time.
    Requires approval from all group members.
    """
    try:
        user_id = current_user.get("id") or current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        body = await request.json()
        group_id = body.get("group_id")
        week_start = body.get("week_start")
        original_day = body.get("original_day_of_week")
        original_start = body.get("original_start_time")
        proposed_day = body.get("proposed_day_of_week")
        proposed_start = body.get("proposed_start_time")
        reason = body.get("reason", "")
        
        if not all([group_id, week_start, proposed_day is not None, proposed_start]):
            raise HTTPException(status_code=400, detail="Missing required fields")
        
        client = supabase_admin if supabase_admin else supabase
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Verify user is member of this group
        member_check = client.table("group_members").select("id").eq("group_id", group_id).eq("user_id", user_id).eq("status", "approved").execute()
        if not member_check.data:
            raise HTTPException(status_code=403, detail="Not a member of this group")
        
        # Calculate end times (1 hour blocks)
        original_end = _minutes_to_time(_time_to_minutes(original_start) + 60) if original_start else None
        proposed_end = _minutes_to_time(_time_to_minutes(proposed_start) + 60)
        
        # Create the change request
        request_data = {
            "group_id": group_id,
            "week_start": week_start,
            "original_day_of_week": original_day,
            "original_start_time": original_start,
            "original_end_time": original_end,
            "proposed_day_of_week": proposed_day,
            "proposed_start_time": proposed_start,
            "proposed_end_time": proposed_end,
            "requested_by": user_id,
            "reason": reason,
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
        original_time_str = f"{day_names[original_day]} {original_start}" if original_day is not None else "קיים"
        proposed_time_str = f"{day_names[proposed_day]} {proposed_start}"
        
        # Send notifications to all members
        for member_id in member_ids:
            try:
                client.table("notifications").insert({
                    "user_id": member_id,
                    "type": "group_change_request",
                    "title": f"בקשת שינוי מפגש: {group_name}",
                    "message": f"{requester_name} מבקש לשנות מפגש מ-{original_time_str} ל-{proposed_time_str}. נדרשת אישור מכל החברים.",
                    "link": f"/schedule?change_request={request_id}",
                    "read": False
                }).execute()
            except Exception as notif_err:
                logging.error(f"Failed to notify member {member_id}: {notif_err}")
        
        logging.info(f"✅ Created group change request {request_id} for group {group_id}")
        
        return JSONResponse(content={
            "message": "Change request created. Waiting for approval from all members.",
            "request": change_request,
            "members_to_approve": len(member_ids)
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
        
        # Record the approval
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
                "responded_at": "NOW()"
            }).eq("request_id", request_id).eq("user_id", user_id).execute()
        
        # Check if all members have approved
        all_members = client.table("group_members").select("user_id").eq("group_id", group_id).eq("status", "approved").execute()
        member_ids = [m["user_id"] for m in (all_members.data or [])]
        
        approvals = client.table("group_change_approvals").select("user_id, approved").eq("request_id", request_id).execute()
        approval_map = {a["user_id"]: a["approved"] for a in (approvals.data or [])}
        
        all_responded = all(mid in approval_map for mid in member_ids)
        all_approved = all_responded and all(approval_map.get(mid, False) for mid in member_ids)
        
        if all_approved:
            # Apply the change!
            week_start = change_request["week_start"]
            proposed_day = change_request["proposed_day_of_week"]
            proposed_start = change_request["proposed_start_time"]
            proposed_end = change_request["proposed_end_time"]
            
            # Update all group_plan_blocks for this group and week
            client.table("group_plan_blocks").update({
                "day_of_week": proposed_day,
                "start_time": proposed_start,
                "end_time": proposed_end
            }).eq("group_id", group_id).eq("week_start", week_start).execute()
            
            # Update all member's weekly_plan_blocks
            for mid in member_ids:
                client.table("weekly_plan_blocks").update({
                    "day_of_week": proposed_day,
                    "start_time": proposed_start,
                    "end_time": proposed_end
                }).eq("user_id", mid).eq("work_type", "group").eq("course_number", change_request.get("course_number", "")).execute()
            
            # Mark request as approved
            client.table("group_meeting_change_requests").update({
                "status": "approved",
                "resolved_at": "NOW()"
            }).eq("id", request_id).execute()
            
            # Notify all members
            group_result = client.table("study_groups").select("group_name").eq("id", group_id).limit(1).execute()
            group_name = group_result.data[0].get("group_name", "Group") if group_result.data else "Group"
            
            for mid in member_ids:
                try:
                    client.table("notifications").insert({
                        "user_id": mid,
                        "type": "group_change_approved",
                        "title": f"שינוי מפגש אושר: {group_name}",
                        "message": f"כל חברי הקבוצה אישרו את השינוי. המפגש עודכן.",
                        "link": f"/schedule?week={week_start}",
                        "read": False
                    }).execute()
                except Exception as notif_err:
                    logging.error(f"Failed to notify member {mid}: {notif_err}")
            
            logging.info(f"✅ Change request {request_id} approved and applied!")
            
            return JSONResponse(content={
                "message": "All members approved! Change has been applied.",
                "status": "approved"
            })
        else:
            logging.info(f"📝 User {user_id} approved request {request_id}. Waiting for others...")
            return JSONResponse(content={
                "message": "Your approval recorded. Waiting for other members.",
                "status": "pending",
                "approved_count": len([a for a in approval_map.values() if a]),
                "total_members": len(member_ids)
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
        
        # Notify all members
        all_members = client.table("group_members").select("user_id").eq("group_id", group_id).eq("status", "approved").execute()
        member_ids = [m["user_id"] for m in (all_members.data or [])]
        
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
        
        # Enrich with group names and approval status
        enriched_requests = []
        for req in (requests.data or []):
            # Get group name
            group_result = client.table("study_groups").select("group_name").eq("id", req["group_id"]).limit(1).execute()
            group_name = group_result.data[0].get("group_name", "Group") if group_result.data else "Group"
            
            # Get requester name
            requester_result = client.table("user_profiles").select("name").eq("id", req["requested_by"]).limit(1).execute()
            requester_name = requester_result.data[0].get("name", "Someone") if requester_result.data else "Someone"
            
            # Check if current user has responded
            approval_check = client.table("group_change_approvals").select("approved").eq("request_id", req["id"]).eq("user_id", user_id).execute()
            user_response = approval_check.data[0] if approval_check.data else None
            
            enriched_requests.append({
                **req,
                "group_name": group_name,
                "requester_name": requester_name,
                "user_has_responded": user_response is not None,
                "user_approved": user_response["approved"] if user_response else None
            })
        
        return JSONResponse(content={"requests": enriched_requests})
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting pending change requests: {e}")
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
        
        notifications_result = supabase.table("notifications").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(50).execute()
        
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
        
        result = supabase.table("notifications").update({"read": True}).eq("id", notification_id).eq("user_id", user_id).execute()
        
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
        
        # DON'T mark notification as read automatically - let user decide when to remove it
        # Notifications will stay visible until user explicitly deletes them
        logging.info(f"ℹ️ Invitation accepted - notification will remain visible until user deletes it")
        
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
        
        return JSONResponse(content={"success": True, "message": "Invitation rejected"})
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error rejecting invitation: {e}")
        raise HTTPException(status_code=500, detail=f"Error rejecting invitation: {str(e)}")


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
