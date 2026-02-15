"""
Test script to verify LLM connection and response generation
Tests the chat flow without RAG to ensure basic LLM connectivity
"""
import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.agents.llm_client import LLMClient
from app.agents.executors.rag_chat import RAGChatExecutor

async def test_llm_connection():
    """Test LLM connection and response generation"""
    print("=" * 60)
    print("Testing LLM Connection and Response Generation")
    print("=" * 60)
    
    # Test 1: Initialize LLM Client
    print("\n1. Initializing LLM Client...")
    llm_client = LLMClient()
    if not llm_client.client:
        print("[FAILED] LLM client not initialized")
        print("   Please check OPENAI_API_KEY or LLMOD_API_KEY in .env file")
        return False
    print(f"[OK] LLM Client initialized")
    print(f"   Model: {llm_client.model}")
    print(f"   Client type: {type(llm_client.client).__name__}")
    
    # Test 2: Simple LLM call
    print("\n2. Testing simple LLM call...")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        
        # gpt-5 models only support temperature=1
        model_name = llm_client.model.lower()
        temperature = 1.0 if "gpt-5" in model_name else 0.7
        
        response = await loop.run_in_executor(
            None,
            lambda: llm_client.client.chat.completions.create(
                model=llm_client.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant. Answer in Hebrew."},
                    {"role": "user", "content": "מה השעה?"}
                ],
                temperature=temperature
            )
        )
        
        response_text = response.choices[0].message.content
        print(f"[OK] LLM call successful")
        print(f"   Response: {response_text[:200]}...")
    except Exception as e:
        error_msg = str(e)
        print(f"[FAILED] LLM call error: {error_msg}")
        if "401" in error_msg or "invalid_api_key" in error_msg or "AuthenticationError" in str(type(e)):
            print("   This is an authentication error. Please check your API key.")
        return False
    
    # Test 3: RAG Chat Executor without RAG (LLM only)
    print("\n3. Testing RAG Chat Executor (LLM only, no RAG)...")
    try:
        rag_executor = RAGChatExecutor()
        
        # Simulate a query without RAG context
        result = await rag_executor.execute(
            user_id="test_user",
            query="מה השעה?",
            llm_client=llm_client,
            user_context=None,
            ui_context=None
        )
        
        if result.get("status") == "success":
            print(f"[OK] RAG Chat Executor test successful")
            print(f"   Response: {result.get('response', '')[:200]}...")
            print(f"   Context used: {result.get('context_used', False)}")
            print(f"   Web search used: {result.get('web_search_used', False)}")
            return True
        else:
            print(f"[FAILED] RAG Chat Executor returned error status")
            print(f"   Error: {result.get('error', 'Unknown error')}")
            print(f"   Response: {result.get('response', 'No response')}")
            return False
    except Exception as e:
        error_msg = str(e)
        print(f"[FAILED] RAG Chat Executor error: {error_msg}")
        import traceback
        print(f"   Traceback: {traceback.format_exc()}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_llm_connection())
    if result:
        print("\n" + "=" * 60)
        print("[OK] All tests passed! LLM connection is working correctly.")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("[FAILED] Some tests failed. Please check the errors above.")
        print("=" * 60)
        sys.exit(1)

