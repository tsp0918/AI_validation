from fastapi import FastAPI

from app.routers.decision import router as decision_router

app = FastAPI(
    title="AI Validation Engine",
    version="0.1.0",
)

# ルーター登録
app.include_router(decision_router)


@app.get("/")
def health_check():
    return {"status": "ok"}
