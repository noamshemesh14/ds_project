"""
Authentication utilities for Supabase
"""
from fastapi import HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import Client
from app.supabase_client import supabase, SUPABASE_URL, SUPABASE_ANON_KEY, supabase_admin
from typing import Optional
import logging
from jose import jwt
import requests

security = HTTPBearer(auto_error=False)

async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[dict]:
    """
    Optional authentication - returns None if no token, user dict if authenticated
    """
    try:
        token = None
        if credentials:
            token = credentials.credentials
        else:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]
        
        if not token:
            return None
        
        # Decode JWT
        try:
            import base64
            parts = token.split('.')
            if len(parts) != 3:
                return None
            
            payload = parts[1]
            # Add padding if needed
            payload += '=' * (4 - len(payload) % 4)
            decoded = base64.urlsafe_b64decode(payload)
            import json
            payload_data = json.loads(decoded)
            
            # Check expiration
            import time
            exp = payload_data.get('exp')
            if exp:
                current_time = time.time()
                if exp < current_time:
                    return None
            
            return {
                'sub': payload_data.get('sub'),
                'email': payload_data.get('email'),
                'role': payload_data.get('role', 'authenticated')
            }
        except Exception:
            return None
    except Exception:
        return None


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> dict:
    """
    Verify JWT token from Supabase and return user
    """
    try:
        # Try to get token from credentials first
        token = None
        if credentials:
            token = credentials.credentials
            logging.info("✅ Token found in HTTPBearer credentials")
        else:
            # Fallback: try to get from Authorization header directly
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]  # Remove "Bearer " prefix
                logging.info("✅ Token found in Authorization header")
            else:
                logging.warning(f"❌ No Authorization header found. Headers: {list(request.headers.keys())}")
        
        if not token:
            logging.error("❌ No token found in request")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No authentication token provided"
            )
        
        logging.info(f"🔐 Attempting to authenticate with token (length: {len(token)}, first 30 chars: {token[:30]}...)")
        
        # Method 1: Decode JWT directly by parsing the payload
        try:
            # JWT format: header.payload.signature
            # We'll decode just the payload part
            import base64
            import json
            
            parts = token.split('.')
            if len(parts) != 3:
                raise ValueError(f"Invalid JWT format: expected 3 parts, got {len(parts)}")
            
            logging.info(f"   JWT has {len(parts)} parts, attempting to decode payload...")
            
            # Decode payload (second part)
            payload_encoded = parts[1]
            # Add padding if needed
            padding = 4 - len(payload_encoded) % 4
            if padding != 4:
                payload_encoded += '=' * padding
            
            try:
                payload_bytes = base64.urlsafe_b64decode(payload_encoded)
                payload = json.loads(payload_bytes.decode('utf-8'))
                logging.info(f"   Decoded payload keys: {list(payload.keys())}")
            except Exception as decode_error:
                logging.error(f"   Failed to decode payload: {decode_error}")
                raise
            
            # Check expiration
            import time
            exp = payload.get("exp")
            current_time = time.time()
            if exp:
                if exp < current_time:
                    time_diff = current_time - exp
                    logging.error(f"   ❌ Token expired {time_diff:.0f} seconds ago (exp: {exp}, now: {current_time})")
                    raise ValueError(f"Token expired")
                time_until_exp = exp - current_time
                logging.info(f"   ✅ Token expires in {time_until_exp:.0f} seconds (exp: {exp}, now: {current_time})")
            
            user_id = payload.get("sub")
            email = payload.get("email")
            
            logging.info(f"   Found user_id: {user_id}, email: {email}")
            
            if user_id:
                logging.info(f"✅ Authenticated user via JWT decode: {email} (id: {user_id})")
                return {
                    "id": user_id,
                    "sub": user_id,
                    "email": email,
                    "user_metadata": payload.get("user_metadata", {})
                }
            else:
                logging.warning(f"❌ No user_id found in JWT token. Payload keys: {list(payload.keys())}")
                raise ValueError("No user_id (sub) in JWT token")
        except Exception as jwt_error:
            logging.warning(f"❌ JWT decode failed: {jwt_error}")
            import traceback
            logging.warning(f"   JWT decode traceback: {traceback.format_exc()}")
        
        # Method 2: Try Supabase API (fallback)
        try:
            from supabase import create_client
            temp_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
            
            # Try to get user with token directly
            # Some Supabase versions support passing token to get_user
            try:
                response = temp_client.auth.get_user(token)
                if response and hasattr(response, 'user') and response.user:
                    logging.info(f"✅ Authenticated user via Supabase API: {response.user.email} (id: {response.user.id})")
                    return {
                        "id": response.user.id,
                        "sub": response.user.id,
                        "email": response.user.email,
                        "user_metadata": response.user.user_metadata or {}
                    }
            except Exception as api_error:
                logging.warning(f"Supabase get_user(token) failed: {api_error}")
                
                # Try with set_session
                try:
                    # Create a session-like object
                    # Supabase expects: {"access_token": "...", "refresh_token": "..."}
                    temp_client.auth.set_session(token, "")
                    response = temp_client.auth.get_user()
                    if response and hasattr(response, 'user') and response.user:
                        logging.info(f"✅ Authenticated user via set_session: {response.user.email} (id: {response.user.id})")
                        return {
                            "id": response.user.id,
                            "sub": response.user.id,
                            "email": response.user.email,
                            "user_metadata": response.user.user_metadata or {}
                        }
                except Exception as session_error:
                    logging.warning(f"Supabase set_session failed: {session_error}")
        except Exception as api_error:
            logging.warning(f"Supabase API method failed: {api_error}")
        
        # All methods failed
        logging.error("❌ Authentication failed: All verification methods failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"❌ Authentication error: {e}")
        import traceback
        logging.error(f"   Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {str(e)}"
        )


# מזהה קבוע של משתמש העל (Super User) עבור CLI
SUPER_USER_ID = "56a2597d-62fc-49b3-9f98-1b852941b5ef"

async def get_cli_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> dict:
    """
    Get user for CLI endpoints - always returns super user.
    שולף את משתמש העל ישירות מ-Supabase לפי UUID קבוע.
    האתר ימשיך לעבוד בדיוק כמו עכשיו - רק CLI יעבוד עם משתמש העל.
    """
    if not supabase_admin:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_SERVICE_ROLE_KEY is required for CLI super user"
        )
    
    try:
        # שלוף את המשתמש ישירות לפי UUID
        # זה עובד כי UUID הוא קבוע ולא משתנה!
        user_response = supabase_admin.auth.admin.get_user_by_id(SUPER_USER_ID)
        
        if user_response and hasattr(user_response, 'user') and user_response.user:
            user = user_response.user
            logging.info(f"🎭 CLI endpoint - using super user: {user.email} (id: {user.id})")
            return {
                "id": user.id,
                "sub": user.id,
                "email": user.email,
                "user_metadata": user.user_metadata or {}
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Super user with ID {SUPER_USER_ID} not found in Supabase"
            )
    except Exception as e:
        logging.error(f"❌ Error fetching super user: {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching super user: {str(e)}"
        )


