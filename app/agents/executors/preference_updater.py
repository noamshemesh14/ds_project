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
            logger.info(f"   Using client: {'supabase_admin' if supabase_admin else 'supabase'}")
            logger.info(f"   Input text: {study_preferences_raw[:100]}..." if len(study_preferences_raw) > 100 else f"   Input text: {study_preferences_raw}")
            
            # Get existing preferences, schedule notes, and current summary
            logger.info(f"   Checking if user profile exists for user_id={user_id} (type: {type(user_id)})")
            profile_result = client.table("user_profiles").select("id, study_preferences_raw, schedule_change_notes, study_preferences_summary").eq("id", user_id).limit(1).execute()
            
            existing_preferences = ""
            schedule_notes = []
            existing_summary = {}
            if profile_result.data:
                profile_id = profile_result.data[0].get("id")
                existing_preferences = profile_result.data[0].get("study_preferences_raw", "") or ""
                schedule_notes = profile_result.data[0].get("schedule_change_notes", []) or []
                existing_summary = profile_result.data[0].get("study_preferences_summary") or {}
                if not isinstance(existing_summary, dict):
                    existing_summary = {}
                logger.info(f"   ✅ Found existing profile: id={profile_id}, preferences_length={len(existing_preferences)}, notes_count={len(schedule_notes)}, summary_keys={list(existing_summary.keys()) if existing_summary else 'none'}")
                logger.info(f"   Profile ID match: {profile_id == user_id}")
            else:
                logger.warning(f"   ⚠️ No existing profile found for user {user_id}")
                logger.warning(f"   Will try to create/update profile using upsert")
            
            # Combine existing preferences with new ones (append if exists, otherwise replace)
            if existing_preferences:
                # Append new preferences to existing ones
                combined_preferences = f"{existing_preferences}\n\n{study_preferences_raw}"
            else:
                combined_preferences = study_preferences_raw
            
            # Update user profile with raw preferences
            # Use upsert to ensure it works whether profile exists or not
            logger.info(f"   Attempting to upsert user_profiles table for user_id={user_id}")
            logger.info(f"   Combined preferences length: {len(combined_preferences)} chars")
            
            try:
                profile_payload = {
                    "id": user_id,
                    "study_preferences_raw": combined_preferences
                }
                
                logger.info(f"   Upsert payload: id={user_id}, preferences_length={len(combined_preferences)}")
                upsert_result = client.table("user_profiles").upsert(
                    profile_payload,
                    on_conflict="id"
                ).execute()
                
                logger.info(f"   Upsert result: {upsert_result}")
                logger.info(f"   Upsert result.data: {upsert_result.data}")
                logger.info(f"   Upsert result.data type: {type(upsert_result.data)}")
                if upsert_result.data:
                    logger.info(f"   Upsert result.data[0]: {upsert_result.data[0]}")
                
                # Always verify by reading back (Supabase might return empty list even on success)
                logger.info(f"   Verifying upsert by reading back from database...")
                verify_result = client.table("user_profiles").select("id, study_preferences_raw, schedule_change_notes, study_preferences_summary").eq("id", user_id).limit(1).execute()
                
                if verify_result.data:
                    saved_id = verify_result.data[0].get("id")
                    saved_preferences = verify_result.data[0].get("study_preferences_raw", "")
                    saved_notes = verify_result.data[0].get("schedule_change_notes", [])
                    saved_summary = verify_result.data[0].get("study_preferences_summary")
                    
                    logger.info(f"   ✅ Profile found after upsert: id={saved_id}")
                    logger.info(f"   Saved preferences length: {len(saved_preferences)} chars")
                    logger.info(f"   Saved notes count: {len(saved_notes) if isinstance(saved_notes, list) else 'N/A'}")
                    logger.info(f"   Saved summary: {saved_summary is not None}")
                    
                    if saved_preferences == combined_preferences:
                        logger.info(f"   ✅ Verified: preferences saved correctly ({len(saved_preferences)} chars)")
                    else:
                        logger.error(f"   ❌ Verification FAILED: saved length={len(saved_preferences)}, expected length={len(combined_preferences)}")
                        logger.error(f"   Saved preview (first 200 chars): {saved_preferences[:200]}")
                        logger.error(f"   Expected preview (first 200 chars): {combined_preferences[:200]}")
                        raise HTTPException(
                            status_code=500,
                            detail=f"Preferences were not saved correctly. Saved: {len(saved_preferences)} chars, Expected: {len(combined_preferences)} chars"
                        )
                else:
                    logger.error(f"   ❌ Could not verify upsert - profile not found after upsert for user_id={user_id}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Profile not found after upsert for user_id={user_id}"
                    )
                    
            except HTTPException:
                raise
            except Exception as update_error:
                logger.error(f"   ❌ Error during upsert: {update_error}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Error updating preferences: {str(update_error)}"
                )
            
            # Generate LLM summary of preferences + schedule notes
            # Import the function from main.py
            from app.main import _summarize_user_preferences_with_llm
            
            logger.info(f"   Generating/updating LLM summary...")
            logger.info(f"   - Combined preferences length: {len(combined_preferences)} chars")
            logger.info(f"   - Schedule notes count: {len(schedule_notes)}")
            logger.info(f"   - Existing summary keys: {list(existing_summary.keys()) if existing_summary else 'none'}")
            
            # Get new summary from LLM (it will merge with existing if needed)
            try:
                new_summary = await _summarize_user_preferences_with_llm(combined_preferences, schedule_notes, existing_summary)
                summary_generated = new_summary is not None
                logger.info(f"   - LLM call result: summary_generated={summary_generated}")
                if new_summary:
                    logger.info(f"   - New summary type: {type(new_summary)}, keys: {list(new_summary.keys())}")
                else:
                    logger.warning(f"   - ⚠️ LLM returned None - check logs above for errors")
            except Exception as llm_err:
                logger.error(f"   ❌ LLM call failed: {llm_err}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                new_summary = None
                summary_generated = False
            
            # Merge new summary with existing summary
            if new_summary:
                logger.info(f"   New summary generated: {type(new_summary)}, keys: {list(new_summary.keys())}")
                
                # Merge: new summary overrides existing, but keep existing fields that aren't in new
                if existing_summary:
                    merged_summary = existing_summary.copy()
                    merged_summary.update(new_summary)  # New values override existing
                    logger.info(f"   Merged summary: existing keys preserved, new keys added/updated")
                else:
                    merged_summary = new_summary
                    logger.info(f"   No existing summary - using new summary as-is")
                
                # Use update since we already have the profile from the first upsert
                logger.info(f"   Updating study_preferences_summary for user_id={user_id}")
                logger.info(f"   - Merged summary keys: {list(merged_summary.keys()) if isinstance(merged_summary, dict) else 'not a dict'}")
                logger.info(f"   - Merged summary preview: {str(merged_summary)[:300]}")
                
                try:
                    summary_update_result = client.table("user_profiles").update({
                        "study_preferences_summary": merged_summary
                    }).eq("id", user_id).execute()
                    
                    logger.info(f"   Summary update result: {summary_update_result}")
                    logger.info(f"   - Update result.data: {summary_update_result.data}")
                    logger.info(f"   - Update result.data type: {type(summary_update_result.data)}")
                    if summary_update_result.data:
                        logger.info(f"   - Updated rows: {len(summary_update_result.data)}")
                except Exception as update_err:
                    logger.error(f"   ❌ Update failed: {update_err}")
                    import traceback
                    logger.error(f"   Traceback: {traceback.format_exc()}")
                    raise
                
                # Verify summary was saved
                summary_verify = client.table("user_profiles").select("study_preferences_summary").eq("id", user_id).limit(1).execute()
                if summary_verify.data:
                    saved_summary = summary_verify.data[0].get("study_preferences_summary")
                    if saved_summary:
                        logger.info(f"   ✅ Verified: summary saved correctly with {len(list(saved_summary.keys()) if isinstance(saved_summary, dict) else [])} keys")
                    else:
                        logger.warning(f"   ⚠️ Summary verification failed: summary is None after update")
                else:
                    logger.warning(f"   ⚠️ Could not verify summary update - profile not found")
            else:
                logger.warning(f"   ⚠️ No summary generated by LLM - keeping existing summary if available")
                logger.warning(f"   ⚠️ This means _summarize_user_preferences_with_llm returned None")
                logger.warning(f"   ⚠️ Check server logs for [LLM CLASSIFICATION] errors above")
                if existing_summary:
                    logger.info(f"   Keeping existing summary with {len(list(existing_summary.keys()))} keys")
                else:
                    logger.warning(f"   ⚠️ No existing summary either - user will have empty summary!")
            
            return {
                "status": "success",
                "message": "Preferences updated successfully",
                "preferences_length": len(combined_preferences),
                "summary_generated": summary_generated,
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
