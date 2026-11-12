import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "crumb_trail.db"
REDIS_SCRIPTS_DIR = Path(__file__).resolve().parent / "redis_scripts"

# Instance Configuration
INSTANCE_ID = os.getenv("INSTANCE_ID", "A")
PORT = int(os.getenv("PORT", "8000" if INSTANCE_ID == "A" else "8001"))
HOST = os.getenv("HOST", "0.0.0.0")

# Redis Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

# External Services
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://localhost:9000/notify")

# City Spatial Bounding Box (Bengaluru center: Koramangala / Indiranagar)
CITY_BOUNDS = {
    "center_lat": 12.9716,
    "center_lon": 77.5946,
    "min_lat": 12.9300,
    "max_lat": 13.0100,
    "min_lon": 77.5500,
    "max_lon": 77.6500,
}
BENGALURU_BOUNDS = CITY_BOUNDS

