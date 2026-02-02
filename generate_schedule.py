"""
Quick script to generate schedule for testing
"""
import requests

BASE_URL = "http://localhost:8000"

# Login (change these to your test user credentials)
email = "test@example.com"  # CHANGE THIS
password = "password"        # CHANGE THIS

print("🔐 Logging in...")
login_response = requests.post(
    f"{BASE_URL}/api/login",
    json={"email": email, "password": password}
)

if login_response.status_code == 200:
    token = login_response.json()["access_token"]
    print("✅ Logged in successfully!")
    
    print("\n🤖 Generating schedule...")
    generate_response = requests.post(
        f"{BASE_URL}/api/weekly-plan/run-immediately",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    if generate_response.status_code == 200:
        print("✅ Schedule generated successfully!")
        print("\n📊 Response:")
        print(generate_response.json())
        print("\n✨ Now go to http://localhost:8000/schedule to see your schedule!")
    else:
        print(f"❌ Failed: {generate_response.status_code}")
        print(generate_response.text)
else:
    print(f"❌ Login failed: {login_response.status_code}")
    print("Please update email and password in this script")



