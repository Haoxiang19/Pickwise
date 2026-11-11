"""HTTP endpoints. Money moves only here, after a user click; the model cannot reach these."""
import logging
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import agent, catalog, llm, store

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="PayPal Shopping Agent")
INDEX = Path(__file__).parent.parent / "static" / "index.html"


@app.middleware("http")
async def user_cookie(request: Request, call_next):
    """No login: a random ID in an HttpOnly cookie identifies the user.

    A cookie (not localStorage) because the return from PayPal is a plain navigation
    and the server must read the ID on that request.
    """
    user_id = request.cookies.get("uid")
    is_new = not user_id
    request.state.user_id = user_id or secrets.token_urlsafe(16)
    response = await call_next(request)
    if is_new:
        response.set_cookie("uid", request.state.user_id, httponly=True, samesite="lax", max_age=30 * 24 * 3600,
                            secure=os.getenv("APP_BASE_URL", "").startswith("https"))
    return response


class ChatIn(BaseModel):
    message: str


@app.get("/")
def index():
    return FileResponse(INDEX)


@app.get("/api/status")
def status():
    """Which services are mocked, so the page can label them."""
    return {"mock_llm": not llm.enabled(), "mock_catalog": not catalog.enabled()}


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    session = store.get_session(request.state.user_id)
    return agent.handle_message(session, body.message.strip()[:2000])
