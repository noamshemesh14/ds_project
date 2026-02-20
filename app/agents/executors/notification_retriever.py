"""
Notification Retriever Executor
Retrieves new notifications for user
"""
import logging
from typing import Dict, Any
from app.supabase_client import supabase, supabase_admin
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class NotificationRetriever:
    def __init__(self):
        self.module_name = "notification_retriever"

    async def execute(
        self,
        user_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        try:
            client = supabase_admin if supabase_admin else supabase
            if not client:
                raise HTTPException(status_code=500, detail="Supabase client not configured")
            
            logger.info(f"🔄 Retrieving unread notifications for user {user_id}")
            
            # Fetch all unread notifications for the user, ordered by creation date (newest first)
            result = client.table("notifications").select("*").eq("user_id", user_id).eq("read", False).order("created_at", desc=True).execute()
            
            notifications = result.data if result.data else []
            
            logger.info(f"✅ Found {len(notifications)} unread notification(s) for user {user_id}")
            
            if len(notifications) == 0:
                return {
                    "status": "success",
                    "message": "No unread notifications",
                    "notifications": [],
                    "count": 0
                }
            
            # Format notifications for display
            formatted_notifications = []
            for notif in notifications:
                formatted_notifications.append({
                    "id": notif.get("id"),
                    "type": notif.get("type"),
                    "title": notif.get("title"),
                    "message": notif.get("message"),
                    "link": notif.get("link"),
                    "created_at": notif.get("created_at")
                })
            
            # Build detailed message
            from datetime import datetime
            detailed_message = f"Found {len(notifications)} unread notification(s):\n\n"
            for idx, notif in enumerate(formatted_notifications, 1):
                detailed_message += f"{idx}. {notif.get('title', 'Notification')}\n"
                detailed_message += f"   {notif.get('message', '')}\n"
                if notif.get('created_at'):
                    try:
                        created_date = datetime.fromisoformat(notif['created_at'].replace('Z', '+00:00'))
                        detailed_message += f"   ({created_date.strftime('%Y-%m-%d %H:%M')})\n"
                    except:
                        detailed_message += f"   ({notif['created_at']})\n"
                detailed_message += "\n"
            
            return {
                "status": "success",
                "message": detailed_message,
                "notifications": formatted_notifications,
                "count": len(notifications)
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error retrieving notifications: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Error retrieving notifications: {str(e)}")

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
