"""
Supervisor - Main task router for the agent system
Routes user prompts to appropriate executors using LLM or pattern matching
"""
import logging
import re
from typing import Dict, Any, List, Optional
from fastapi import HTTPException
from app.agents.executors.course_manager import CourseManager
from app.agents.executors.schedule_retriever import ScheduleRetriever
from app.agents.executors.group_manager import GroupManager
from app.agents.executors.notification_retriever import NotificationRetriever
from app.agents.executors.notification_cleaner import NotificationCleaner
from app.agents.executors.request_handler import RequestHandler
from app.agents.executors.preference_updater import PreferenceUpdater
from app.agents.executors.block_mover import BlockMover
from app.agents.executors.block_resizer import BlockResizer
from app.agents.executors.block_creator import BlockCreator
from app.agents.executors.constraint_manager import ConstraintManager
from app.agents.llm_client import LLMClient

logger = logging.getLogger(__name__)

# Helper function for debug logging
def _write_debug_log(session_id, run_id, hypothesis_id, location, message, data):
    import json
    import os as os_module
    try:
        log_dir = r'c:\DS\AcademicPlanner\ds_project\.cursor'
        os_module.makedirs(log_dir, exist_ok=True)
        log_file = os_module.path.join(log_dir, 'debug.log')
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                "sessionId": session_id,
                "runId": run_id,
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(__import__('time').time()*1000)
            })+'\n')
    except Exception as log_err:
        logger.warning(f"Failed to write debug log: {log_err}")


