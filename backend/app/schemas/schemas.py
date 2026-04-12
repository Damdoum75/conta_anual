from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class TaxReturnStatusEnum(str, Enum):
    DRAFT = "draft"
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    COMPLETED = "completed"


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: Optional[str] = None
    nie: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    nie: Optional[str]
    is_admin: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TaxReturnCreate(BaseModel):
    year: int = Field(..., ge=2020, le=2030)
    civil_status: Optional[str] = None
    autonomous_community: Optional[str] = None
    is_joint_declaration: bool = False


class TaxReturnUpdate(BaseModel):
    civil_status: Optional[str] = None
    autonomous_community: Optional[str] = None
    is_joint_declaration: Optional[bool] = None
    raw_answers: Optional[Dict[str, Any]] = None


class TaxReturnResponse(BaseModel):
    id: int
    user_id: int
    year: int
    status: TaxReturnStatusEnum
    civil_status: Optional[str]
    autonomous_community: Optional[str]
    is_joint_declaration: bool
    calculation_result: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CalculationRequest(BaseModel):
    raw_answers: Dict[str, Any]
    is_joint_declaration: bool = False


class CalculationResponse(BaseModel):
    base_imponible: float
    deducciones: Dict[str, float]
    tramos_aplicados: List[Dict[str, Any]]
    cuota_integral: float
    cuota_neta: float
    resultado: float
    resultado_tipo: str
    descripcion: str


class TaxRuleResponse(BaseModel):
    id: int
    year: int
    scope: str
    region_code: Optional[str]
    rules_json: Dict[str, Any]
    version: int

    class Config:
        from_attributes = True


class TaxRuleCreate(BaseModel):
    year: int
    scope: str
    region_code: Optional[str] = None
    rules_json: Dict[str, Any]


class CheckoutResponse(BaseModel):
    checkout_url: str
    free: bool = False
    discount_percent: float = 0


class CouponValidateRequest(BaseModel):
    code: str


class CouponValidateResponse(BaseModel):
    valid: bool
    discount_percent: float = 0
    description: Optional[str] = None


class PaymentWebhook(BaseModel):
    payment_intent_id: str
    status: str
    tax_return_id: int