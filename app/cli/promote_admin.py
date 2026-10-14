"""Promote a user to admin and force MFA.

Run:
    uv run python -m app.cli.promote_admin user@example.com
"""

import asyncio
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models.user import User, UserRole


async def promote(email: str) -> None:
    normalized = email.strip().lower()
    async with SessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.email == normalized))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                email=normalized,
                role=UserRole.ADMIN,
                mfa_required=True,
                is_active=True,
            )
            db.add(user)
            action = "created"
        else:
            user.role = UserRole.ADMIN
            user.mfa_required = True
            user.is_active = True
            action = "updated"
        await db.commit()
        print(f"Admin {action}: {user.email} (role={user.role.value}, mfa_required={user.mfa_required})")


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m app.cli.promote_admin <email>", file=sys.stderr)
        sys.exit(2)
    asyncio.run(promote(sys.argv[1]))


if __name__ == "__main__":
    main()
