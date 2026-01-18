# How to Start the Server

## Quick Start

1. **Open Terminal in Cursor:**
   - Press `Ctrl + `` (backtick) OR
   - Go to `Terminal` → `New Terminal` from menu

2. **Navigate to project directory:**
   ```powershell
   cd C:\DS\AcademicPlanner\ds_project
   ```

3. **Start the server (choose one method):**

   **Method 1: Using uvicorn directly (recommended)**
   ```powershell
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

   **Method 2: Using the run script**
   ```powershell
   py run_server.py
   ```

4. **The server will run on:**
   - http://localhost:8000
   - http://0.0.0.0:8000

5. **To stop the server:**
   - Press `Ctrl+C` in the terminal

## Verify Server is Running

After starting, you should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started server process [XXXXX]
INFO:     Application startup complete.
```

## Troubleshooting

### If you see "ModuleNotFoundError: No module named 'supabase'"
Run:
```powershell
py -m pip install -r requirements.txt
```

### If you see "uvicorn: command not found"
Use Python module syntax:
```powershell
py -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### If you see "SUPABASE_ANON_KEY environment variable is required"
Make sure you have a `.env` file in `ds_project/` with:
```
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
```

### To test if server is working
Run (in a new terminal):
```powershell
cd C:\DS\AcademicPlanner\ds_project
py test_server.py
```

## Viewing Logs

All logs appear directly in the Cursor terminal where you ran `py run_server.py`.

You'll see:
- Server startup messages
- API request logs
- Error messages
- Debug information

