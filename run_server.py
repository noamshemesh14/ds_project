"""
Simple script to run the FastAPI server
"""
import uvicorn
import sys
import os
from pathlib import Path

# Check if .env file exists
env_file = Path(__file__).parent / ".env"
if not env_file.exists():
    print("WARNING: .env file not found. Make sure SUPABASE_ANON_KEY is set.")
    print("   Create a .env file in ds_project/ with:")
    print("   SUPABASE_URL=your_url")
    print("   SUPABASE_ANON_KEY=your_key")
    print("   SUPABASE_SERVICE_ROLE_KEY=your_service_key (optional)")
    print()

if __name__ == "__main__":
    try:
        print("Starting server on http://0.0.0.0:8000")
        print("Press Ctrl+C to stop")
        print("-" * 50)
        uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
    except KeyboardInterrupt:
        print("\nServer stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nERROR: Failed to start server: {e}")
        print("\nTroubleshooting:")
        print("1. Make sure all dependencies are installed: py -m pip install -r requirements.txt")
        print("2. Check that .env file exists with SUPABASE_ANON_KEY")
        print("3. Verify port 8000 is not already in use")
        sys.exit(1)

