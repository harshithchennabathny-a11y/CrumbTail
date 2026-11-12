import os

os.environ["INSTANCE_ID"] = "A"
os.environ["PORT"] = "8000"

from app.main import create_app

app = create_app(instance_id="A")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main_a:app", host="0.0.0.0", port=8000, reload=False)

