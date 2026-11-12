import os

os.environ["INSTANCE_ID"] = "B"
os.environ["PORT"] = "8001"

from app.main import create_app

app = create_app(instance_id="B")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main_b:app", host="0.0.0.0", port=8001, reload=False)

