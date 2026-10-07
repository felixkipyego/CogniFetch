from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_current_user
from app.auth import service, schemas
from app.db.models import User

router = APIRouter()


@router.post("/register", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: schemas.RegisterRequest, db: AsyncSession = Depends(get_db)):
    user, needs_verification = await service.register(db, body.email, body.password)
    return schemas.UserOut(
        id=user.id,
        email=user.email,
        needs_verification=needs_verification,
        created_at=user.created_at,
    )


@router.post("/login", response_model=schemas.TokenResponse)
async def login(body: schemas.LoginRequest, db: AsyncSession = Depends(get_db)):
    access_token, refresh_token = await service.login(db, body.email, body.password)
    return schemas.TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=schemas.AccessTokenResponse)
async def refresh(body: schemas.RefreshRequest, db: AsyncSession = Depends(get_db)):
    return schemas.AccessTokenResponse(access_token=await service.refresh(db, body.refresh_token))


@router.get("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    await service.verify_email(db, token)


@router.post("/resend-verification", status_code=status.HTTP_204_NO_CONTENT)
async def resend_verification(body: schemas.ResendVerificationRequest, db: AsyncSession = Depends(get_db)):
    await service.resend_verification(db, body.email)


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: schemas.ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await service.change_password(db, str(current_user.id), body.current_password, body.new_password)
