"""
Request Handler Executor
Handles approval/rejection of requests (group invitations and change requests)
"""
import logging
from typing import Dict, Any, Optional
from app.supabase_client import supabase, supabase_admin
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class RequestHandler:
    def __init__(self):
        self.module_name = "request_handler"

    async def execute(
        self,
        user_id: str,
        request_id: Optional[str] = None,
        action: Optional[str] = None,
        group_name: Optional[str] = None,
        course_number: Optional[str] = None,
        user_prompt: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Handle approval/rejection of requests.
        
        Supports:
        1. Group invitations - find by request_id, group_name, or course_number
        2. Group change requests - find by request_id
        
        Actions: "accept", "approve", "reject", "decline"
        """
        try:
            client = supabase_admin if supabase_admin else supabase
            if not client:
                raise HTTPException(status_code=500, detail="Supabase client not configured")
            
            if not action:
                raise HTTPException(status_code=400, detail="action is required (accept/approve/reject/decline)")
            
            # Normalize action
            action_lower = action.lower().strip()
            is_approve = action_lower in ["accept", "approve", "אישור", "אשר"]
            is_reject = action_lower in ["reject", "decline", "דחייה", "דחה"]
            
            if not is_approve and not is_reject:
                raise HTTPException(status_code=400, detail=f"Invalid action: {action}. Use 'accept'/'approve' or 'reject'/'decline'")
            
            # Try to extract group_name from user_prompt if not provided
            if not group_name and user_prompt:
                import re
                # Look for patterns like "for group X", "קבוצת X", "group named X"
                group_patterns = [
                    r'group\s+([^"\']+)',
                    r'קבוצת\s+([^"\']+)',
                    r'for group\s+([^"\']+)',
                    r'קבוצה\s+([^"\']+)',
                ]
                for pattern in group_patterns:
                    match = re.search(pattern, user_prompt, re.IGNORECASE)
                    if match:
                        extracted_name = match.group(1).strip()
                        # Remove common trailing words
                        extracted_name = re.sub(r'\s+(invitation|הזמנה|for|עבור).*$', '', extracted_name, flags=re.IGNORECASE)
                        if extracted_name and len(extracted_name) > 2:
                            group_name = extracted_name
                            logger.info(f"📝 Extracted group_name from user_prompt: {group_name}")
                            break
            
            logger.info(f"🔄 Handling request: request_id={request_id}, action={action}, group_name={group_name}, course_number={course_number}")
            
            # Try to find invitation if request_id not provided
            invitation_id = None
            change_request_id = None
            
            if request_id:
                # Check if it's an invitation or change request
                invitation_check = client.table("group_invitations").select("id").eq("id", request_id).eq("invitee_user_id", user_id).limit(1).execute()
                if invitation_check.data:
                    invitation_id = request_id
                    logger.info(f"✅ Found invitation: {invitation_id}")
                else:
                    change_request_check = client.table("group_meeting_change_requests").select("id").eq("id", request_id).limit(1).execute()
                    if change_request_check.data:
                        change_request_id = request_id
                        logger.info(f"✅ Found change request: {change_request_id}")
                    else:
                        raise HTTPException(status_code=404, detail="Request not found")
            else:
                # Try to find invitation or change request by group_name or course_number
                if group_name or course_number:
                    logger.info(f"🔍 Searching for invitation or change request by group_name={group_name}, course_number={course_number}")
                    
                    # Find groups matching the criteria
                    group_query = client.table("study_groups").select("id, group_name, course_id")
                    if group_name:
                        group_query = group_query.ilike("group_name", f"%{group_name}%")
                    if course_number:
                        group_query = group_query.eq("course_id", course_number)
                    
                    groups_result = group_query.execute()
                    
                    if not groups_result.data:
                        raise HTTPException(status_code=404, detail=f"No group found matching: group_name={group_name}, course_number={course_number}")
                    
                    # Try to find pending invitation or change request for any of these groups
                    for group in groups_result.data:
                        group_id = group["id"]
                        logger.info(f"🔍 Checking group {group_id} ({group.get('group_name')})")
                        
                        # First, try to find pending change request
                        change_req_result = client.table("group_meeting_change_requests").select("id").eq("group_id", group_id).eq("status", "pending").order("created_at", desc=True).limit(1).execute()
                        
                        if change_req_result.data:
                            change_request_id = change_req_result.data[0]["id"]
                            logger.info(f"✅ Found pending change request: {change_request_id} for group {group_id}")
                            break
                        
                        # If no change request, try to find pending invitation
                        inv_result = client.table("group_invitations").select("id").eq("group_id", group_id).eq("invitee_user_id", user_id).eq("status", "pending").order("created_at", desc=True).limit(1).execute()
                        
                        if inv_result.data:
                            invitation_id = inv_result.data[0]["id"]
                            logger.info(f"✅ Found pending invitation: {invitation_id} for group {group_id}")
                            break
                    
                    if not invitation_id and not change_request_id:
                        raise HTTPException(status_code=404, detail=f"No pending invitation or change request found for group matching: group_name={group_name}, course_number={course_number}")
            
            # Handle invitation
            if invitation_id:
                if is_approve:
                    # Accept invitation
                    logger.info(f"✅ Accepting invitation {invitation_id}")
                    
                    # Get invitation
                    inv_result = client.table("group_invitations").select("*").eq("id", invitation_id).eq("invitee_user_id", user_id).eq("status", "pending").execute()
                    if not inv_result.data:
                        raise HTTPException(status_code=404, detail="Invitation not found or already processed")
                    
                    invitation = inv_result.data[0]
                    group_id = invitation.get('group_id')
                    
                    # Update invitation status
                    client.table("group_invitations").update({
                        "status": "accepted",
                        "responded_at": "now()"
                    }).eq("id", invitation_id).execute()
                    
                    # Add user to group members
                    import re
                    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)
                    
                    group_id_str = str(group_id).strip()
                    user_id_str = str(user_id).strip()
                    
                    if not uuid_pattern.match(group_id_str) or not uuid_pattern.match(user_id_str):
                        raise HTTPException(status_code=400, detail="Invalid ID format")
                    
                    # Check if member already exists
                    existing = client.table("group_members").select("*").eq("group_id", group_id_str).eq("user_id", user_id_str).execute()
                    
                    if existing.data:
                        # Update existing member
                        client.table("group_members").update({
                            "status": "approved"
                        }).eq("group_id", group_id_str).eq("user_id", user_id_str).execute()
                    else:
                        # Insert new member
                        member_data = {
                            "group_id": group_id_str,
                            "user_id": user_id_str,
                            "status": "approved"
                        }
                        inviter_id = invitation.get("inviter_id")
                        if inviter_id:
                            inviter_str = str(inviter_id).strip()
                            if inviter_str and inviter_str.lower() not in ["null", "none", ""] and uuid_pattern.match(inviter_str):
                                member_data["invited_by"] = inviter_str
                        
                        client.table("group_members").insert(member_data).execute()
                    
                    # Mark notification as read
                    try:
                        client.table("notifications").update({
                            "read": True
                        }).eq("user_id", user_id).eq("type", "group_invitation").like("link", f"%invitation={invitation_id}%").execute()
                    except Exception as notif_err:
                        logger.warning(f"Could not update notification: {notif_err}")
                    
                    return {
                        "status": "success",
                        "message": "Invitation accepted successfully"
                    }
                else:
                    # Reject invitation
                    logger.info(f"❌ Rejecting invitation {invitation_id}")
                    
                    result = client.table("group_invitations").update({
                        "status": "rejected",
                        "responded_at": "now()"
                    }).eq("id", invitation_id).eq("invitee_user_id", user_id).eq("status", "pending").execute()
                    
                    if not result.data:
                        raise HTTPException(status_code=404, detail="Invitation not found or already processed")
                    
                    # Mark related notifications as read
                    try:
                        client.table("notifications").update({
                            "read": True
                        }).eq("user_id", user_id).eq("type", "group_invitation").like("link", f"%invitation={invitation_id}%").execute()
                    except Exception as notif_err:
                        logger.warning(f"Could not update notifications: {notif_err}")
                    
                    return {
                        "status": "success",
                        "message": "Invitation rejected"
                    }
            
            # Handle change request
            elif change_request_id:
                # Get the change request
                request_result = client.table("group_meeting_change_requests").select("*").eq("id", change_request_id).limit(1).execute()
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
                
                if is_approve:
                    logger.info(f"✅ Approving change request {change_request_id}")
                    
                    # Record the approval
                    try:
                        client.table("group_change_approvals").insert({
                            "request_id": change_request_id,
                            "user_id": user_id,
                            "approved": True
                        }).execute()
                    except Exception:
                        # Might already exist
                        client.table("group_change_approvals").update({
                            "approved": True,
                            "responded_at": "NOW()"
                        }).eq("request_id", change_request_id).eq("user_id", user_id).execute()
                    
                    # Mark notification as read
                    try:
                        client.table("notifications").update({
                            "read": True
                        }).eq("user_id", user_id).eq("type", "group_change_request").like("link", f"%change_request={change_request_id}%").execute()
                    except Exception as notif_err:
                        logger.warning(f"Could not update notification: {notif_err}")
                    
                    # Note: The actual change application happens when all members approve
                    # This is handled by the approve_group_change_request endpoint
                    # For now, we just record the approval
                    
                    return {
                        "status": "success",
                        "message": "Change request approved. Waiting for all members to approve."
                    }
                else:
                    logger.info(f"❌ Rejecting change request {change_request_id}")
                    
                    # Record the rejection
                    try:
                        client.table("group_change_approvals").insert({
                            "request_id": change_request_id,
                            "user_id": user_id,
                            "approved": False
                        }).execute()
                    except Exception:
                        client.table("group_change_approvals").update({
                            "approved": False,
                            "responded_at": "NOW()"
                        }).eq("request_id", change_request_id).eq("user_id", user_id).execute()
                    
                    # Mark request as rejected
                    client.table("group_meeting_change_requests").update({
                        "status": "rejected",
                        "resolved_at": "NOW()"
                    }).eq("id", change_request_id).execute()
                    
                    # Mark notification as read
                    try:
                        client.table("notifications").update({
                            "read": True
                        }).eq("user_id", user_id).eq("type", "group_change_request").like("link", f"%change_request={change_request_id}%").execute()
                    except Exception as notif_err:
                        logger.warning(f"Could not update notification: {notif_err}")
                    
                    return {
                        "status": "success",
                        "message": "Change request rejected"
                    }
            else:
                raise HTTPException(status_code=400, detail="Could not find invitation or change request. Please provide request_id, group_name, or course_number")
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error handling request: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Error handling request: {str(e)}")

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
