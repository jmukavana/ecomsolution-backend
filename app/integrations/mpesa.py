"""Safaricom Daraja STK Push client + callback parsing.

Sandbox: api.safaricom.co.ke is the production host; sandbox is sandbox.safaricom.co.ke.
Set MPESA_ENV=sandbox|production.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)


def _api_base() -> str:
    if settings.MPESA_ENV == "production":
        return "https://api.safaricom.co.ke"
    return "https://sandbox.safaricom.co.ke"


def _format_phone_for_daraja(phone: str) -> str:
    """Daraja expects 2547XXXXXXXX (no '+'). Accepts E.164 or local form."""
    raw = phone.strip().replace(" ", "").replace("-", "")
    if raw.startswith("+254"):
        return raw[1:]
    if raw.startswith("254"):
        return raw
    if raw.startswith("0") and len(raw) == 10:
        return "254" + raw[1:]
    if raw.startswith("7") and len(raw) == 9:
        return "254" + raw
    raise ValueError("invalid Kenyan phone number")


@dataclass(slots=True)
class StkPushResult:
    merchant_request_id: str
    checkout_request_id: str
    response_code: str
    response_description: str
    customer_message: str


class MpesaError(RuntimeError):
    pass


async def _get_access_token() -> str:
    auth = base64.b64encode(
        f"{settings.MPESA_CONSUMER_KEY}:{settings.MPESA_CONSUMER_SECRET}".encode()
    ).decode()
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(
            f"{_api_base()}/oauth/v1/generate?grant_type=client_credentials",
            headers={"Authorization": f"Basic {auth}"},
        )
        if res.status_code != 200:
            raise MpesaError(f"Daraja OAuth failed: {res.status_code} {res.text}")
        return res.json()["access_token"]


def _build_password(timestamp: str) -> str:
    raw = f"{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}"
    return base64.b64encode(raw.encode()).decode()


async def initiate_stk_push(
    *,
    phone: str,
    amount: int,
    account_ref: str,
    description: str,
) -> StkPushResult:
    """Trigger an STK Push prompt on the customer's phone.

    Raises MpesaError on Daraja-level failures. Daraja sometimes returns 200 with
    a non-zero `ResponseCode`; we surface that via the result object.
    """
    if not (settings.MPESA_CONSUMER_KEY and settings.MPESA_CONSUMER_SECRET and settings.MPESA_PASSKEY):
        raise MpesaError("M-Pesa credentials not configured (set MPESA_* in .env)")
    if not settings.MPESA_CALLBACK_URL:
        raise MpesaError("MPESA_CALLBACK_URL not configured (use ngrok in dev)")

    token = await _get_access_token()
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    body = {
        "BusinessShortCode": settings.MPESA_SHORTCODE,
        "Password": _build_password(ts),
        "Timestamp": ts,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(amount),
        "PartyA": _format_phone_for_daraja(phone),
        "PartyB": settings.MPESA_SHORTCODE,
        "PhoneNumber": _format_phone_for_daraja(phone),
        "CallBackURL": settings.MPESA_CALLBACK_URL,
        "AccountReference": account_ref[:12],
        "TransactionDesc": description[:13],
    }
    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(
            f"{_api_base()}/mpesa/stkpush/v1/processrequest",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
    if res.status_code != 200:
        raise MpesaError(f"STK Push HTTP {res.status_code}: {res.text}")
    data = res.json()
    return StkPushResult(
        merchant_request_id=data.get("MerchantRequestID", ""),
        checkout_request_id=data.get("CheckoutRequestID", ""),
        response_code=str(data.get("ResponseCode", "")),
        response_description=data.get("ResponseDescription", ""),
        customer_message=data.get("CustomerMessage", ""),
    )


@dataclass(slots=True)
class CallbackOutcome:
    checkout_request_id: str
    success: bool
    result_code: int
    result_desc: str
    amount: int | None
    mpesa_receipt: str | None
    phone_number: str | None


def parse_callback(payload: dict[str, Any]) -> CallbackOutcome:
    """Parse the JSON Safaricom POSTs to MPESA_CALLBACK_URL."""
    body = payload.get("Body") or {}
    stk = body.get("stkCallback") or {}
    result_code = int(stk.get("ResultCode", -1))
    items: list[dict[str, Any]] = (
        (stk.get("CallbackMetadata") or {}).get("Item") or []
    )
    by_name = {item.get("Name"): item.get("Value") for item in items}
    return CallbackOutcome(
        checkout_request_id=stk.get("CheckoutRequestID", ""),
        success=result_code == 0,
        result_code=result_code,
        result_desc=stk.get("ResultDesc", ""),
        amount=int(by_name["Amount"]) if "Amount" in by_name else None,
        mpesa_receipt=str(by_name.get("MpesaReceiptNumber"))
        if "MpesaReceiptNumber" in by_name
        else None,
        phone_number=str(by_name.get("PhoneNumber"))
        if "PhoneNumber" in by_name
        else None,
    )
