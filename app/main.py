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
    ConstraintCreate, Constraint, ChatMessage, ChatResponse,
    StudyGroupCreate, StudyGroup, GroupInvitationResponse, Notification,
    Assignment, AssignmentCreate
)
from app.parser import TranscriptParser
from app.supabase_client import supabase, supabase_admin
from app.auth import get_current_user, get_optional_user
from dotenv import load_dotenv
import sys
import logging

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
        user_id = current_user["id"]
        logging.info(f"📥 Loading user data for user_id: {user_id}")
        
        # Use service_role client if available, otherwise anon client
        client = supabase_admin if supabase_admin else supabase
        
        if not client:
            raise HTTPException(status_code=500, detail="Supabase client not configured")
        
        # Get user profile
        try:
            profile_result = client.table("user_profiles").select("*").eq("id", user_id).execute()
            if not profile_result.data or len(profile_result.data) == 0:
                logging.info(f"   No profile found for user {user_id}")
                return JSONResponse(content={
                    "student_info": None,
                    "courses": [],
                    "metadata": {"has_data": False}
                })
            
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
        for course in courses:
            courses_list.append({
                "course_name": course.get("course_name", ""),
                "course_number": course.get("course_number", ""),
                "credit_points": course.get("credit_points"),
                "grade": course.get("grade"),
                "letter_grade": course.get("letter_grade"),
                "semester": course.get("semester"),
                "year": course.get("year"),
                "notes": course.get("notes", ""),
                "is_passed": course.get("is_passed", False),
                "retake_count": course.get("retake_count", 0)
            })
        
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
            "end_time": constraint_data.end_time
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
            "end_time": constraint_data.end_time
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
        
        # If no valid emails provided, reject (user must invite at least one person)
        if not valid_emails:
            if self_invite_attempted:
                error_msg = "You cannot invite yourself to a group. Please invite at least one other registered user."
            else:
                error_msg = "You must invite at least one registered user to create a group."
            logging.error(f"   ❌ {error_msg}")
            raise HTTPException(
                status_code=400,
                detail=error_msg
            )
        
        # NOW create the group (only if all emails are valid)
        logging.info(f"   ✅ All {len(valid_emails)} emails are valid. Creating group...")
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
        
        # Create invitations for each VALIDATED email
        invitations_created = []
        invitations_failed = []
        
        for email_data in valid_emails:
            email = email_data["email"]
            user_check = email_data["user"]
            
            try:
                # Create invitation (user is already validated)
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
        user_id = current_user.get('sub')
        
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")
        
        # Get groups where user is a member
        members_result = supabase.table("group_members").select("group_id").eq("user_id", user_id).eq("status", "approved").execute()
        member_group_ids = [m['group_id'] for m in (members_result.data or [])]
        
        # Get groups created by user
        created_groups = supabase.table("study_groups").select("*").eq("created_by", user_id).execute()
        created_group_ids = [g['id'] for g in (created_groups.data or [])]
        
        # Combine group IDs
        all_group_ids = list(set(member_group_ids + created_group_ids))
        
        # Get all groups
        all_groups = {}
        if all_group_ids:
            groups_result = supabase.table("study_groups").select("*").in_("id", all_group_ids).execute()
            for group in (groups_result.data or []):
                all_groups[group['id']] = group
        
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
        
        return JSONResponse(content={"groups": list(all_groups.values())})
        
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
