from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Coupon


async def validate_coupon(code: str, db: AsyncSession) -> Optional[Coupon]:
    result = await db.execute(
        select(Coupon).where(
            Coupon.code == code.upper(),
            Coupon.is_active == True
        )
    )
    coupon = result.scalar_one_or_none()
    
    if not coupon:
        return None
    
    now = datetime.utcnow()
    if coupon.valid_until and coupon.valid_until < now:
        return None
    
    if coupon.current_uses >= coupon.max_uses:
        return None
    
    return coupon


async def use_coupon(code: str, db: AsyncSession) -> bool:
    result = await db.execute(
        select(Coupon).where(Coupon.code == code.upper())
    )
    coupon = result.scalar_one_or_none()
    
    if coupon:
        coupon.current_uses += 1
        await db.commit()
        return True
    
    return False


async def create_default_coupons(db: AsyncSession):
    existing = await db.execute(select(Coupon).where(Coupon.code == "TESTFREE"))
    if not existing.scalar_one_or_none():
        test_coupon = Coupon(
            code="TESTFREE",
            discount_percent=100,
            max_uses=1000,
            valid_until=datetime.utcnow() + timedelta(days=30),
            description="Coupon gratuit pour tests - Test gratuit semanas",
            is_active=True
        )
        db.add(test_coupon)
        
        promo_coupon = Coupon(
            code="PROMO2025",
            discount_percent=100,
            max_uses=500,
            valid_until=datetime.utcnow() + timedelta(days=365),
            description="Promotion lancement - Test gratuit",
            is_active=True
        )
        db.add(promo_coupon)
        
        await db.commit()