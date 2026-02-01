"""Simple OpenAI test without emojis"""
import os
from dotenv import load_dotenv

load_dotenv()

print("="*60)
print("OPENAI CONFIGURATION TEST")
print("="*60)

# Check API key
api_key = os.getenv('OPENAI_API_KEY')
if api_key:
    print(f"API key found: {api_key[:15]}...{api_key[-4:]}")
else:
    print("ERROR: OPENAI_API_KEY not found!")
    exit(1)

# Test import
try:
    from openai import OpenAI
    print("OpenAI package imported successfully")
except ImportError as e:
    print(f"ERROR: {e}")
    exit(1)

# Test API call
try:
    client = OpenAI(api_key=api_key)
    print("Testing API call...")
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": "Say 'test successful' in 2 words"}
        ],
        max_tokens=10
    )
    result = response.choices[0].message.content
    print(f"API Response: {result}")
    print("\nSUCCESS! OpenAI is working!")
except Exception as e:
    print(f"ERROR: {e}")
    exit(1)

