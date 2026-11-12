@echo off
echo Starting Crumb Trail - FastAPI Instance A on port 8000...
cd /d "%~dp0.."
set INSTANCE_ID=A
set PORT=8000
python -m uvicorn app.main_a:app --host 0.0.0.0 --port 8000

