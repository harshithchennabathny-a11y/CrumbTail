@echo off
echo Starting Crumb Trail - Mock Notification Service on port 9000...
cd /d "%~dp0.."
python -m uvicorn app.mock_notification_service:app --host 0.0.0.0 --port 9000

