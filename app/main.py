from fastapi import FastAPI
from .routers import session, turn

app = FastAPI(title="Sanctra Orchestrator")
app.include_router(session.router, prefix="/session", tags=["session"])
app.include_router(turn.router, prefix="/turn", tags=["turn"])
