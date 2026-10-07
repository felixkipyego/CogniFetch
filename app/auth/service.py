import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException, status

from app.config import settings
from app.db.models import User
from app.auth.utils import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    create_email_verification_token,
    decode_token,
)
from app.auth.email import send_verification_email

logger = logging.getLogger(__name__)


async def register(db: AsyncSession, email: str, password: str) -> tuple[User, bool]:
    """
    Returns (user, needs_verification).
    needs_verification is True when SMTP is configured and a verification email was sent.
    """
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    count_result = await db.execute(select(func.count()).select_from(User))
    is_first_user = count_result.scalar() == 0

    needs_verification = bool(settings.smtp_host)

    user = User(
        email=email,
        hashed_password=hash_password(password),
        is_admin=is_first_user,
        is_verified=not needs_verification,
    )

    if needs_verification:
        token = create_email_verification_token(str(user.id))
        user.email_token = token

    db.add(user)
    await db.commit()
    await db.refresh(user)

    if needs_verification:
        try:
            await send_verification_email(email, user.email_token)
        except Exception:
            logger.exception("Failed to send verification email to %s", email)

    return user, needs_verification


async def login(db: AsyncSession, email: str, password: str) -> tuple[str, str]:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before signing in. Check your inbox and spam folder.",
        )
    access = create_access_token(str(user.id), is_admin=user.is_admin)
    refresh = create_refresh_token(str(user.id))
    return access, refresh


async def refresh(db: AsyncSession, refresh_token: str) -> str:
    payload = decode_token(refresh_token, expected_type="refresh")
    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return create_access_token(str(user.id), is_admin=user.is_admin)


async def change_password(db: AsyncSession, user_id: str, current_password: str, new_password: str) -> None:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not verify_password(current_password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if len(new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 8 characters")
    user.hashed_password = hash_password(new_password)
    await db.commit()


async def verify_email(db: AsyncSession, token: str) -> None:
    payload = decode_token(token, expected_type="email_verify")
    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.is_verified:
        return  # already verified — treat as success
    if user.email_token != token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This verification link has already been used or is no longer valid.",
        )
    user.is_verified = True
    user.email_token = None
    await db.commit()


async def resend_verification(db: AsyncSession, email: str) -> None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    # Silent no-op for unknown or already-verified emails (avoids user enumeration)
    if not user or user.is_verified:
        return
    token = create_email_verification_token(str(user.id))
    user.email_token = token
    await db.commit()
    try:
        await send_verification_email(email, token)
    except Exception:
        logger.exception("Failed to resend verification email to %s", email)
