"""Seed notification templates.

Run:
    uv run python -m app.cli.seed_templates
"""

import asyncio

from sqlalchemy import delete

from app.db import SessionLocal
from app.models.notification import NotificationChannel, NotificationTemplate

TEMPLATES: list[dict] = [
    # ---- Auth ----
    {
        "key": "auth.otp",
        "channel": NotificationChannel.EMAIL,
        "subject_template": "Your Ecom-solution login code",
        "body_template": (
            "Hi{% if name %} {{ name }}{% endif %},\n\n"
            "Your one-time login code is: {{ code }}\n\n"
            "It expires in {{ ttl_minutes }} minutes. "
            "If you didn't request this, you can safely ignore this email.\n\n"
            "- Ecom-solution"
        ),
    },
    {
        "key": "auth.new_device",
        "channel": NotificationChannel.EMAIL,
        "subject_template": "New sign-in to your Ecom-solution account",
        "body_template": (
            "A new device just signed in to your account:\n\n"
            "  IP: {{ ip }}\n"
            "  Device: {{ user_agent }}\n"
            "  Time: {{ when }}\n\n"
            "If this wasn't you, sign in and revoke the session from "
            "Account → Security → Sessions.\n"
        ),
    },
    {
        "key": "auth.new_device",
        "channel": NotificationChannel.IN_APP,
        "subject_template": "New sign-in detected",
        "body_template": "A new device signed in from {{ ip }} at {{ when }}.",
    },
    # ---- Orders (customer) ----
    {
        "key": "order.placed",
        "channel": NotificationChannel.EMAIL,
        "subject_template": "Order #{{ order_id }} received",
        "body_template": (
            "Thanks for your order!\n\n"
            "  Order:  #{{ order_id }}\n"
            "  Total:  KSh {{ total }}\n"
            "  Payment: {{ payment_method }}\n\n"
            "We'll send another email once payment is confirmed.\n"
        ),
    },
    {
        "key": "order.placed",
        "channel": NotificationChannel.IN_APP,
        "subject_template": "Order #{{ order_id }} placed",
        "body_template": "We've received order #{{ order_id }} (KSh {{ total }}).",
    },
    {
        "key": "order.paid",
        "channel": NotificationChannel.EMAIL,
        "subject_template": "Payment received for order #{{ order_id }}",
        "body_template": (
            "Your payment of KSh {{ total }} for order #{{ order_id }} was received.\n"
            "{% if mpesa_receipt %}M-Pesa receipt: {{ mpesa_receipt }}\n{% endif %}"
            "We're now preparing your items for dispatch.\n"
        ),
    },
    {
        "key": "order.paid",
        "channel": NotificationChannel.IN_APP,
        "subject_template": "Payment confirmed",
        "body_template": "Order #{{ order_id }} is paid. Preparing for dispatch.",
    },
    {
        "key": "order.shipped",
        "channel": NotificationChannel.EMAIL,
        "subject_template": "Order #{{ order_id }} shipped",
        "body_template": (
            "Good news — your order #{{ order_id }} is on its way!\n"
            "{% if courier %}Courier: {{ courier }}\n{% endif %}"
            "{% if tracking %}Tracking: {{ tracking }}\n{% endif %}"
        ),
    },
    {
        "key": "order.shipped",
        "channel": NotificationChannel.IN_APP,
        "subject_template": "Order shipped",
        "body_template": "Order #{{ order_id }} is on the way.",
    },
    {
        "key": "order.delivered",
        "channel": NotificationChannel.EMAIL,
        "subject_template": "Order #{{ order_id }} delivered",
        "body_template": (
            "Your order #{{ order_id }} was marked delivered. Enjoy!\n\n"
            "If anything's wrong, reply to this email within 48 hours.\n"
        ),
    },
    {
        "key": "order.delivered",
        "channel": NotificationChannel.IN_APP,
        "subject_template": "Order delivered",
        "body_template": "Order #{{ order_id }} was delivered.",
    },
    # ---- Admin alerts ----
    {
        "key": "admin.new_order",
        "channel": NotificationChannel.IN_APP,
        "subject_template": "New order #{{ order_id }}",
        "body_template": "{{ customer }} placed order #{{ order_id }} for KSh {{ total }}.",
    },
    {
        "key": "admin.low_stock",
        "channel": NotificationChannel.IN_APP,
        "subject_template": "Low stock: {{ product_name }}",
        "body_template": (
            "Variant {{ variant_sku }} has {{ stock }} unit(s) left "
            "(threshold {{ threshold }})."
        ),
    },
]


async def seed() -> None:
    async with SessionLocal() as db:
        await db.execute(delete(NotificationTemplate))
        for t in TEMPLATES:
            db.add(NotificationTemplate(**t))
        await db.commit()
        print(f"Seeded {len(TEMPLATES)} notification templates.")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
