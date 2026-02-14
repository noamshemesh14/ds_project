"""
Group Manager Executor
Manages study groups - creates groups and invites members
"""
import logging
from typing import Dict, Any, Optional, List
from app.supabase_client import supabase, supabase_admin
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class GroupManager:
    def __init__(self):
        self.module_name = "group_manager"

    async def execute(
        self,
        user_id: str,
        course_number: Optional[str] = None,
        course_name: Optional[str] = None,
        group_name: Optional[str] = None,
        invite_emails: Optional[List[str]] = None,
        description: Optional[str] = None,
        user_email: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a study group and invite members.
        
        Validations:
        - Only registered users can be invited
        - Invitees must be enrolled in the course
        - At least one user (other than creator) must be invited
        - Cannot invite yourself
        """
        try:
            client = supabase_admin if supabase_admin else supabase
            if not client:
                raise HTTPException(status_code=500, detail="Supabase client not configured")
            
            if not course_number:
                raise HTTPException(status_code=400, detail="course_number is required")
            
            if not group_name:
                raise HTTPException(status_code=400, detail="group_name is required")
            
            # Get user email if not provided
            if not user_email:
                user_profile = client.table("user_profiles").select("email").eq("id", user_id).limit(1).execute()
                if user_profile.data and user_profile.data[0].get("email"):
                    user_email = user_profile.data[0]["email"]
                else:
                    # Try to get from auth
                    try:
                        if supabase_admin:
                            auth_user = supabase_admin.auth.admin.get_user_by_id(user_id)
                            if hasattr(auth_user, 'user') and hasattr(auth_user.user, 'email'):
                                user_email = auth_user.user.email
                    except Exception as auth_err:
                        logger.warning(f"Could not get user email from auth: {auth_err}")
            
            if not user_email:
                raise HTTPException(status_code=400, detail="User email is required for group creation")
            
            logger.info(f"🔄 Creating group: {group_name} for course {course_number} (user: {user_id})")
            
            # Get course name if not provided
            if not course_name:
                catalog_result = client.table("course_catalog").select("course_name").eq("course_number", course_number).limit(1).execute()
                if catalog_result.data:
                    course_name = catalog_result.data[0].get("course_name", course_number)
                else:
                    course_name = course_number
            
            # Filter out current user's email and empty emails
            filtered_emails = []
            if invite_emails:
                user_email_lower = user_email.strip().lower()
                for email in invite_emails:
                    if not email or not email.strip():
                        continue
                    email_normalized = email.strip().lower()
                    if email_normalized != user_email_lower:
                        filtered_emails.append(email_normalized)
                    else:
                        logger.warning(f"⚠️ Skipping {email_normalized} - cannot invite yourself")
            
            # Validation: Must invite at least one user (other than yourself)
            if not filtered_emails:
                raise HTTPException(
                    status_code=400,
                    detail="You must invite at least one other user to the group. You cannot create a group with only yourself."
                )
            
            # Validate all emails are registered users
            valid_emails = []
            unregistered_emails = []
            
            all_registered_users = {}
            if supabase_admin:
                try:
                    auth_users = supabase_admin.auth.admin.list_users()
                    if hasattr(auth_users, 'users'):
                        for u in auth_users.users:
                            if hasattr(u, 'email') and u.email:
                                all_registered_users[u.email.lower()] = u
                    elif isinstance(auth_users, list):
                        for u in auth_users:
                            if hasattr(u, 'email') and u.email:
                                all_registered_users[u.email.lower()] = u
                    else:
                        for u in auth_users:
                            if hasattr(u, 'email') and u.email:
                                all_registered_users[u.email.lower()] = u
                    logger.info(f"   Found {len(all_registered_users)} registered users in system")
                except Exception as list_error:
                    logger.error(f"Error listing users: {list_error}")
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to validate user emails. Please try again."
                    )
            
            # Validate each email
            for email in filtered_emails:
                if email in all_registered_users:
                    valid_emails.append({
                        "email": email,
                        "user": all_registered_users[email]
                    })
                    logger.info(f"   ✅ {email} is registered")
                else:
                    unregistered_emails.append(email)
                    logger.warning(f"   ❌ {email} is NOT registered")
            
            # Reject if there are unregistered emails
            if unregistered_emails:
                error_msg = f"The following emails are not registered in the system: {', '.join(unregistered_emails)}. Only registered users can be invited to groups."
                raise HTTPException(status_code=400, detail=error_msg)
            
            # Validate that invitees are enrolled in the course
            creator_profile = client.table("user_profiles").select("current_semester, current_year").eq("id", user_id).execute()
            creator_semester = None
            creator_year = None
            if creator_profile.data and len(creator_profile.data) > 0:
                creator_semester = creator_profile.data[0].get("current_semester")
                creator_year = creator_profile.data[0].get("current_year")
            
            def extract_semester_season(semester_str):
                if not semester_str:
                    return None
                semester_str = str(semester_str).strip()
                if "חורף" in semester_str or "winter" in semester_str.lower():
                    return "חורף"
                elif "אביב" in semester_str or "spring" in semester_str.lower():
                    return "אביב"
                elif "קיץ" in semester_str or "summer" in semester_str.lower():
                    return "קיץ"
                return semester_str
            
            eligible_emails = []
            ineligible_emails = []
            
            if creator_semester and creator_year:
                creator_semester_season = extract_semester_season(creator_semester)
                logger.info(f"   Validating invitees for course {course_number} in semester {creator_semester} (season: {creator_semester_season}) year {creator_year}")
                
                for email_data in valid_emails:
                    email = email_data["email"]
                    invitee_user_id = email_data["user"].id
                    
                    # Check if invitee has this course in the same semester/year
                    invitee_courses = client.table("courses").select("*").eq("user_id", invitee_user_id).eq("course_number", course_number).execute()
                    
                    has_course_in_semester = False
                    if invitee_courses.data:
                        for course in invitee_courses.data:
                            course_semester = course.get("semester")
                            course_year = course.get("year")
                            course_semester_season = extract_semester_season(course_semester) if course_semester else None
                            
                            semester_matches = course_semester_season == creator_semester_season if course_semester_season and creator_semester_season else False
                            year_matches = not creator_year or not course_year or course_year == creator_year
                            
                            if semester_matches and year_matches:
                                has_course_in_semester = True
                                logger.info(f"   ✅ {email} is enrolled in course {course_number} for {creator_semester_season} {creator_year}")
                                break
                    
                    if has_course_in_semester:
                        eligible_emails.append(email_data)
                    else:
                        ineligible_emails.append(email)
                        logger.warning(f"   ❌ {email} is NOT enrolled in course {course_number} for {creator_semester_season} {creator_year}")
            else:
                # If creator doesn't have semester/year set, allow all (backward compatibility)
                logger.warning(f"   ⚠️ Creator's semester/year not set - allowing all invitees")
                eligible_emails = valid_emails
            
            # Reject if there are ineligible emails
            if ineligible_emails:
                creator_semester_season = extract_semester_season(creator_semester) if creator_semester else None
                error_msg = f"The following users are not enrolled in course {course_name} (course number: {course_number}) for the selected semester ({creator_semester_season or creator_semester} {creator_year}): {', '.join(ineligible_emails)}. Please make sure they have this course in their courses list for the same semester and year."
                raise HTTPException(status_code=400, detail=error_msg)
            
            # Final validation: Must have at least one eligible invitee
            if not eligible_emails:
                error_msg = "None of the invited users are enrolled in this course for the selected semester, or you must invite at least one other user."
                raise HTTPException(status_code=400, detail=error_msg)
            
            # CRITICAL: Check if user already has a group for this course
            # Check 1: Groups where user is the creator
            existing_groups_as_creator = client.table("study_groups").select("id, group_name").eq("created_by", user_id).eq("course_id", course_number).execute()
            if existing_groups_as_creator.data and len(existing_groups_as_creator.data) > 0:
                existing_group = existing_groups_as_creator.data[0]
                error_msg = f"You already have a group for this course: {existing_group.get('group_name')}. You can only create one group per course."
                logger.error(f"   ❌ {error_msg}")
                raise HTTPException(
                    status_code=400,
                    detail=error_msg
                )
            
            # Check 2: Groups where user is a member (approved)
            user_groups = client.table("group_members").select("group_id, status").eq("user_id", user_id).eq("status", "approved").execute()
            if user_groups.data:
                group_ids = [gm["group_id"] for gm in user_groups.data]
                if group_ids:
                    existing_groups_as_member = client.table("study_groups").select("id, group_name").eq("course_id", course_number).in_("id", group_ids).execute()
                    if existing_groups_as_member.data and len(existing_groups_as_member.data) > 0:
                        existing_group = existing_groups_as_member.data[0]
                        error_msg = f"You are already a member of a group for this course: {existing_group.get('group_name')}. You can only be in one group per course."
                        logger.error(f"   ❌ {error_msg}")
                        raise HTTPException(
                            status_code=400,
                            detail=error_msg
                        )
            
            # Check 3: Pending invitations where user is the inviter (creator)
            # Since group_id might be NULL, we need to check invitations with NULL group_id
            # Also check pending_group_creations to see if there's already a pending group for this course
            pending_invitations_as_inviter = client.table("group_invitations").select("id, group_id").eq("inviter_id", user_id).eq("status", "pending").execute()
            if pending_invitations_as_inviter.data:
                # Check if any of these invitations have NULL group_id (meaning group not created yet)
                # This indicates there's a pending group creation for this inviter
                has_null_group_id = any(inv.get("group_id") is None or str(inv.get("group_id", "")).strip().lower() in ["null", "none", ""] for inv in pending_invitations_as_inviter.data)
                if has_null_group_id:
                    # Check if the pending group is for the same course
                    try:
                        pending_creation = client.table("pending_group_creations").select("course_id").eq("inviter_id", user_id).eq("course_id", course_number).execute()
                        if pending_creation.data:
                            error_msg = f"You already have a pending group invitation for this course. Please wait for responses or cancel the existing invitation before creating a new group."
                            logger.error(f"   ❌ {error_msg}")
                            raise HTTPException(
                                status_code=400,
                                detail=error_msg
                            )
                    except Exception as pending_check_err:
                        # If table doesn't exist, just check by group_id
                        logger.warning(f"⚠️ Could not check pending_group_creations: {pending_check_err}")
                        error_msg = f"You already have a pending group invitation. Please wait for responses or cancel the existing invitation before creating a new group."
                        logger.error(f"   ❌ {error_msg}")
                        raise HTTPException(
                            status_code=400,
                            detail=error_msg
                        )
            
            # Check 4: Check if any of the invitees already have a group for this course
            for email_data in eligible_emails:
                invitee_user_id = email_data["user"].id
                
                # Check if invitee is creator of a group for this course
                invitee_groups_as_creator = client.table("study_groups").select("id, group_name").eq("created_by", invitee_user_id).eq("course_id", course_number).execute()
                if invitee_groups_as_creator.data and len(invitee_groups_as_creator.data) > 0:
                    existing_group = invitee_groups_as_creator.data[0]
                    error_msg = f"User {email_data['email']} already has a group for this course: {existing_group.get('group_name')}. They cannot be invited to another group for the same course."
                    logger.error(f"   ❌ {error_msg}")
                    raise HTTPException(
                        status_code=400,
                        detail=error_msg
                    )
                
                # Check if invitee is a member of a group for this course
                invitee_groups = client.table("group_members").select("group_id, status").eq("user_id", invitee_user_id).eq("status", "approved").execute()
                if invitee_groups.data:
                    invitee_group_ids = [gm["group_id"] for gm in invitee_groups.data]
                    if invitee_group_ids:
                        invitee_groups_as_member = client.table("study_groups").select("id, group_name").eq("course_id", course_number).in_("id", invitee_group_ids).execute()
                        if invitee_groups_as_member.data and len(invitee_groups_as_member.data) > 0:
                            existing_group = invitee_groups_as_member.data[0]
                            error_msg = f"User {email_data['email']} is already a member of a group for this course: {existing_group.get('group_name')}. They cannot be invited to another group for the same course."
                            logger.error(f"   ❌ {error_msg}")
                            raise HTTPException(
                                status_code=400,
                                detail=error_msg
                            )
            
            # CRITICAL: Group should only be created AFTER all invitees accept
            # We always have at least one eligible invitee (validated above)
            # The group will be created when all invitees accept (in accept_invitation)
            
            group_id = None
            group = None
            
            # Group will be created only after all invitees accept
            logger.info(f"   ✅ All {len(eligible_emails)} invitees are eligible. Group will be created after all accept invitations.")
            
            # CRITICAL: Store group creation metadata for later use
            # This allows us to preserve group_name, course_name, description when creating the group
            pending_group_creation_id = None
            if not group_id:  # Only if group not created yet
                try:
                    pending_creation_result = client.table("pending_group_creations").insert({
                        "inviter_id": user_id,
                        "course_id": course_number,
                        "course_name": course_name,
                        "group_name": group_name,
                        "description": description
                    }).execute()
                    if pending_creation_result.data:
                        pending_group_creation_id = pending_creation_result.data[0]['id']
                        logger.info(f"✅ Stored pending group creation metadata: {pending_group_creation_id}")
                except Exception as pending_err:
                    # If table doesn't exist, log warning but continue
                    logger.warning(f"⚠️ Could not store pending group creation (table may not exist): {pending_err}")
            
            # Create invitations for each eligible email
            invitations_created = []
            invitations_failed = []
            
            # Check if any emails from the original list are not in eligible_emails
            original_emails = [e.strip().lower() for e in (invite_emails or []) if e and e.strip()]
            eligible_email_list = [ed["email"] for ed in eligible_emails]
            missing_emails = [e for e in original_emails if e not in eligible_email_list]
            
            if missing_emails:
                for email in missing_emails:
                    # Check why it's missing
                    if email in unregistered_emails:
                        invitations_failed.append(f"{email} (not registered)")
                        logger.error(f"❌ {email} is not registered in the system")
                    elif email in ineligible_emails:
                        invitations_failed.append(f"{email} (not enrolled in course)")
                        logger.error(f"❌ {email} is not enrolled in course {course_number}")
                    else:
                        invitations_failed.append(f"{email} (unknown reason)")
                        logger.error(f"❌ {email} failed for unknown reason")
            
            for email_data in eligible_emails:
                email = email_data["email"]
                user_check = email_data["user"]
                
                try:
                    # Create invitation WITHOUT group_id (will be set when group is created)
                    invitation_data = {
                        "group_id": group_id,  # NULL if group not created yet
                        "inviter_id": user_id,
                        "invitee_email": email,
                        "invitee_user_id": user_check.id,
                        "status": "pending"
                    }
                    
                    invitation_result = client.table("group_invitations").insert(invitation_data).execute()
                    
                    if invitation_result.data:
                        invitation_id = invitation_result.data[0]['id']
                        invitations_created.append(email)
                        logger.info(f"✅ Created invitation for {email}")
                        
                        # Create notification with invitation_id (group_id may be NULL)
                        try:
                            notification_link = f"/my-courses?invitation={invitation_id}"
                            if group_id:
                                notification_link = f"/my-courses?group={group_id}&invitation={invitation_id}"
                            
                            client.table("notifications").insert({
                                "user_id": user_check.id,
                                "type": "group_invitation",
                                "title": f"Study group invitation: {group_name}",
                                "message": f"{user_email} invited you to join a study group for course {course_name}",
                                "link": notification_link,
                                "read": False
                            }).execute()
                        except Exception as notif_error:
                            logger.warning(f"Failed to create notification for {email}: {notif_error}")
                    else:
                        invitations_failed.append(f"{email} (insert returned no data)")
                        logger.error(f"❌ Failed to create invitation for {email}: insert returned no data")
                        
                except Exception as e:
                    error_msg = str(e)
                    invitations_failed.append(f"{email} ({error_msg})")
                    logger.error(f"Error inviting {email}: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
            
            if group:
                return {
                    "status": "success",
                    "message": f"Group '{group_name}' created successfully. {len(invitations_created)} invitation(s) sent.",
                    "group_id": group_id,
                    "group": group,
                    "invitations_created": invitations_created,
                    "invitations_failed": invitations_failed
                }
            else:
                return {
                    "status": "success",
                    "message": f"Invitations sent. Group will be created after all invitees accept. {len(invitations_created)} invitation(s) sent.",
                    "invitations_created": invitations_created,
                    "invitations_failed": invitations_failed
                }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error in group manager: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Error creating group: {str(e)}")

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
