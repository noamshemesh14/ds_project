"""
Test if OpenAI is properly configured
"""
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

print("="*60)
print("🔍 OPENAI CONFIGURATION TEST")
print("="*60)

# 1. Check if OpenAI can be imported
print("\n1️⃣ Checking OpenAI package...")
try:
    from openai import OpenAI
    print("   ✅ OpenAI package imported successfully!")
except ImportError as e:
    print(f"   ❌ OpenAI package not found: {e}")
    exit(1)

# 2. Check if API key exists in environment
print("\n2️⃣ Checking API key in environment...")
api_key = os.getenv('OPENAI_API_KEY')
if api_key:
    print(f"   ✅ API key found: {api_key[:15]}...{api_key[-4:]}")
else:
    print("   ❌ OPENAI_API_KEY not found in environment!")
    print("   💡 Make sure .env file exists with: OPENAI_API_KEY=sk-...")
    exit(1)

# 3. Try to create OpenAI client
print("\n3️⃣ Creating OpenAI client...")
try:
    client = OpenAI(api_key=api_key)
    print("   ✅ Client created successfully!")
except Exception as e:
    print(f"   ❌ Failed to create client: {e}")
    exit(1)

# 4. Try a simple API call
print("\n4️⃣ Testing API call (this may take a few seconds)...")
try:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Say 'Hello' in one word."}
        ],
        max_tokens=10
    )
    result = response.choices[0].message.content
    print(f"   ✅ API call successful! Response: {result}")
except Exception as e:
    print(f"   ❌ API call failed: {e}")
    print(f"   💡 Check if your API key is valid")
    exit(1)

print("\n" + "="*60)
print("✅ ALL TESTS PASSED!")
print("="*60)
print("\n💡 OpenAI is properly configured.")
print("   The LLM should work in your schedule generation.")
print("\n📝 Next step: Run schedule generation again:")
print('   curl.exe -X POST "http://localhost:8000/api/weekly-plan/run-immediately"')

