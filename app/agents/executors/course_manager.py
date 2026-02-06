"""
Course Manager Executor
Manages adding courses to user's course list
"""
import logging
from typing import Dict, Any, Optional
from app.supabase_client import supabase, supabase_admin
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class CourseManager:
    def __init__(self):
        self.module_name = "course_manager"

    async def execute(
        self,
        user_id: str,
        course_number: str,
        course_name: Optional[str] = None,
        semester: Optional[str] = None,
        year: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        try:
            client = supabase_admin if supabase_admin else supabase
            if not client:
                raise HTTPException(status_code=500, detail="Supabase client not configured")

            logger.info(f"🔍 Checking if course {course_number} exists in catalog")
            catalog_result = client.table("course_catalog").select("*").eq("course_number", course_number).execute()

            if not catalog_result.data or len(catalog_result.data) == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"Course with number {course_number} not found in catalog. Please verify the course number is correct."
                )

            course_catalog = catalog_result.data[0]
            catalog_course_name = course_catalog.get("course_name", course_number)
            credit_points = course_catalog.get("credit_points")

            if course_name and course_name.lower() != catalog_course_name.lower():
                raise HTTPException(
                    status_code=400,
                    detail=f"Course name mismatch. Provided '{course_name}' but catalog has '{catalog_course_name}' for course number {course_number}."
                )

            logger.info(f"✅ Found course in catalog: {catalog_course_name} ({course_number})")

            existing_course = client.table("courses").select("*").eq("user_id", user_id).eq("course_number", course_number).execute()

            if existing_course.data and len(existing_course.data) > 0:
                logger.warning(f"⚠️ User already has course {course_number}")
                return {
                    "status": "already_exists",
                    "message": f"Course {catalog_course_name} ({course_number}) already exists in your course list",
                    "course": existing_course.data[0]
                }

            # Apply default semester and year if not provided
            final_semester = semester if semester else "חורף"
            final_year = year if year else 2026

            course_data = {
                "user_id": user_id,
                "course_number": course_number,
                "course_name": catalog_course_name,
                "credit_points": credit_points,
                "semester": final_semester,
                "year": final_year,
                "is_passed": False,
                "retake_count": 0
            }

            logger.info(f"➕ Adding course {course_number} to user {user_id} for {final_semester} {final_year}")
            result = client.table("courses").insert(course_data).execute()

            if not result.data or len(result.data) == 0:
                raise HTTPException(status_code=500, detail="Failed to add course")

            added_course = result.data[0]
            logger.info(f"✅ Successfully added course {course_number} to user {user_id}")

            return {
                "status": "success",
                "message": f"Course {catalog_course_name} ({course_number}) successfully added to your course list for {final_semester} {final_year}",
                "course": added_course
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error adding course: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Error adding course: {str(e)}")

    def get_step_log(
        self,
        prompt: Dict[str, Any],
        response: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "module": self.module_name,
            "prompt": prompt,
            "response": response
        }
