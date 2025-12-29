# app/main.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from app.routers.decision import router as decision_router
from app.routers.ui import router as ui_router

app = FastAPI(title="AI Validation (Trade Screening)", version="0.1.0")

# static
app.mount("/static", StaticFiles(directory="static"), name="static")

# templates (ui.py で利用)
templates = Jinja2Templates(directory="templates")
app.state.templates = templates

# routers
app.include_router(ui_router)
app.include_router(decision_router)

@app.get("/")
def health_check():
    return {"status": "ok"}
