from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import timedelta, datetime
import json

from app.db.database import get_db
from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_active_user,
    normalize_nie_dni,
    is_valid_spanish_nie_dni,
    user_has_access,
)
from app.core.config import settings
from app.models.models import User, TaxReturn, TaxReturnStatus, Coupon, TaxRule
from app.schemas.schemas import (
    UserCreate, UserLogin, UserResponse, TokenResponse,
    TaxReturnCreate, TaxReturnUpdate, TaxReturnResponse,
    CalculationRequest, CalculationResponse, CheckoutResponse,
    TaxRuleResponse, TaxRuleCreate, CouponValidateRequest, CouponValidateResponse
)
from app.services.irpf_calculator import calcular_resultado_irpf, comparar_declaraciones
from app.services.payment_service import create_checkout_session, create_monthly_access_checkout_session
from app.services.pdf_service import generar_pdf_modelo100
from app.services.coupon_service import validate_coupon, use_coupon

router = APIRouter()


@router.post("/auth/register", response_model=TokenResponse)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == user_data.email))
    existing_user = result.scalar_one_or_none()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El email ya está registrado"
        )

    normalized_nie = None
    if user_data.nie:
        normalized_nie = normalize_nie_dni(user_data.nie)
        if not is_valid_spanish_nie_dni(normalized_nie):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="NIE/DNI invalide"
            )
        result = await db.execute(select(User).where(User.nie == normalized_nie))
        existing_nie_user = result.scalar_one_or_none()
        if existing_nie_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ce NIE/DNI est déjà utilisé"
            )
    
    db_user = User(
        email=user_data.email,
        password_hash=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        nie=normalized_nie,
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    
    access_token = create_access_token(
        data={"sub": db_user.email},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    return TokenResponse(access_token=access_token)


@router.post("/auth/login", response_model=TokenResponse)
async def login(user_data: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == user_data.email))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos"
        )
    
    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    return TokenResponse(access_token=access_token)


@router.get("/users/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_active_user)):
    setattr(current_user, "has_access", user_has_access(current_user))
    return current_user


@router.post("/billing/trial/start", response_model=UserResponse)
async def start_trial(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    now = datetime.utcnow()
    if current_user.trial_started_at and current_user.trial_ends_at and current_user.trial_ends_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Essai déjà terminé"
        )

    if not current_user.trial_started_at:
        current_user.trial_started_at = now
        current_user.trial_ends_at = now + timedelta(days=settings.TRIAL_DAYS)
        await db.commit()
        await db.refresh(current_user)

    setattr(current_user, "has_access", user_has_access(current_user, now=now))
    return current_user


@router.post("/billing/monthly/checkout", response_model=CheckoutResponse)
async def create_monthly_checkout(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if not current_user.nie:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="NIE/DNI requis"
        )
    normalized_nie = normalize_nie_dni(current_user.nie)
    if not is_valid_spanish_nie_dni(normalized_nie):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="NIE/DNI invalide"
        )
    current_user.nie = normalized_nie
    await db.commit()

    session = create_monthly_access_checkout_session(
        user_id=current_user.id,
        nie=normalized_nie,
    )
    return CheckoutResponse(checkout_url=session.url, free=False, discount_percent=0)


