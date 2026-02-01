"""
Quick script to test schedule generation with LLM
"""
import requests
import json

# Configuration
BASE_URL = "http://localhost:8000"
TOKEN = "YOUR_AUTH_TOKEN_HERE"  # Get from localStorage in browser

def test_schedule_generation():
    """Test the schedule generation with current preferences"""
    
    # 1. Check if preferences are saved
    print("📋 Checking saved preferences...")
    response = requests.get(
        f"{BASE_URL}/api/user/preferences",
        headers={"Authorization": f"Bearer {TOKEN}"}
    )
    
    if response.ok:
        prefs = response.json()
        print(f"✅ Raw preferences: {len(prefs.get('study_preferences_raw', ''))} characters")
        print(f"   Preview: {prefs.get('study_preferences_raw', '')[:100]}...")
        print(f"   Summary (should be empty for now): {prefs.get('study_preferences_summary')}")
    else:
        print(f"❌ Error getting preferences: {response.status_code}")
        return
    
    # 2. Trigger schedule generation for next week
    print("\n🚀 Triggering schedule generation for next week...")
    week_start = "2026-02-08"  # Next week
    
    response = requests.post(
        f"{BASE_URL}/api/weekly-plan/generate?week_start={week_start}",
        headers={"Authorization": f"Bearer {TOKEN}"}
    )
    
    if response.ok:
        result = response.json()
        print(f"✅ Schedule generated!")
        print(f"   Plan ID: {result.get('plan_id')}")
        print(f"   Total blocks: {len(result.get('blocks', []))}")
        
        # Count LLM vs fallback blocks
        llm_blocks = [b for b in result.get('blocks', []) if b.get('source') == 'llm']
        fallback_blocks = [b for b in result.get('blocks', []) if b.get('source') == 'auto_fallback']
        
        print(f"   🤖 LLM-generated blocks: {len(llm_blocks)}")
        print(f"   🔧 Fallback blocks: {len(fallback_blocks)}")
        
        if llm_blocks:
            print("\n✅ LLM REFINEMENT WORKED! 🎉")
            print("   The schedule was optimized based on your preferences.")
        else:
            print("\n⚠️ LLM refinement did not run (used fallback)")
            print("   Check server logs for the reason.")
    else:
        print(f"❌ Error generating schedule: {response.status_code}")
        print(f"   {response.text}")

if __name__ == "__main__":
    if TOKEN == "YOUR_AUTH_TOKEN_HERE":
        print("❌ Please set your auth token in the script first!")
        print("   Get it from: localStorage.getItem('auth_token') in browser console")
    else:
        test_schedule_generation()

