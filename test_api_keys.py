"""
Test script to verify each API key individually before testing the code
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_openai_key():
    """Test OpenAI API key"""
    print("\n" + "=" * 60)
    print("Testing OPENAI_API_KEY")
    print("=" * 60)
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[FAILED] OPENAI_API_KEY not found in .env")
        return False
    
    print(f"[OK] OPENAI_API_KEY found")
    print(f"   Length: {len(api_key)}")
    print(f"   Starts with: {api_key[:10]}...")
    print(f"   Ends with: ...{api_key[-4:]}")
    
    # Test the key
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        # Try a simple API call
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": "Say 'test'"}
            ],
            max_tokens=5
        )
        
        print(f"[OK] OpenAI API key is VALID")
        print(f"   Response: {response.choices[0].message.content}")
        return True
    except Exception as e:
        error_msg = str(e)
        print(f"[FAILED] OpenAI API key test failed")
        print(f"   Error: {error_msg}")
        if "401" in error_msg or "invalid_api_key" in error_msg or "Incorrect API key" in error_msg:
            print("   This is an authentication error - the key is INVALID")
        return False

def test_llmod_key():
    """Test LLMod API key"""
    print("\n" + "=" * 60)
    print("Testing LLMOD_API_KEY / LLM_API_KEY")
    print("=" * 60)
    
    api_key = os.getenv("LLMOD_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        print("[SKIP] LLMOD_API_KEY / LLM_API_KEY not found in .env")
        print("   This is optional if using OpenAI")
        return None
    
    print(f"[OK] LLMOD_API_KEY / LLM_API_KEY found")
    print(f"   Length: {len(api_key)}")
    print(f"   Starts with: {api_key[:10]}...")
    print(f"   Ends with: ...{api_key[-4:]}")
    
    # Get base URL
    base_url = os.getenv("LLMOD_BASE_URL") or os.getenv("LLM_BASE_URL") or "https://api.llmod.ai/v1"
    if not base_url.endswith("/v1"):
        if base_url.endswith("/"):
            base_url = base_url + "v1"
        else:
            base_url = base_url + "/v1"
    
    print(f"   Base URL: {base_url}")
    
    # Test the key
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        
        # Try a simple API call
        model = os.getenv("LLMOD_MODEL") or os.getenv("LLM_MODEL") or "gpt-3.5-turbo"
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": "Say 'test'"}
            ],
            max_tokens=5
        )
        
        print(f"[OK] LLMod API key is VALID")
        print(f"   Model: {model}")
        print(f"   Response: {response.choices[0].message.content}")
        return True
    except Exception as e:
        error_msg = str(e)
        print(f"[FAILED] LLMod API key test failed")
        print(f"   Error: {error_msg}")
        if "401" in error_msg or "invalid_api_key" in error_msg or "Incorrect API key" in error_msg:
            print("   This is an authentication error - the key is INVALID")
        return False

def test_pinecone_key():
    """Test Pinecone API key"""
    print("\n" + "=" * 60)
    print("Testing PINECONE_API_KEY")
    print("=" * 60)
    
    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        print("[SKIP] PINECONE_API_KEY not found in .env")
        print("   This is optional - RAG will work without it (LLM only)")
        return None
    
    print(f"[OK] PINECONE_API_KEY found")
    print(f"   Length: {len(api_key)}")
    print(f"   Starts with: {api_key[:10]}...")
    print(f"   Ends with: ...{api_key[-4:]}")
    
    # Test the key
    try:
        from pinecone import Pinecone
        pc = Pinecone(api_key=api_key)
        
        # Try to list indexes (this validates the key)
        indexes = pc.list_indexes()
        
        print(f"[OK] Pinecone API key is VALID")
        print(f"   Found {len(indexes.names())} indexes")
        return True
    except Exception as e:
        error_msg = str(e)
        print(f"[FAILED] Pinecone API key test failed")
        print(f"   Error: {error_msg}")
        if "401" in error_msg or "invalid_api_key" in error_msg or "Unauthorized" in error_msg:
            print("   This is an authentication error - the key is INVALID")
        return False

def test_embedding_config():
    """Test embedding configuration"""
    print("\n" + "=" * 60)
    print("Testing Embedding Configuration")
    print("=" * 60)
    
    embedding_base_url = os.getenv("EMBEDDING_BASE_URL")
    embedding_model = os.getenv("EMBEDDING_MODEL")
    
    print(f"   EMBEDDING_BASE_URL: {embedding_base_url or 'Not set (will use standard OpenAI)'}")
    print(f"   EMBEDDING_MODEL: {embedding_model or 'Not set (will use default)'}")
    
    if embedding_base_url:
        # If EMBEDDING_BASE_URL is set, we should use LLMOD_API_KEY
        llmod_key = os.getenv("LLMOD_API_KEY") or os.getenv("LLM_API_KEY")
        if llmod_key:
            print(f"[OK] EMBEDDING_BASE_URL is set and LLMOD_API_KEY found")
            print("   Embeddings will use LLMod.ai")
        else:
            print(f"[WARNING] EMBEDDING_BASE_URL is set but LLMOD_API_KEY not found")
            print("   Will fall back to OPENAI_API_KEY without base_url")
    else:
        # If no EMBEDDING_BASE_URL, we should use OPENAI_API_KEY
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            print(f"[OK] No EMBEDDING_BASE_URL, will use OPENAI_API_KEY for embeddings")
        else:
            print(f"[WARNING] No EMBEDDING_BASE_URL and no OPENAI_API_KEY")
            print("   Embeddings will fail")
    
    return True

def main():
    """Run all API key tests"""
    print("=" * 60)
    print("API Key Validation Test")
    print("=" * 60)
    
    results = {}
    
    # Test OpenAI key
    results["openai"] = test_openai_key()
    
    # Test LLMod key
    results["llmod"] = test_llmod_key()
    
    # Test Pinecone key
    results["pinecone"] = test_pinecone_key()
    
    # Test embedding config
    test_embedding_config()
    
    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    
    if results["openai"]:
        print("[OK] OPENAI_API_KEY is valid - LLM will work")
    else:
        print("[FAILED] OPENAI_API_KEY is invalid - LLM will NOT work")
    
    if results["llmod"] is True:
        print("[OK] LLMOD_API_KEY is valid - LLMod.ai will work")
    elif results["llmod"] is False:
        print("[FAILED] LLMOD_API_KEY is invalid")
    else:
        print("[SKIP] LLMOD_API_KEY not set (optional)")
    
    if results["pinecone"] is True:
        print("[OK] PINECONE_API_KEY is valid - RAG will work")
    elif results["pinecone"] is False:
        print("[FAILED] PINECONE_API_KEY is invalid - RAG will NOT work")
    else:
        print("[SKIP] PINECONE_API_KEY not set (optional - RAG will use LLM only)")
    
    # Final verdict
    if results["openai"]:
        print("\n[OK] At least one LLM API key is valid - Chat will work (LLM only)")
        if results["pinecone"]:
            print("[OK] RAG is fully configured - Chat will work with RAG")
        else:
            print("[INFO] RAG is not configured - Chat will work without RAG (LLM only)")
        return True
    else:
        print("\n[FAILED] No valid LLM API key found - Chat will NOT work")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

