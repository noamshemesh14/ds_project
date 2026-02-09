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
        course_name: Optional[str] = None,
        user_prompt: Optional[str] = None,
        date: Optional[str] = None,
        week_start: Optional[str] = None,
        day_of_week: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        time_of_day: Optional[str] = None,
        original_duration: Optional[int] = None,
        proposed_duration: Optional[int] = None,
        request_type: Optional[str] = None,
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
                    group_query = client.table("study_groups").select("id, group_name, course_id, course_name")
                    if group_name:
                        group_query = group_query.ilike("group_name", f"%{group_name}%")
                    if course_number:
                        group_query = group_query.eq("course_id", course_number)
                    if course_name:
                        # Also filter by course_name if provided
                        group_query = group_query.ilike("course_name", f"%{course_name}%")
                    
                    groups_result = group_query.execute()
                    
                    # #region agent log
                    import json
                    try:
                        with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                            f.write(json.dumps({"runId":"run1","hypothesisId":"I","location":"app/agents/executors/request_handler.py:execute","message":"Groups found","data":{"groups_count":len(groups_result.data or []),"groups":[{"id":g.get("id"),"name":g.get("group_name")} for g in (groups_result.data or [])]},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                    except: pass
                    # #endregion
                    
                    if not groups_result.data:
                        raise HTTPException(status_code=404, detail=f"No group found matching: group_name={group_name}, course_number={course_number}, course_name={course_name}")
                    
                    # Try to find pending invitation or change request for any of these groups
                    for group in groups_result.data:
                        group_id = group["id"]
                        logger.info(f"🔍 Checking group {group_id} ({group.get('group_name')})")
                        
                        # First, try to find pending change request with more specific criteria
                        change_req_query = client.table("group_meeting_change_requests").select("id, week_start, proposed_day_of_week, proposed_start_time, proposed_end_time, original_day_of_week, original_start_time, original_end_time, original_duration_hours, proposed_duration_hours, request_type, status").eq("group_id", group_id)
                        
                        # #region agent log
                        try:
                            with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                f.write(json.dumps({"runId":"run1","hypothesisId":"J","location":"app/agents/executors/request_handler.py:execute","message":"BEFORE filtering by status","data":{"group_id":group_id,"search_params":{"week_start":week_start,"date":date,"day_of_week":day_of_week,"time_of_day":time_of_day,"start_time":start_time,"original_duration":original_duration,"proposed_duration":proposed_duration,"request_type":request_type}},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                        except: pass
                        # #endregion
                        
                        # Get ALL requests first (including non-pending) to see what's there
                        all_requests = change_req_query.order("created_at", desc=True).limit(10).execute()
                        
                        # #region agent log
                        try:
                            with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                f.write(json.dumps({"runId":"run1","hypothesisId":"J","location":"app/agents/executors/request_handler.py:execute","message":"ALL requests for group (before status filter)","data":{"group_id":group_id,"total_requests":len(all_requests.data or []),"requests":[{"id":r.get("id"),"status":r.get("status"),"week_start":r.get("week_start"),"day":r.get("proposed_day_of_week") or r.get("original_day_of_week"),"start":r.get("proposed_start_time") or r.get("original_start_time"),"original_duration":r.get("original_duration_hours"),"proposed_duration":r.get("proposed_duration_hours"),"type":r.get("request_type")} for r in (all_requests.data or [])]},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                        except: pass
                        # #endregion
                        
                        # Now filter by pending status
                        change_req_query = change_req_query.eq("status", "pending")
                        
                        # Use date/week_start if provided
                        if week_start:
                            change_req_query = change_req_query.eq("week_start", week_start)
                            logger.info(f"   Filtering by week_start: {week_start}")
                        elif date:
                            # Convert date to week_start (Sunday of that week)
                            from datetime import datetime, timedelta
                            try:
                                date_normalized = date.replace("/", "-")
                                date_obj = None
                                for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%d-%m-%y"]:
                                    try:
                                        date_obj = datetime.strptime(date_normalized, fmt)
                                        break
                                    except ValueError:
                                        continue
                                if date_obj:
                                    days_since_sunday = (date_obj.weekday() + 1) % 7
                                    sunday = date_obj - timedelta(days=days_since_sunday)
                                    week_start_calculated = sunday.strftime("%Y-%m-%d")
                                    change_req_query = change_req_query.eq("week_start", week_start_calculated)
                                    logger.info(f"   Converted date {date} to week_start: {week_start_calculated}")
                            except Exception as date_err:
                                logger.warning(f"   Could not parse date {date}: {date_err}")
                        
                        # Use day_of_week if provided - fetch all and filter in Python
                        # (Supabase doesn't support OR queries easily, so we'll filter after fetching)
                        logger.info(f"   Will filter by day_of_week: {day_of_week} after fetching")
                        
                        # Use time_of_day if provided (convert to approximate time range)
                        if time_of_day:
                            time_mapping = {
                                "morning": ("08:00", "12:00"),
                                "afternoon": ("12:00", "17:00"),
                                "evening": ("17:00", "21:00"),
                                "night": ("20:00", "23:00")
                            }
                            if time_of_day.lower() in time_mapping:
                                start_range, end_range = time_mapping[time_of_day.lower()]
                                # Filter by proposed_start_time or original_start_time in range
                                logger.info(f"   Filtering by time_of_day '{time_of_day}' (range: {start_range}-{end_range})")
                                # Note: Supabase doesn't support range queries easily, so we'll filter after fetching
                        
                        change_req_result = change_req_query.order("created_at", desc=True).execute()
                        
                        # #region agent log
                        try:
                            with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                f.write(json.dumps({"runId":"run1","hypothesisId":"K","location":"app/agents/executors/request_handler.py:execute","message":"Pending requests BEFORE filters","data":{"group_id":group_id,"pending_count":len(change_req_result.data or []),"requests":[{"id":r.get("id"),"week_start":r.get("week_start"),"day":r.get("proposed_day_of_week") or r.get("original_day_of_week"),"start":r.get("proposed_start_time") or r.get("original_start_time"),"original_duration":r.get("original_duration_hours"),"proposed_duration":r.get("proposed_duration_hours"),"type":r.get("request_type")} for r in (change_req_result.data or [])]},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                        except: pass
                        # #endregion
                        
                        # Filter by day_of_week if provided
                        if day_of_week is not None and change_req_result.data:
                            filtered_by_day = []
                            for req in change_req_result.data:
                                req_day = req.get("proposed_day_of_week") or req.get("original_day_of_week")
                                if req_day == day_of_week:
                                    filtered_by_day.append(req)
                            
                            if filtered_by_day:
                                change_req_result.data = filtered_by_day
                                logger.info(f"   Filtered to {len(filtered_by_day)} requests matching day_of_week={day_of_week}")
                            else:
                                change_req_result.data = []
                        
                        # Filter by start_time if provided (exact match or close)
                        if start_time and change_req_result.data:
                            filtered_by_time = []
                            # Normalize start_time to HH:MM format (remove seconds if present)
                            normalized_start_time = start_time
                            if len(start_time) > 5 and start_time[5] == ':':
                                normalized_start_time = start_time[:5]  # Take only HH:MM
                            
                            for req in change_req_result.data:
                                proposed_start = req.get("proposed_start_time", "")
                                original_start = req.get("original_start_time", "")
                                
                                # Normalize times from database (remove seconds if present)
                                normalized_proposed = proposed_start[:5] if proposed_start and len(proposed_start) > 5 and proposed_start[5] == ':' else proposed_start
                                normalized_original = original_start[:5] if original_start and len(original_start) > 5 and original_start[5] == ':' else original_start
                                
                                # Check if start_time matches either proposed or original (normalized)
                                if normalized_proposed == normalized_start_time or normalized_original == normalized_start_time:
                                    filtered_by_time.append(req)
                            
                            # #region agent log
                            try:
                                with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                    f.write(json.dumps({"runId":"run1","hypothesisId":"M","location":"app/agents/executors/request_handler.py:execute","message":"start_time filter","data":{"start_time":start_time,"normalized_start_time":normalized_start_time,"requests_before":len(change_req_result.data),"requests_after":len(filtered_by_time),"request_times":[{"id":r.get("id"),"proposed":r.get("proposed_start_time"),"original":r.get("original_start_time")} for r in change_req_result.data]},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                            except: pass
                            # #endregion
                            
                            if filtered_by_time:
                                change_req_result.data = filtered_by_time
                                logger.info(f"   Filtered to {len(filtered_by_time)} requests matching start_time={start_time}")
                            else:
                                change_req_result.data = []
                        
                        # Filter by time_of_day if provided
                        if time_of_day and change_req_result.data:
                            time_mapping = {
                                "morning": ("08:00", "12:00"),
                                "afternoon": ("12:00", "17:00"),
                                "evening": ("17:00", "21:00"),
                                "night": ("20:00", "23:00")
                            }
                            if time_of_day.lower() in time_mapping:
                                start_range, end_range = time_mapping[time_of_day.lower()]
                                filtered_requests = []
                                for req in change_req_result.data:
                                    # Check proposed_start_time or original_start_time
                                    proposed_start = req.get("proposed_start_time", "")
                                    original_start = req.get("original_start_time", "")
                                    start_to_check = proposed_start or original_start
                                    
                                    if start_to_check and start_range <= start_to_check < end_range:
                                        filtered_requests.append(req)
                                
                                if filtered_requests:
                                    change_req_result.data = filtered_requests
                                    logger.info(f"   Filtered to {len(filtered_requests)} requests matching time_of_day '{time_of_day}'")
                                else:
                                    change_req_result.data = []
                        
                        # Filter by original_duration and proposed_duration if provided (for resize requests)
                        if (original_duration is not None or proposed_duration is not None) and change_req_result.data:
                            filtered_by_duration = []
                            for req in change_req_result.data:
                                req_original_duration = req.get("original_duration_hours")
                                req_proposed_duration = req.get("proposed_duration_hours")
                                
                                # Check if durations match
                                original_match = original_duration is None or req_original_duration == original_duration
                                proposed_match = proposed_duration is None or req_proposed_duration == proposed_duration
                                
                                if original_match and proposed_match:
                                    filtered_by_duration.append(req)
                            
                            if filtered_by_duration:
                                change_req_result.data = filtered_by_duration
                                logger.info(f"   Filtered to {len(filtered_by_duration)} requests matching duration (original={original_duration}, proposed={proposed_duration})")
                            else:
                                change_req_result.data = []
                        
                        # Filter by request_type if provided
                        if request_type and change_req_result.data:
                            filtered_by_type = [req for req in change_req_result.data if req.get("request_type") == request_type]
                            if filtered_by_type:
                                change_req_result.data = filtered_by_type
                                logger.info(f"   Filtered to {len(filtered_by_type)} requests matching request_type={request_type}")
                            else:
                                change_req_result.data = []
                        
                        # #region agent log
                        try:
                            with open(r'c:\DS\AcademicPlanner\ds_project\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                f.write(json.dumps({"runId":"run1","hypothesisId":"L","location":"app/agents/executors/request_handler.py:execute","message":"Pending requests AFTER all filters","data":{"group_id":group_id,"final_count":len(change_req_result.data or []),"requests":[{"id":r.get("id"),"week_start":r.get("week_start"),"day":r.get("proposed_day_of_week") or r.get("original_day_of_week"),"start":r.get("proposed_start_time") or r.get("original_start_time"),"original_duration":r.get("original_duration_hours"),"proposed_duration":r.get("proposed_duration_hours"),"type":r.get("request_type")} for r in (change_req_result.data or [])]},"timestamp":int(__import__('time').time()*1000)}) + '\n')
                        except: pass
                        # #endregion
                        
                        if change_req_result.data:
                            # If multiple requests found, score them by how well they match
                            scored_requests = []
                            for req in change_req_result.data:
                                score = 0
                                
                                # Score by day_of_week match
                                req_day = req.get("proposed_day_of_week") or req.get("original_day_of_week")
                                if day_of_week is not None and req_day == day_of_week:
                                    score += 10
                                
                                # Score by start_time match
                                req_start = req.get("proposed_start_time") or req.get("original_start_time")
                                if start_time and req_start == start_time:
                                    score += 10
                                
                                # Score by duration match (for resize)
                                if original_duration is not None and req.get("original_duration_hours") == original_duration:
                                    score += 5
                                if proposed_duration is not None and req.get("proposed_duration_hours") == proposed_duration:
                                    score += 5
                                
                                # Score by request_type match
                                if request_type and req.get("request_type") == request_type:
                                    score += 3
                                
                                scored_requests.append((score, req))
                            
                            # Sort by score (highest first) and take the best match
                            scored_requests.sort(key=lambda x: x[0], reverse=True)
                            selected_request = scored_requests[0][1] if scored_requests else change_req_result.data[0]
                            best_score = scored_requests[0][0] if scored_requests else 0
                            
                            change_request_id = selected_request["id"]
                            logger.info(f"✅ Found pending change request: {change_request_id} for group {group_id} (score={best_score}, week_start={selected_request.get('week_start')}, day={selected_request.get('proposed_day_of_week') or selected_request.get('original_day_of_week')}, start={selected_request.get('proposed_start_time') or selected_request.get('original_start_time')}, type={selected_request.get('request_type')}, original_duration={selected_request.get('original_duration_hours')}, proposed_duration={selected_request.get('proposed_duration_hours')})")
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
                    
                    # Record the approval first
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
                    
                    # Now check if all members have approved
                    # Get all group members (except requester)
                    requester_id = change_request.get("requested_by")
                    all_members_result = client.table("group_members").select("user_id").eq("group_id", group_id).eq("status", "approved").execute()
                    member_ids = [m["user_id"] for m in (all_members_result.data or [])]
                    members_needing_approval = [mid for mid in member_ids if mid != requester_id]
                    
                    # Get all approvals
                    approvals = client.table("group_change_approvals").select("user_id, approved").eq("request_id", change_request_id).execute()
                    approval_map = {a["user_id"]: a["approved"] for a in (approvals.data or [])}
                    
                    # Check if all members (except requester) have approved
                    all_responded = all(mid in approval_map for mid in members_needing_approval)
                    all_approved = all_responded and all(approval_map.get(mid, False) for mid in members_needing_approval)
                    
                    logger.info(f"📊 Approval check: all_responded={all_responded}, all_approved={all_approved}, members_needing_approval={len(members_needing_approval)}, approvals={len(approval_map)}")
                    
                    if all_approved:
                        # All members approved! Apply the change by calling the internal function from main.py
                        logger.info(f"✅ All members approved! Applying change for request {change_request_id}")
                        
                        # If week_start is missing from change_request, try to calculate it from date
                        if not change_request.get("week_start") and date:
                            from datetime import datetime, timedelta
                            try:
                                date_normalized = date.replace("/", "-")
                                date_obj = None
                                for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%d-%m-%y"]:
                                    try:
                                        date_obj = datetime.strptime(date_normalized, fmt)
                                        break
                                    except ValueError:
                                        continue
                                if date_obj:
                                    days_since_sunday = (date_obj.weekday() + 1) % 7
                                    sunday = date_obj - timedelta(days=days_since_sunday)
                                    week_start_calculated = sunday.strftime("%Y-%m-%d")
                                    change_request["week_start"] = week_start_calculated
                                    logger.info(f"📅 Calculated and set week_start={week_start_calculated} from date={date}")
                            except Exception as date_err:
                                logger.warning(f"⚠️ Could not calculate week_start from date {date}: {date_err}")
                        
                        # Import the internal function from main.py
                        from app.main import _apply_group_change_request
                        
                        # Call the function to apply the change
                        await _apply_group_change_request(change_request_id, client, change_request, group_id, member_ids, requester_id)
                        
                        return {
                            "status": "success",
                            "message": "All members approved! Change has been applied.",
                            "applied": True
                        }
                    else:
                        # Not all members approved yet
                        approved_count = len([a for a in approval_map.values() if a])
                        total_needed = len(members_needing_approval)
                        
                        # Mark notification as read
                        try:
                            client.table("notifications").update({
                                "read": True
                            }).eq("user_id", user_id).eq("type", "group_change_request").like("link", f"%change_request={change_request_id}%").execute()
                        except Exception as notif_err:
                            logger.warning(f"Could not update notification: {notif_err}")
                        
                        return {
                            "status": "success",
                            "message": f"Your approval recorded. Waiting for other members ({approved_count}/{total_needed} approved).",
                            "applied": False,
                            "approved_count": approved_count,
                            "total_needed": total_needed
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
