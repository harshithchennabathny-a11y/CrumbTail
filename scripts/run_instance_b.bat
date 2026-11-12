@echo off
echo Starting Crumb Trail - FastAPI Instance B on port 8001...
cd /d "%~dp0.."
set INSTANCE_ID=B
set PORT=8001
python -m uvicorn app.main_b:app --host 0.0.0.0 --port 8001