class Supervisor:
    def __init__(self):
        self.executors = {
            "course_manager": CourseManager(),
            "schedule_retriever": ScheduleRetriever(),
            "group_manager": GroupManager(),
            "notification_retriever": NotificationRetriever(),
            "notification_cleaner": NotificationCleaner(),
            "request_handler": RequestHandler(),
            "preference_updater": PreferenceUpdater(),
            "block_mover": BlockMover(),
            "block_resizer": BlockResizer(),
            "block_creator": BlockCreator(),
            "constraint_manager": ConstraintManager(),
        }
        self.module_name = "supervisor"
        self.llm_client = LLMClient()

    async def route_task(
        self,
        user_prompt: str,
        user_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        steps: List[Dict[str, Any]] = []

        try:
            # Use LLM for intelligent routing and parameter extraction
            # #region agent log
            _write_debug_log("debug-session", "supervisor", "P", "supervisor.py:route_task", "Supervisor routing started", {"user_prompt": user_prompt, "has_llm_client": bool(self.llm_client), "llm_client_has_client": bool(self.llm_client.client) if self.llm_client else False, "llm_model": self.llm_client.model if self.llm_client else None})
            # #endregion

            logger.info(f"🔍 Routing task with LLM: {user_prompt}")
            logger.info(f"   LLM client initialized: {self.llm_client.client is not None}")
            logger.info(f"   LLM model: {self.llm_client.model}")

            llm_routing_result = await self.llm_client.route_task(user_prompt)

            # #region agent log
            _write_debug_log("debug-session", "supervisor", "Q", "supervisor.py:route_task", "LLM routing result received", {"executor_name": llm_routing_result.get("executor_name"), "has_error": bool(llm_routing_result.get("error")), "error": llm_routing_result.get("error"), "params": llm_routing_result.get("executor_params",{})})
            # #endregion

            logger.info(f"   LLM routing result: {llm_routing_result}")

            executor_name = llm_routing_result.get("executor_name")
            executor_params = llm_routing_result.get("executor_params", {})
            llm_response = llm_routing_result.get("llm_response")

            if llm_routing_result.get("error"):
                logger.warning(f"   LLM error: {llm_routing_result.get('error')}")

            # Add LLM routing step to trace
            steps.append({
                "module": self.module_name,
                "prompt": {
                    "user_prompt": user_prompt,
                    "routing_type": "llm"
                },
                "response": {
                    "executor": executor_name,
                    "params": executor_params,
                    "llm_response": llm_response,
                    "reasoning": llm_routing_result.get("reasoning")
                }
            })

            # Fallback to pattern matching if LLM didn't return executor
            if not executor_name:
                logger.warning("LLM routing failed, falling back to pattern matching")
                # #region agent log
                _write_debug_log("debug-session", "supervisor", "R", "supervisor.py:route_task", "Falling back to pattern matching", {})
                # #endregion
                executor_name, executor_params = self._fallback_pattern_matching(user_prompt)

                # Update step with fallback result
                if executor_name:
                    steps[-1]["response"]["fallback_used"] = True
                    steps[-1]["response"]["executor"] = executor_name
                    steps[-1]["response"]["params"] = executor_params

                if not executor_name:
                    return {
                        "status": "error",
                        "error": "Could not identify the requested task. Please rephrase your request more clearly.",
                        "response": None,
                        "steps": steps
                    }

            executor = self.executors.get(executor_name)
            if not executor:
                return {
                    "status": "error",
                    "error": f"Executor {executor_name} not found",
                    "response": None,
                    "steps": steps
                }

            try:
                # Pass user_prompt to executors that might need it for preference extraction or parameter extraction
                if executor_name in ["block_mover", "block_resizer", "request_handler"]:
                    executor_params["user_prompt"] = user_prompt
                
                result = await executor.execute(user_id=user_id, **executor_params, **kwargs)

                steps.append(executor.get_step_log(
                    prompt={"user_prompt": user_prompt, **executor_params},
                    response=result
                ))

                return {
                    "status": "ok",
                    "error": None,
                    "response": result.get("message", "Task completed successfully"),
                    "steps": steps
                }
            except HTTPException as http_exc:
                # HTTPException has a detail attribute
                error_msg = http_exc.detail if hasattr(http_exc, 'detail') else str(http_exc)
                logger.error(f"HTTPException executing {executor_name}: {error_msg}")
                steps.append({
                    "module": executor_name,
                    "prompt": {"user_prompt": user_prompt, **executor_params},
                    "response": {"error": error_msg}
                })
                return {
                    "status": "error",
                    "error": error_msg,
                    "response": None,
                    "steps": steps
                }
            except Exception as e:
                error_msg = str(e) if str(e) else "Unknown error occurred"
                logger.error(f"Error executing {executor_name}: {error_msg}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                steps.append({
                    "module": executor_name,
                    "prompt": {"user_prompt": user_prompt, **executor_params},
                    "response": {"error": error_msg}
                })
                return {
                    "status": "error",
                    "error": error_msg,
                    "response": None,
                    "steps": steps
                }

        except Exception as e:
            logger.error(f"Supervisor error: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "status": "error",
                "error": f"Supervisor error: {str(e)}",
                "response": None,
                "steps": steps
            }

    def _fallback_pattern_matching(self, user_prompt: str) -> tuple[Optional[str], Dict[str, Any]]:
        """
        Fallback pattern matching for task routing when LLM is unavailable
        Returns (executor_name, executor_params)
        """
        prompt_lower = user_prompt.lower()
        
        # Course manager patterns
        if any(word in prompt_lower for word in ["add course", "add class", "הוסף קורס", "צרף קורס"]):
            # Extract course number (3-6 digits)
            course_numbers = re.findall(r'\d{3,6}', user_prompt)
            if course_numbers:
                # Use the longest number found (to handle cases like "104043")
                course_number = max(course_numbers, key=len)
                return "course_manager", {"course_number": course_number}
        
        # Schedule retriever patterns
        if any(word in prompt_lower for word in ["schedule", "לוז", "מערכת", "show schedule", "הצג לוז"]):
            # Try to extract date
            date_match = re.search(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})', user_prompt)
            date = date_match.group(1).replace('/', '-') if date_match else None
            return "schedule_retriever", {"date": date} if date else {}
        
        # Notification retriever patterns
        if any(word in prompt_lower for word in ["notifications", "התראות", "show notifications", "הצג התראות"]):
            return "notification_retriever", {}
        
        # Notification cleaner patterns
        if any(word in prompt_lower for word in ["clear notifications", "נקה התראות", "delete notifications"]):
            return "notification_cleaner", {}
        
        # Group manager patterns
        if any(word in prompt_lower for word in ["create group", "צור קבוצה", "new group"]):
            return "group_manager", {}
        
        # Request handler patterns
        if any(word in prompt_lower for word in ["approve", "reject", "אישור", "דחייה"]):
            return "request_handler", {}
        
        # Block mover patterns
        if any(word in prompt_lower for word in ["move block", "הזז בלוק", "move"]):
            return "block_mover", {}
        
        # Block resizer patterns
        if any(word in prompt_lower for word in ["resize", "שינוי גודל", "change duration"]):
            return "block_resizer", {}
        
        # Block creator patterns
        if any(word in prompt_lower for word in ["add block", "create block", "new block", "הוסף בלוק", "צור בלוק", "בלוק חדש", "add study", "הוסף למידה"]):
            return "block_creator", {}
        
        # Preference updater patterns
        if any(word in prompt_lower for word in ["update preferences", "עדכן העדפות", "study preferences", "העדפות לימוד", "I prefer", "אני מעדיף", "I like", "אני אוהב"]):
            return "preference_updater", {}
        
        # Constraint manager patterns
        if any(word in prompt_lower for word in ["add constraint", "הוסף אילוץ", "I have", "יש לי", "training", "אימון", "work", "עבודה", "meeting", "מפגש", "constraint", "אילוץ"]):
            return "constraint_manager", {}
        
        return None, {}
