"""
Courses Retriever Executor
Retrieves and displays all courses the user is taking this semester
"""
import logging
from typing import Dict, Any
from app.supabase_client import supabase, supabase_admin
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class CoursesRetriever:
    def __init__(self):
        self.module_name = "courses_retriever"

    async def execute(
        self,
        user_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        try:
            client = supabase_admin if supabase_admin else supabase
            if not client:
                raise HTTPException(status_code=500, detail="Supabase client not configured")
            
            logger.info(f"🔄 Retrieving courses for user {user_id}")
            
            # Fetch all courses for the user
            result = client.table("courses").select("course_number, course_name, credit_points").eq("user_id", user_id).order("course_number").execute()
            
            courses = result.data if result.data else []
            
            logger.info(f"✅ Found {len(courses)} course(s) for user {user_id}")
            
            if len(courses) == 0:
                return {
                    "status": "success",
                    "message": "No courses found for this semester",
                    "courses": [],
                    "count": 0
                }
            
            # Format courses for display
            formatted_courses = []
            total_credits = 0
            for course in courses:
                credit_points = course.get("credit_points", 0)
                total_credits += credit_points if credit_points else 0
                formatted_courses.append({
                    "course_number": course.get("course_number"),
                    "course_name": course.get("course_name"),
                    "credit_points": credit_points
                })
            
            # Build detailed message
            detailed_message = f"Found {len(courses)} course(s)"
            if total_credits > 0:
                detailed_message += f" ({total_credits} credit points total)"
            detailed_message += ":\n\n"
            for idx, course in enumerate(formatted_courses, 1):
                detailed_message += f"{idx}. {course.get('course_number', '')} - {course.get('course_name', '')}\n"
                if course.get('credit_points'):
                    detailed_message += f"   ({course.get('credit_points')} credit points)\n"
                detailed_message += "\n"
            
            return {
                "status": "success",
                "message": detailed_message,
                "courses": formatted_courses,
                "count": len(courses),
                "total_credit_points": total_credits
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error retrieving courses: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Error retrieving courses: {str(e)}")

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


