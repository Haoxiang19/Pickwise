"""HTTP endpoints. Money moves only here, after a user click; the model cannot reach these."""
import html
import logging
import os
import secrets
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app import agent, catalog, checkout, llm, paypal, paypal_mock, store

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


class CartIn(BaseModel):
    product_id: str
    quantity: int = 1


class ConfirmIn(BaseModel):
    cart_id: str


def base_url(request: Request) -> str:
    return os.getenv("APP_BASE_URL", "").rstrip("/") or str(request.base_url).rstrip("/")


@app.get("/")
def index():
    return FileResponse(INDEX)


@app.get("/api/status")
def status():
    """Which services are mocked, so the page can label them."""
    return {"mock_llm": not llm.enabled(), "mock_catalog": not catalog.enabled(), "mock_paypal": not paypal.enabled()}


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    session = store.get_session(request.state.user_id)
    return agent.handle_message(session, body.message.strip()[:2000])


@app.post("/api/cart")
def create_cart(body: CartIn, request: Request):
    """F8: the "Choose" button on a card. Same rules as the model's prepare_cart tool."""
    session = store.get_session(request.state.user_id)
    try:
        cart = store.create_cart(session, body.product_id, body.quantity)
    except store.CartError as e:
        raise HTTPException(400, str(e))
    return agent.cart_view(cart)


@app.post("/api/confirm")
def confirm(body: ConfirmIn, request: Request):
    """F9, F10: the Confirm button. Creates the PayPal order and returns the approval link."""
    session = store.get_session(request.state.user_id)
    try:
        order = checkout.confirm(session, request.state.user_id, body.cart_id, base_url(request))
    except (store.CartError, checkout.CheckoutError) as e:
        raise HTTPException(400, str(e))
    return {"order_id": order["id"], "approve_url": order["approval_url"]}


# --- Mock PayPal approval page, only when no PayPal credentials are set ---

@app.get("/mock-paypal/checkout", response_class=HTMLResponse)
def mock_paypal_checkout(token: str):
    if paypal.enabled() or token not in paypal_mock.orders:
        raise HTTPException(404)
    amount = paypal_mock.orders[token]["purchase_units"][0]["amount"]
    t, cancel = html.escape(token), html.escape(paypal_mock.urls[token]["cancel_url"])
    return f"""<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mock PayPal</title><body style="font-family:system-ui;max-width:480px;margin:40px auto;padding:16px">
<p style="background:#fff3cd;padding:8px">MOCK PayPal: no PayPal credentials are configured. No real or sandbox payment happens.</p>
<h2>Pay {html.escape(amount["value"])} {html.escape(amount["currency_code"])}</h2>
<form method="post" action="/mock-paypal/approve"><input type="hidden" name="token" value="{t}">
<button style="padding:10px 20px">Approve payment</button></form>
<p><a href="{cancel}">Cancel and return to the store</a></p></body>"""


@app.post("/mock-paypal/approve")
async def mock_paypal_approve(request: Request):
    # Parsed by hand: FastAPI's form support needs an extra package.
    token = parse_qs((await request.body()).decode()).get("token", [""])[0]
    if paypal.enabled() or token not in paypal_mock.orders:
        raise HTTPException(404)
    paypal_mock.approve(token)
    # Real PayPal appends token and PayerID to the return URL; the app ignores both.
    return RedirectResponse(f"{paypal_mock.urls[token]['return_url']}&token={token}&PayerID=MOCKPAYER", status_code=303)
