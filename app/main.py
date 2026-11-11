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

from app import agent, catalog, checkout, llm, memory, paypal, paypal_mock, store

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


class CartLine(BaseModel):
    product_id: str
    quantity: int = 1


class CartIn(BaseModel):
    """One product (the card's Choose button) or several (`items`, F21); exactly one of the two."""
    product_id: str | None = None
    quantity: int = 1
    items: list[CartLine] | None = None


class ConfirmIn(BaseModel):
    cart_id: str


class RefundIn(BaseModel):
    lines: list[int] | None = None  # F23: line numbers; None means every line not refunded yet


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


@app.post("/api/conversation/new")
def new_conversation(request: Request):
    """F19: a fresh conversation; saved preferences will be applied to its recommendations."""
    store.new_conversation(request.state.user_id)
    return {"ok": True}


@app.get("/api/memory")
def list_memory(request: Request):
    """F20: everything remembered about this user, strongest first."""
    return [{"id": p["id"], "text": p["text"], "strength": p["strength"], "evidence_count": p["evidence_count"]}
            for p in memory.list_preferences(request.state.user_id)]


@app.delete("/api/memory/{pref_id}")
def delete_memory(pref_id: int, request: Request):
    """F20: the user deletes one entry. It also stops applying to the current conversation."""
    if not memory.delete(request.state.user_id, pref_id):
        raise HTTPException(404, "Not found")
    session = store.get_session(request.state.user_id)
    if session.memory_profile:
        session.memory_profile = [m for m in session.memory_profile if m["id"] != pref_id]
    return {"ok": True}


@app.post("/api/cart")
def create_cart(body: CartIn, request: Request):
    """F8, F21: the "Choose" button on a card, or a list of items. Same rules as the model's prepare_cart tool."""
    if (body.product_id is None) == (body.items is None):
        raise HTTPException(400, "Send either product_id or items, not both.")
    session = store.get_session(request.state.user_id)
    lines = [(body.product_id, body.quantity)] if body.items is None else [(i.product_id, i.quantity) for i in body.items]
    try:
        cart = store.create_cart_items(session, lines)
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


@app.get("/paypal/return")
def paypal_return(order_id: int, request: Request):
    """F11: PayPal sends the buyer here after approval. Verify and capture, then show the result page."""
    try:
        checkout.handle_return(request.state.user_id, order_id)
    except checkout.CheckoutError:
        raise HTTPException(404, "Order not found")
    # Redirect so a refresh of the result page only reads the order and never captures again.
    return RedirectResponse(f"/?order_id={order_id}", status_code=303)


@app.get("/paypal/cancel")
def paypal_cancel(order_id: int, request: Request):
    """F13: PayPal sends the buyer here after Cancel."""
    try:
        checkout.handle_cancel(request.state.user_id, order_id)
    except checkout.CheckoutError:
        raise HTTPException(404, "Order not found")
    return RedirectResponse(f"/?order_id={order_id}", status_code=303)


@app.get("/api/orders/{order_id}")
def get_order(order_id: int, request: Request):
    """F14: the result page reads the stored order; only the owner can see it."""
    order = store.get_order(order_id, request.state.user_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    return checkout.order_view(order)


@app.post("/api/orders/{order_id}/refund")
def refund_order(order_id: int, request: Request, body: RefundIn | None = None):
    """F16, F23: the Confirm refund button. The only place a refund is sent to PayPal. No body = all remaining lines."""
    try:
        order = checkout.refund(request.state.user_id, order_id, body.lines if body else None)
    except checkout.CheckoutError as e:
        raise HTTPException(400, str(e))
    return checkout.order_view(order)


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
