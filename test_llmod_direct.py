"""
Test LLMod.ai API key directly with the correct configuration
"""
import os
from dotenv import load_dotenv

load_dotenv()

# The key from the website
test_key = "sk-NaXQH1ceM3FDA638o5XV8Q"
base_url = "https://api.llmod.ai/v1"
model = "RPRTHPB-gpt-5-mini"

print("=" * 60)
print("Testing LLMod.ai API Key Directly")
print("=" * 60)
print(f"Key: {test_key[:10]}...{test_key[-4:]}")
print(f"Base URL: {base_url}")
print(f"Model: {model}")

try:
    from openai import OpenAI
    
    client = OpenAI(
        api_key=test_key,
        base_url=base_url
    )
    
    print("\nTesting API call...")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": "Say 'test'"}
        ],
        max_tokens=5
    )
    
    print(f"[OK] API call successful!")
    print(f"Response: {response.choices[0].message.content}")
    print("\n[OK] The key works! You need to set it as LLMOD_API_KEY in .env")
    
except Exception as e:
    error_msg = str(e)
    print(f"[FAILED] API call failed: {error_msg}")
    if "401" in error_msg or "invalid_api_key" in error_msg:
        print("This is an authentication error - the key might be invalid or expired")
    else:
        print("This is a different error - check the error message above")

