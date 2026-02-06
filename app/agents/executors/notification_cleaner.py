"""
Notification Cleaner Executor
Cleans/deletes notifications
"""
import logging
from typing import Dict, Any, Optional
from app.supabase_client import supabase, supabase_admin
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class NotificationCleaner:
    def __init__(self):
        self.module_name = "notification_cleaner"

    async def execute(
        self,
        user_id: str,
        notification_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        try:
            client = supabase_admin if supabase_admin else supabase
            if not client:
                raise HTTPException(status_code=500, detail="Supabase client not configured")
            
            # If a specific notification_id is provided, mark only that one as read
            if notification_id:
                logger.info(f"🔄 Marking notification {notification_id} as read for user {user_id}")
                result = client.table("notifications").update({"read": True}).eq("id", notification_id).eq("user_id", user_id).execute()
                
                if not result.data or len(result.data) == 0:
                    raise HTTPException(status_code=404, detail=f"Notification {notification_id} not found or does not belong to user")
                
                logger.info(f"✅ Notification {notification_id} marked as read")
                return {
                    "status": "success",
                    "message": f"Notification marked as read",
                    "notification_id": notification_id,
                    "marked_count": 1
                }
            
            # Otherwise, mark all unread notifications as read
            logger.info(f"🔄 Marking all unread notifications as read for user {user_id}")
            
            # Mark all unread notifications as read
            result = client.table("notifications").update({"read": True}).eq("user_id", user_id).eq("read", False).execute()
            
            marked_count = len(result.data) if result.data else 0
            
            if marked_count == 0:
                logger.info(f"✅ No unread notifications to mark for user {user_id}")
                return {
                    "status": "success",
                    "message": "No unread notifications to mark",
                    "marked_count": 0
                }
            
            logger.info(f"✅ Marked {marked_count} notification(s) as read for user {user_id}")
            
            return {
                "status": "success",
                "message": f"Marked {marked_count} notification(s) as read",
                "marked_count": marked_count
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error cleaning notifications: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Error cleaning notifications: {str(e)}")

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
