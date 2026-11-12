@echo off
echo Starting Redis 7.2.5 on port 6379...
cd /d "%~dp0tools\redis"
redis-server.exe redis.conf

