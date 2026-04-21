from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import re

from app.core.config import settings
from app.db.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        token = credentials.credentials
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    
    if user is None:
        raise credentials_exception
    
    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user


def normalize_nie_dni(value: str) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def is_valid_spanish_nie_dni(value: str) -> bool:
    value = normalize_nie_dni(value)
    dni_letters = "TRWAGMYFPDXBNJZSQVHLCKE"

    m_dni = re.fullmatch(r"(\d{8})([A-Z])", value)
    if m_dni:
        number = int(m_dni.group(1))
        letter = m_dni.group(2)
        return dni_letters[number % 23] == letter

    m_nie = re.fullmatch(r"([XYZ])(\d{7})([A-Z])", value)
    if m_nie:
        prefix = m_nie.group(1)
        number_part = m_nie.group(2)
        letter = m_nie.group(3)
        prefix_digit = {"X": "0", "Y": "1", "Z": "2"}[prefix]
        number = int(prefix_digit + number_part)
        return dni_letters[number % 23] == letter

    return False


def user_has_access(user: User, now: Optional[datetime] = None) -> bool:
    now = now or datetime.utcnow()
    if user.subscription_ends_at and user.subscription_ends_at > now:
        return True
    if user.trial_ends_at and user.trial_ends_at > now:
        return True
    return False
