from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
import enum

from app.db.database import Base


class TaxReturnStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    COMPLETED = "completed"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255))
    nie = Column(String(20))
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tax_returns = relationship("TaxReturn", back_populates="user")


class TaxReturn(Base):
    __tablename__ = "tax_returns"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    year = Column(Integer, nullable=False)
    status = Column(SQLEnum(TaxReturnStatus), default=TaxReturnStatus.DRAFT)
    
    civil_status = Column(String(50))
    autonomous_community = Column(String(50))
    is_joint_declaration = Column(Boolean, default=False)
    
    raw_answers = Column(Text)
    calculation_result = Column(Text)
    
    coupon_code = Column(String(50), nullable=True)
    coupon_discount = Column(Float, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="tax_returns")
    payments = relationship("Payment", back_populates="tax_return")


class Coupon(Base):
    __tablename__ = "coupons"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    discount_percent = Column(Float, default=100)
    max_uses = Column(Integer, default=100)
    current_uses = Column(Integer, default=0)
    valid_from = Column(DateTime, default=datetime.utcnow)
    valid_until = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    description = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)


class TaxRule(Base):
    __tablename__ = "tax_rules"

    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False)
    scope = Column(String(50))
    region_code = Column(String(10))
    rules_json = Column(Text)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    tax_return_id = Column(Integer, ForeignKey("tax_returns.id"), nullable=False)
    provider = Column(String(20))
    provider_payment_id = Column(String(100))
    amount = Column(Float)
    currency = Column(String(3))
    status = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)

    tax_return = relationship("TaxReturn", back_populates="payments")