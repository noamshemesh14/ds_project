"""
Preference Updater Executor
Updates user study preferences from natural language prompt
"""
import logging
from typing import Dict, Any, Optional
from app.supabase_client import supabase, supabase_admin
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class PreferenceUpdater:
    def __init__(self):
        self.module_name = "preference_updater"

    async def execute(
        self,
        user_id: str,
        preferences_text: Optional[str] = None,
        user_prompt: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Update user study preferences from natural language prompt.
        
        Args:
            user_id: User ID
            preferences_text: Direct preferences text (if provided)
            user_prompt: User's natural language prompt about preferences
        """
        try:
            client = supabase_admin if supabase_admin else supabase
            if not client:
                raise HTTPException(status_code=500, detail="Supabase client not configured")
            
            # Use preferences_text if provided, otherwise use user_prompt
            study_preferences_raw = preferences_text or user_prompt or ""
            
            if not study_preferences_raw:
                raise HTTPException(status_code=400, detail="preferences_text or user_prompt is required")
            
            logger.info(f"🔄 Updating study preferences for user {user_id}")
            
            # Get existing preferences and schedule notes
            profile_result = client.table("user_profiles").select("study_preferences_raw, schedule_change_notes").eq("id", user_id).limit(1).execute()
            
            existing_preferences = ""
            schedule_notes = []
            if profile_result.data:
                existing_preferences = profile_result.data[0].get("study_preferences_raw", "") or ""
                schedule_notes = profile_result.data[0].get("schedule_change_notes", []) or []
            
            # Combine existing preferences with new ones (append if exists, otherwise replace)
            if existing_preferences:
                # Append new preferences to existing ones
                combined_preferences = f"{existing_preferences}\n\n{study_preferences_raw}"
            else:
                combined_preferences = study_preferences_raw
            
            # Update user profile with raw preferences
            profile_payload = {
                "id": user_id,
                "study_preferences_raw": combined_preferences
            }
            
            update_result = client.table("user_profiles").upsert(
                profile_payload,
                on_conflict="id"
            ).execute()
            
            logger.info(f"✅ Saved study preferences for user {user_id}: {len(combined_preferences)} chars")
            
            # Generate LLM summary of preferences + schedule notes
            # Import the function from main.py
            from app.main import _summarize_user_preferences_with_llm
            
            summary = await _summarize_user_preferences_with_llm(combined_preferences, schedule_notes)
            
            if summary:
                # Save the summary
                client.table("user_profiles").update({
                    "study_preferences_summary": summary
                }).eq("id", user_id).execute()
                logger.info(f"✅ Updated preferences summary for user {user_id}")
            
            return {
                "status": "success",
                "message": "Preferences updated successfully",
                "preferences_length": len(combined_preferences),
                "summary_generated": summary is not None,
                "was_appended": existing_preferences != ""
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error updating preferences: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise HTTPException(status_code=500, detail=f"Error updating preferences: {str(e)}")

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