@router.post("/tax-returns/", response_model=TaxReturnResponse)
async def create_tax_return(
    tax_return_data: TaxReturnCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    db_tax_return = TaxReturn(
        user_id=current_user.id,
        year=tax_return_data.year,
        civil_status=tax_return_data.civil_status,
        autonomous_community=tax_return_data.autonomous_community,
        is_joint_declaration=tax_return_data.is_joint_declaration,
        status=TaxReturnStatus.DRAFT,
    )
    db.add(db_tax_return)
    await db.commit()
    await db.refresh(db_tax_return)
    
    return db_tax_return


@router.get("/tax-returns/", response_model=list[TaxReturnResponse])
async def list_tax_returns(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    result = await db.execute(
        select(TaxReturn).where(TaxReturn.user_id == current_user.id).order_by(TaxReturn.created_at.desc())
    )
    tax_returns = result.scalars().all()
    return tax_returns


@router.get("/tax-returns/{tax_return_id}", response_model=TaxReturnResponse)
async def get_tax_return(
    tax_return_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    result = await db.execute(
        select(TaxReturn).where(
            TaxReturn.id == tax_return_id,
            TaxReturn.user_id == current_user.id
        )
    )
    tax_return = result.scalar_one_or_none()
    
    if not tax_return:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Declaración no encontrada"
        )
    
    return tax_return


@router.patch("/tax-returns/{tax_return_id}", response_model=TaxReturnResponse)
async def update_tax_return(
    tax_return_id: int,
    tax_return_data: TaxReturnUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    result = await db.execute(
        select(TaxReturn).where(
            TaxReturn.id == tax_return_id,
            TaxReturn.user_id == current_user.id
        )
    )
    tax_return = result.scalar_one_or_none()
    
    if not tax_return:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Declaración no encontrada"
        )
    
    if tax_return_data.civil_status is not None:
        tax_return.civil_status = tax_return_data.civil_status
    if tax_return_data.autonomous_community is not None:
        tax_return.autonomous_community = tax_return_data.autonomous_community
    if tax_return_data.is_joint_declaration is not None:
        tax_return.is_joint_declaration = tax_return_data.is_joint_declaration
    if tax_return_data.raw_answers is not None:
        tax_return.raw_answers = json.dumps(tax_return_data.raw_answers)
    
    await db.commit()
    await db.refresh(tax_return)
    
    return tax_return


@router.post("/tax-returns/{tax_return_id}/calculate")
async def calculate_tax_return(
    tax_return_id: int,
    calculation_data: CalculationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    result = await db.execute(
        select(TaxReturn).where(
            TaxReturn.id == tax_return_id,
            TaxReturn.user_id == current_user.id
        )
    )
    tax_return = result.scalar_one_or_none()
    
    if not tax_return:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Declaración no encontrada"
        )
    
    datos = calculation_data.raw_answers.copy()
    datos["comunidad"] = tax_return.autonomous_community or "MAD"
    
    resultado = calcular_resultado_irpf(datos, calculation_data.is_joint_declaration)
    
    tax_return.calculation_result = json.dumps(resultado)
    tax_return.raw_answers = json.dumps(calculation_data.raw_answers)
    tax_return.is_joint_declaration = calculation_data.is_joint_declaration
    has_access = user_has_access(current_user)
    tax_return.status = TaxReturnStatus.PAID if has_access else TaxReturnStatus.PENDING_PAYMENT
    
    await db.commit()
    
    return {
        "tax_return_id": tax_return_id,
        "resultado": resultado,
        "requires_payment": not has_access,
    }


@router.post("/tax-returns/{tax_return_id}/compare")
async def compare_declarations(
    tax_return_id: int,
    datos_persona2: CalculationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    result = await db.execute(
        select(TaxReturn).where(
            TaxReturn.id == tax_return_id,
            TaxReturn.user_id == current_user.id
        )
    )
    tax_return = result.scalar_one_or_none()
    
    if not tax_return or not tax_return.calculation_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Declaración no encontrada o sin resultados"
        )
    
    datos_persona1 = json.loads(tax_return.calculation_result)
    datos_p2 = datos_persona2.raw_answers
    
    comparacion = comparar_declaraciones(datos_persona1, datos_p2)
    
    return comparacion


@router.post("/tax-returns/{tax_return_id}/checkout", response_model=CheckoutResponse)
async def create_checkout(
    tax_return_id: int,
    coupon_code: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    result = await db.execute(
        select(TaxReturn).where(
            TaxReturn.id == tax_return_id,
            TaxReturn.user_id == current_user.id
        )
    )
    tax_return = result.scalar_one_or_none()
    
    if not tax_return:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Declaración no encontrada"
        )
    
    if tax_return.status != TaxReturnStatus.PENDING_PAYMENT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La declaración no está lista para le paiement"
        )
    
    is_free = False
    discount_percent = 0
    
    if coupon_code:
        coupon = await validate_coupon(coupon_code, db)
        if coupon:
            is_free = coupon.discount_percent >= 100
            discount_percent = coupon.discount_percent
            tax_return.coupon_code = coupon_code.upper()
            tax_return.coupon_discount = coupon.discount_percent
            await db.commit()
    
    if is_free:
        tax_return.status = TaxReturnStatus.PAID
        await db.commit()
        await use_coupon(coupon_code, db)
        return CheckoutResponse(checkout_url="", free=True, discount_percent=discount_percent)
    
    session = create_checkout_session(tax_return_id, amount=1000)
    
    return CheckoutResponse(checkout_url=session.url, free=False, discount_percent=0)


@router.post("/coupons/validate", response_model=CouponValidateResponse)
async def validate_coupon_endpoint(
    coupon_data: CouponValidateRequest,
    db: AsyncSession = Depends(get_db)
):
    coupon = await validate_coupon(coupon_data.code, db)
    
    if coupon:
        return CouponValidateResponse(
            valid=True,
            discount_percent=coupon.discount_percent,
            description=coupon.description
        )
    
    return CouponValidateResponse(valid=False, discount_percent=0)


@router.post("/payments/webhook")
async def payment_webhook(
    payload: bytes,
    stripe_signature: str = Header(None, alias="stripe-signature"),
    db: AsyncSession = Depends(get_db)
):
    from app.services.payment_service import construct_webhook_event
    
    try:
        event = construct_webhook_event(payload, stripe_signature)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Signature invalide"
        )
    
    if event.type == "checkout.session.completed":
        session = event.data.object
        metadata = session.metadata or {}
        kind = metadata.get("kind")

        if kind == "monthly_access":
            user_id = int(metadata.get("user_id", 0))
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                now = datetime.utcnow()
                base = user.subscription_ends_at if user.subscription_ends_at and user.subscription_ends_at > now else now
                user.subscription_ends_at = base + timedelta(days=settings.MONTHLY_ACCESS_DURATION_DAYS)
                await db.commit()
        else:
            tax_return_id = int(metadata.get("tax_return_id", 0))
            result = await db.execute(
                select(TaxReturn).where(TaxReturn.id == tax_return_id)
            )
            tax_return = result.scalar_one_or_none()
            
            if tax_return:
                tax_return.status = TaxReturnStatus.PAID
                await db.commit()
    
    return {"status": "success"}


