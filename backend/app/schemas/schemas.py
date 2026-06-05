from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
import json


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
    trial_started_at: Optional[datetime] = None
    trial_ends_at: Optional[datetime] = None
    subscription_ends_at: Optional[datetime] = None
    has_access: bool = False

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
    raw_answers: Optional[Dict[str, Any]] = None
    calculation_result: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    @field_validator("raw_answers", mode="before")
    @classmethod
    def parse_raw_answers(cls, v):
        if v is None:
            return None
        if isinstance(v, (dict, list)):
            return v
        if isinstance(v, str) and v.strip():
            try:
                return json.loads(v)
            except Exception:
                return None
        return None

    @field_validator("calculation_result", mode="before")
    @classmethod
    def parse_calculation_result(cls, v):
        if v is None:
            return None
        if isinstance(v, (dict, list)):
            return v
        if isinstance(v, str) and v.strip():
            try:
                return json.loads(v)
            except Exception:
                return None
        return None

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


class PayslipExtractResponse(BaseModel):
    month: int
    filename: str
    extracted: Dict[str, Any]
    suggested_raw_answers_delta: Dict[str, Any]
    totals: Optional[Dict[str, Any]] = None
    source: Optional[str] = None
    ocr_used: Optional[bool] = None
    ocr_error: Optional[str] = None


class PayslipMeta(BaseModel):
    month: int
    filename: str
    uploaded_at: datetime


class PayslipOcrRequest(BaseModel):
    month: int = Field(..., ge=1, le=12)
    ocr_json: Dict[str, Any]


class ContentAnalyzeRequest(BaseModel):
    linkedin_url: Optional[str] = None
    article_url: Optional[str] = None
    article_text: Optional[str] = None


class ExtractedContentResponse(BaseModel):
    url: str
    ok: bool
    status_code: Optional[int] = None
    error: Optional[str] = None
    title: str = ""
    description: str = ""
    og_title: str = ""
    og_description: str = ""
    text_preview: str = ""


class ContentAnalyzeResponse(BaseModel):
    linkedin: Optional[ExtractedContentResponse] = None
    article: Optional[ExtractedContentResponse] = None
    analysis: Dict[str, Any]
