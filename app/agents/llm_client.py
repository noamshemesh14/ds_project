"""
LLM Client for intelligent task routing and parameter extraction
"""
import logging
import os
import json
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import asyncio

load_dotenv()

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("OpenAI library not installed. Install with: pip install openai")

# Helper function for debug logging
def _write_debug_log(session_id, run_id, hypothesis_id, location, message, data):
    """Write debug log to file"""
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


class LLMClient:
    def __init__(self):
        self.client = None
        self.model = None
        self._initialize_client()

    def _initialize_client(self):
        _write_debug_log("debug-session", "init", "A", "llm_client.py:_initialize_client", "Initializing LLM client", {"has_openai": HAS_OPENAI})

        logger.info("🔧 Initializing LLM client...")

        if not HAS_OPENAI:
            logger.warning("❌ OpenAI library not available. LLM routing will be disabled.")
            logger.warning("   Install with: pip install openai")
            _write_debug_log("debug-session", "init", "B", "llm_client.py:_initialize_client", "OpenAI library not available", {})
            return

        llmod_api_key = os.getenv("LLMOD_API_KEY")
        if not llmod_api_key:
            llmod_api_key = os.getenv("LLM_API_KEY")

        if llmod_api_key:
            logger.info(f"   Found LLMod API key (length: {len(llmod_api_key)}, starts with: {llmod_api_key[:10]}...)")
            if llmod_api_key == "your_llmod_api_key_here":
                logger.error("   ⚠️ LLM_API_KEY is still set to placeholder 'your_llmod_api_key_here'!")
                logger.error("   Please replace it with your actual LLMod.ai API key in .env file")
                llmod_api_key = None
        else:
            logger.warning("   ⚠️ No LLMod API key found (checked LLMOD_API_KEY and LLM_API_KEY)")

        llmod_base_url = os.getenv("LLMOD_BASE_URL") or os.getenv("LLM_BASE_URL") or "https://api.llmod.ai/v1"

        if llmod_base_url and not llmod_base_url.endswith("/v1"):
            if llmod_base_url.endswith("/"):
                llmod_base_url = llmod_base_url + "v1"
            else:
                llmod_base_url = llmod_base_url + "/v1"

        env_vars_checked = {
            "LLMOD_API_KEY": bool(os.getenv("LLMOD_API_KEY")),
            "LLM_API_KEY": bool(os.getenv("LLM_API_KEY")),
            "LLMOD_BASE_URL": bool(os.getenv("LLMOD_BASE_URL")),
            "LLM_BASE_URL": bool(os.getenv("LLM_BASE_URL")),
            "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY"))
        }
        _write_debug_log("debug-session", "init", "C", "llm_client.py:_initialize_client", "Checking LLMod keys", {
            "has_llmod_key": bool(llmod_api_key),
            "llmod_key_length": len(llmod_api_key) if llmod_api_key else 0,
            "llmod_base_url": llmod_base_url,
            "env_vars_found": env_vars_checked
        })

        openai_api_key = os.getenv("OPENAI_API_KEY")

        _write_debug_log("debug-session", "init", "D", "llm_client.py:_initialize_client", "Checking OpenAI key", {"has_openai_key": bool(openai_api_key), "openai_key_length": len(openai_api_key) if openai_api_key else 0})

        logger.info(f"   Checking for LLMOD_API_KEY: {'Found' if llmod_api_key else 'Not found'}")
        logger.info(f"   Checking for OPENAI_API_KEY: {'Found' if openai_api_key else 'Not found'}")

        try:
            if llmod_api_key:
                logger.info(f"   Using LLMod.ai with base_url: {llmod_base_url}")
                self.client = OpenAI(
                    api_key=llmod_api_key,
                    base_url=llmod_base_url
                )
                self.model = os.getenv("LLMOD_MODEL") or os.getenv("LLM_MODEL") or "gpt-3.5-turbo"
                logger.info(f"✅ Initialized LLMod.ai client with model: {self.model}")
                _write_debug_log("debug-session", "init", "E", "llm_client.py:_initialize_client", "LLMod.ai client initialized", {"model": self.model, "base_url": llmod_base_url})
            elif openai_api_key:
                logger.info("   Using OpenAI")
                self.client = OpenAI(api_key=openai_api_key)
                self.model = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
                logger.info(f"✅ Initialized OpenAI client with model: {self.model}")
                _write_debug_log("debug-session", "init", "F", "llm_client.py:_initialize_client", "OpenAI client initialized", {"model": self.model})
            else:
                logger.warning("⚠️ No LLM API key found. Set LLMOD_API_KEY or OPENAI_API_KEY in .env")
                logger.warning("   LLM routing will be disabled, using fallback pattern matching")
                _write_debug_log("debug-session", "init", "G", "llm_client.py:_initialize_client", "No API key found", {})
        except Exception as e:
            logger.error(f"❌ Failed to initialize LLM client: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            _write_debug_log("debug-session", "init", "H", "llm_client.py:_initialize_client", "Initialization error", {"error": str(e), "error_type": type(e).__name__})

    async def route_task(
        self,
        user_prompt: str
    ) -> Dict[str, Any]:
        _write_debug_log("debug-session", "route", "I", "llm_client.py:route_task", "Route task called", {"user_prompt": user_prompt, "has_client": bool(self.client), "model": self.model})

        if not self.client:
            logger.warning("⚠️ LLM client not available, falling back to pattern matching")
            _write_debug_log("debug-session", "route", "J", "llm_client.py:route_task", "No LLM client available", {})
            return {"executor_name": None, "executor_params": {}, "error": "LLM client not initialized"}

        logger.info(f"🤖 Calling LLM with model: {self.model}")
        logger.info(f"   User prompt: {user_prompt}")

        routing_prompt = self._create_routing_prompt(user_prompt)

        _write_debug_log("debug-session", "route", "K", "llm_client.py:route_task", "Before LLM call", {"model": self.model, "system_prompt_length": len(routing_prompt["system"]), "user_prompt_length": len(routing_prompt["user"])})

        try:
            logger.info(f"   Sending request to LLM...")
            import asyncio
            loop = asyncio.get_event_loop()

            # Determine temperature based on model
            temperature_setting = 0.1
            if self.model and "gpt-5" in self.model.lower():
                temperature_setting = 1.0
                logger.info(f"   Using temperature={temperature_setting} for gpt-5 model: {self.model}")

            response = await loop.run_in_executor(
                None,
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": routing_prompt["system"]
                        },
                        {
                            "role": "user",
                            "content": routing_prompt["user"]
                        }
                    ],
                    temperature=temperature_setting,
                    response_format={"type": "json_object"}
                )
            )

            _write_debug_log("debug-session", "route", "L", "llm_client.py:route_task", "LLM call succeeded", {"has_response": bool(response), "choices_count": len(response.choices) if response and hasattr(response, 'choices') else 0})

            llm_response = response.choices[0].message.content
            logger.info(f"   LLM raw response: {llm_response[:200]}...")

            _write_debug_log("debug-session", "route", "M", "llm_client.py:route_task", "LLM response received", {"response_length": len(llm_response) if llm_response else 0, "response_preview": llm_response[:200] if llm_response else None})

            routing_result = json.loads(llm_response)

            _write_debug_log("debug-session", "route", "N", "llm_client.py:route_task", "Routing result parsed", {"executor_name": routing_result.get("executor_name"), "params_keys": list(routing_result.get("executor_params", {}).keys()), "course_number": routing_result.get("executor_params", {}).get("course_number")})

            logger.info(f"✅ LLM routing result: executor={routing_result.get('executor_name')}, params={routing_result.get('executor_params')}")

            return {
                "executor_name": routing_result.get("executor_name"),
                "executor_params": routing_result.get("executor_params", {}),
                "llm_response": llm_response,
                "reasoning": routing_result.get("reasoning", "")
            }

        except Exception as e:
            error_str = str(e)
            error_type = type(e).__name__

            if "401" in error_str or "invalid_api_key" in error_str or "AuthenticationError" in error_type:
                logger.error(f"❌ LLM Authentication Error: Invalid API key")
                logger.error(f"   Please check your API key in .env file")
                logger.error(f"   For LLMod.ai: Set LLMOD_API_KEY or LLM_API_KEY")
                logger.error(f"   For OpenAI: Set OPENAI_API_KEY with a valid key")
                logger.error(f"   Falling back to pattern matching...")
            else:
                logger.error(f"❌ Error in LLM routing: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")

            _write_debug_log("debug-session", "route", "O", "llm_client.py:route_task", "LLM call error", {"error": error_str, "error_type": error_type, "is_auth_error": "401" in error_str or "invalid_api_key" in error_str})
            return {"executor_name": None, "executor_params": {}, "error": error_str}

    def _create_routing_prompt(self, user_prompt: str) -> Dict[str, str]:
        system_prompt = """You are a task router for an academic planner system. Your job is to analyze user requests and determine:
1. Which executor should handle the task
2. What parameters to extract from the user's request

Available executors:
- course_manager: Add courses from catalog to user's course list. Requires: course_number (string, e.g., "10403"). Optional: course_name (string, e.g., "אלגוריתמים"). Note: Semester and year are handled by default in the backend and do not need to be extracted.
- schedule_retriever: Get weekly schedule. Optional: date (YYYY-MM-DD or YYYY/MM/DD format). If no date is provided, default to the current week.
- group_manager: Create study groups. Requires: course_number, group_name, invite_emails (list)
- notification_retriever: Get new notifications. No parameters needed
- notification_cleaner: Clean/delete notifications. Optional: notification_id
- request_handler: Approve/reject requests. Requires: request_id, action ("accept" or "reject")
- preference_updater: Update course time preferences. Requires: course_number, personal_ratio, group_ratio
- block_mover: Move study blocks. Requires: block_id, new_day, new_start_time, new_end_time
- block_resizer: Resize study blocks. Requires: block_id, new_duration or new_start_time/new_end_time

Return your response as JSON with this exact structure:
{
  "executor_name": "executor_name_here",
  "executor_params": {
    "param1": "value1",
    "param2": "value2"
  },
  "reasoning": "brief explanation of why this executor was chosen"
}

Extract all relevant parameters from the user's request. If a parameter is missing but required, set it to null.

For course_manager:
- Extract course_number (required) - look for 3-6 digit numbers in the user's prompt.
- CRITICAL RULE: Extract the COMPLETE and EXACT number sequence as written by the user.
  * If user writes "104043" (6 digits), extract "104043" - ALL 6 digits
  * If user writes "10404" (5 digits), extract "10404" - ALL 5 digits
  * NEVER truncate, shorten, or modify the course number
  * NEVER extract a partial number (e.g., don't extract "10404" from "104043")
  * The course number must match EXACTLY what the user typed
- Extract course_name if mentioned (optional) - will be validated against catalog
- IMPORTANT: Do NOT extract semester or year for course_manager. These are handled by default in the backend.

For schedule_retriever:
- Extract date (optional) - look for YYYY-MM-DD or YYYY/MM/DD format. Examples: "2026-02-08", "2026/02/08". If not provided, assume current week.

MOST IMPORTANT RULE: When you see a course number in the user's prompt, extract it EXACTLY as written.
If the user writes "104043", you MUST extract "104043" with all 6 digits.
Do NOT extract "10404" or any shorter version.
The course number must be an exact match to what appears in the user's text."""

        user_prompt_formatted = f"""User request: "{user_prompt}"

Analyze this request and determine:
1. Which executor should handle it
2. What parameters can be extracted

Return JSON response with executor_name and executor_params."""

        return {
            "system": system_prompt,
            "user": user_prompt_formatted
        }