@router.get("/tax-returns/{tax_return_id}/download")
async def download_pdf(
    tax_return_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    result = await db.execute(
        select(TaxReturn).where(
            TaxReturn.id == tax_return_id,
            TaxReturn.user_id == current_user.id
        )
    )
    tax_return = result.scalar_one_or_none()
    
    if not tax_return:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Declaración no encontrada"
        )
    
    if tax_return.status != TaxReturnStatus.PAID and not user_has_access(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Es necesario pagar para descargar el documento"
        )
    
    datos_usuario = {
        "email": current_user.email,
        "nie": current_user.nie,
        "civil_status": tax_return.civil_status,
        "autonomous_community": tax_return.autonomous_community,
        "is_joint_declaration": tax_return.is_joint_declaration,
    }
    
    resultado = json.loads(tax_return.calculation_result) if tax_return.calculation_result else {}
    
    pdf_bytes = generar_pdf_modelo100(datos_usuario, resultado, tax_return.year)
    
    from fastapi.responses import Response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=modelo100_{tax_return.year}_{tax_return_id}.pdf"
        }
    )


@router.post("/admin/tax-rules", response_model=TaxRuleResponse)
async def create_tax_rule(
    rule_data: TaxRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere permisos de administrador"
        )
    
    db_rule = TaxRule(
        year=rule_data.year,
        scope=rule_data.scope,
        region_code=rule_data.region_code,
        rules_json=json.dumps(rule_data.rules_json),
    )
    db.add(db_rule)
    await db.commit()
    await db.refresh(db_rule)
    
    return db_rule
