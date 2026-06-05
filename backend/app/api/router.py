from fastapi import APIRouter, Depends, HTTPException, status, Header, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import timedelta, datetime
import json
from pathlib import Path
import re
import httpx

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
    TaxRuleResponse, TaxRuleCreate, CouponValidateRequest, CouponValidateResponse,
    PayslipExtractResponse, PayslipMeta, PayslipOcrRequest,
    ContentAnalyzeRequest, ContentAnalyzeResponse, ExtractedContentResponse,
)
from app.services.irpf_calculator import calcular_resultado_irpf, comparar_declaraciones
from app.services.payment_service import create_checkout_session, create_monthly_access_checkout_session
from app.services.pdf_service import generar_pdf_modelo100
from app.services.coupon_service import validate_coupon, use_coupon
from app.services.content_analysis_service import fetch_and_extract, analyze_text

router = APIRouter()

UPLOADS_DIR = Path(__file__).resolve().parents[2] / "uploads"


def _parse_amount(value: str) -> float:
    s = (value or "").strip()
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[^\d,.\-]", "", s)
    if s.count(",") >= 1 and s.count(".") >= 1:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(",") >= 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def _extract_from_pdf_bytes(pdf_bytes: bytes) -> dict:
    from pdfminer.high_level import extract_text
    from io import BytesIO

    text = extract_text(BytesIO(pdf_bytes)) or ""
    t = re.sub(r"\s+", " ", text).strip()

    patterns = [
        ("ingresos_trabajo", r"(?:a\.\s*total\s+devengad[oa]|total\s+devengad[oa]|devengos\s+totales|bruto\s+total)\s*[:\-]?\s*([0-9][0-9\.,]*)"),
        ("retenciones", r"(?:\d+\s*[\.\)]\s*)?(?:b\.\s*)?(?:irpf|retenci[oó]n(?:es)?\s+a\s+cuenta\s+del\s+irpf|retenci[oó]n(?:es)?\s+irpf)(?:\s+en\s+especie)?\s*[:\-]?\s*([0-9][0-9\.,]*)"),
        ("contribuciones_pension", r"(?:\d+\s*[\.\)]\s*)?(?:total\s+aportaciones|aportaci[oó]n\s+trabajador(?:a)?\s+a\s+la\s+seguridad\s+social|seguridad\s+social|cotizaci[oó]n(?:es)?)\s*[:\-]?\s*([0-9][0-9\.,]*)"),
        ("liquido", r"(?:l[ií]quido\s+total\s+a\s+percibir|l[ií]quido\s+a\s+percibir|total\s+a\s+percibir|neto\s+a\s+percibir|total\s+liquido)\s*[:\-]?\s*([0-9][0-9\.,]*)"),
        ("total_deducir", r"(?:b\.\s*total\s+a\s+deducir|total\s+a\s+deducir)\s*[:\-]?\s*([0-9][0-9\.,]*)"),
    ]

    extracted = {"raw_text_preview": t[:800]}
    for key, pat in patterns:
        m = re.search(pat, t, flags=re.IGNORECASE)
        if m:
            extracted[key] = _parse_amount(m.group(1))

    return extracted


def _find_number_by_keys(obj: object, keys: list[str]) -> float | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and any(kk in k.lower() for kk in keys):
                if isinstance(v, (int, float)):
                    return float(v)
                if isinstance(v, str):
                    val = _parse_amount(v)
                    if val:
                        return val
            found = _find_number_by_keys(v, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_number_by_keys(v, keys)
            if found is not None:
                return found
    return None


def _collect_text(obj: object, limit: int = 20000) -> str:
    parts: list[str] = []

    def walk(o: object):
        if len(" ".join(parts)) >= limit:
            return
        if isinstance(o, str):
            s = o.strip()
            if s:
                parts.append(s)
            return
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(k, str) and k.strip():
                    parts.append(k.strip())
                walk(v)
            return
        if isinstance(o, list):
            for v in o:
                walk(v)
            return

    walk(obj)
    return " ".join(parts)[:limit]


def _extract_from_ocr_json(ocr_json: dict) -> dict:
    extracted: dict = {}

    direct_brut = ocr_json.get("ingresos_trabajo")
    direct_irpf = ocr_json.get("retenciones")
    direct_ss = ocr_json.get("contribuciones_pension")
    direct_net = ocr_json.get("liquido")

    if isinstance(direct_brut, (int, float, str)):
        val = _parse_amount(direct_brut) if isinstance(direct_brut, str) else float(direct_brut)
        if val:
            extracted["ingresos_trabajo"] = val
    if isinstance(direct_irpf, (int, float, str)):
        val = _parse_amount(direct_irpf) if isinstance(direct_irpf, str) else float(direct_irpf)
        if val:
            extracted["retenciones"] = val
    if isinstance(direct_ss, (int, float, str)):
        val = _parse_amount(direct_ss) if isinstance(direct_ss, str) else float(direct_ss)
        if val:
            extracted["contribuciones_pension"] = val
    if isinstance(direct_net, (int, float, str)):
        val = _parse_amount(direct_net) if isinstance(direct_net, str) else float(direct_net)
        if val:
            extracted["liquido"] = val

    brut = _find_number_by_keys(ocr_json, ["bruto", "brut", "deveng", "gross", "total_deveng"])
    irpf = _find_number_by_keys(ocr_json, ["irpf", "retenc"])
    ss = _find_number_by_keys(ocr_json, ["seguridad", "social", "ss", "cotiz", "aportacion"])
    net = _find_number_by_keys(ocr_json, ["liquido", "líquido", "neto", "percibir", "total_a_percibir"])

    if brut and "ingresos_trabajo" not in extracted:
        extracted["ingresos_trabajo"] = brut
    if irpf and "retenciones" not in extracted:
        extracted["retenciones"] = irpf
    if ss and "contribuciones_pension" not in extracted:
        extracted["contribuciones_pension"] = ss
    if net and "liquido" not in extracted:
        extracted["liquido"] = net

    text = ""
    for candidate_key in ("text", "full_text", "raw_text", "content"):
        v = ocr_json.get(candidate_key)
        if isinstance(v, str) and v.strip():
            text = v
            break
    if not text:
        text = _collect_text(ocr_json, limit=20000)

    if text:
        t = re.sub(r"\s+", " ", text).strip()
        extracted.setdefault("raw_text_preview", t[:800])
        if "retenciones" not in extracted:
            m = re.search(r"(?:\d+\s*[\.\)]\s*)?(?:b\.\s*)?(?:irpf|retenci[oó]n(?:es)?\s+a\s+cuenta\s+del\s+irpf|retenci[oó]n(?:es)?\s+irpf)(?:\s+en\s+especie)?\s*[:\-]?\s*([0-9][0-9\.,]*)", t, flags=re.IGNORECASE)
            if m:
                extracted["retenciones"] = _parse_amount(m.group(1))
        if "contribuciones_pension" not in extracted:
            m = re.search(r"(?:\d+\s*[\.\)]\s*)?(?:total\s+aportaciones|aportaci[oó]n\s+trabajador(?:a)?\s+a\s+la\s+seguridad\s+social|seguridad\s+social|cotizaci[oó]n(?:es)?)\s*[:\-]?\s*([0-9][0-9\.,]*)", t, flags=re.IGNORECASE)
            if m:
                extracted["contribuciones_pension"] = _parse_amount(m.group(1))
        if "ingresos_trabajo" not in extracted:
            m = re.search(r"(?:a\.\s*total\s+devengad[oa]|total\s+devengad[oa]|devengos\s+totales|bruto\s+total)\s*[:\-]?\s*([0-9][0-9\.,]*)", t, flags=re.IGNORECASE)
            if m:
                extracted["ingresos_trabajo"] = _parse_amount(m.group(1))
        if "liquido" not in extracted:
            m = re.search(r"(?:l[ií]quido\s+total\s+a\s+percibir|l[ií]quido\s+a\s+percibir|total\s+a\s+percibir|neto\s+a\s+percibir|total\s+liquido)\s*[:\-]?\s*([0-9][0-9\.,]*)", t, flags=re.IGNORECASE)
            if m:
                extracted["liquido"] = _parse_amount(m.group(1))

    return extracted


def _upsert_nomina_and_totals(raw: dict, month: int, entry: dict) -> dict:
    nominas = raw.get("nominas", [])
    if not isinstance(nominas, list):
        nominas = []
    nominas = [n for n in nominas if not (isinstance(n, dict) and int(n.get("month", 0)) == month)]
    nominas.append(entry)
    nominas = sorted(nominas, key=lambda x: int(x.get("month", 0)))
    raw["nominas"] = nominas

    total_brut = 0.0
    total_irpf = 0.0
    total_ss = 0.0
    for n in nominas:
        if not isinstance(n, dict):
            continue
        delta = n.get("delta") if isinstance(n.get("delta"), dict) else {}
        total_brut += float(delta.get("ingresos_trabajo", 0) or 0)
        total_irpf += float(delta.get("retenciones", 0) or 0)
        total_ss += float(delta.get("contribuciones_pension", 0) or 0)

    raw["ingresos_trabajo"] = round(total_brut, 2)
    raw["retenciones"] = round(total_irpf, 2)
    raw["contribuciones_pension"] = round(total_ss, 2)
    raw["nominas_totals"] = {
        "ingresos_trabajo": raw["ingresos_trabajo"],
        "retenciones": raw["retenciones"],
        "contribuciones_pension": raw["contribuciones_pension"],
    }
    return raw


async def _call_ocr_service(filename: str, content: bytes) -> tuple[dict | None, str | None]:
    if not settings.OCR_SERVICE_ENABLED:
        return None, "OCR service disabled"
    url = (settings.OCR_SERVICE_URL or "").strip()
    if not url:
        return None, "OCR service URL is empty"

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                url,
                files={"file": (filename or "document.pdf", content, "application/pdf")},
            )
        if resp.status_code >= 400:
            body = (resp.text or "").strip()
            body = body[:500] if body else ""
            msg = f"OCR service error {resp.status_code}"
            if body:
                msg = f"{msg}: {body}"
            return None, msg
        data = resp.json()
        if not isinstance(data, dict):
            return None, "OCR service returned a non-JSON object"
        return data, None
    except Exception as e:
        return None, f"OCR service request failed: {type(e).__name__}"


async def _get_tax_return_owned(db: AsyncSession, tax_return_id: int, user_id: int) -> TaxReturn:
    result = await db.execute(
        select(TaxReturn).where(
            TaxReturn.id == tax_return_id,
            TaxReturn.user_id == user_id,
        )
    )
    tax_return = result.scalar_one_or_none()
    if not tax_return:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Declaración no encontrada")
    return tax_return


@router.post("/auth/register", response_model=TokenResponse)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    if settings.DISABLE_REGISTRATION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inscription désactivée temporairement"
        )
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


@router.get("/tax-returns/{tax_return_id}/payslips", response_model=list[PayslipMeta])
async def list_payslips(
    tax_return_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tax_return = await _get_tax_return_owned(db, tax_return_id, current_user.id)
    raw = json.loads(tax_return.raw_answers) if tax_return.raw_answers else {}
    nominas = raw.get("nominas", [])
    if not isinstance(nominas, list):
        return []
    items: list[PayslipMeta] = []
    for n in sorted([x for x in nominas if isinstance(x, dict)], key=lambda x: int(x.get("month", 0))):
        month = int(n.get("month", 0))
        if month < 1 or month > 12:
            continue
        filename = str(n.get("filename") or "")
        uploaded_at_raw = n.get("uploaded_at")
        uploaded_at = datetime.utcnow()
        if isinstance(uploaded_at_raw, str):
            try:
                uploaded_at = datetime.fromisoformat(uploaded_at_raw.replace("Z", "+00:00"))
            except Exception:
                uploaded_at = datetime.utcnow()
        items.append(PayslipMeta(month=month, filename=filename, uploaded_at=uploaded_at))
    return items


@router.get("/tax-returns/{tax_return_id}/payslips/{month}/download")
async def download_payslip(
    tax_return_id: int,
    month: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await _get_tax_return_owned(db, tax_return_id, current_user.id)
    if month < 1 or month > 12:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mois invalide")
    folder = UPLOADS_DIR / str(tax_return_id)
    matches = list(folder.glob(f"{month:02d}_*.pdf"))
    if not matches:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nómina introuvable")
    path = matches[0]
    from fastapi.responses import FileResponse
    return FileResponse(path=str(path), media_type="application/pdf", filename=path.name)


@router.post("/tax-returns/{tax_return_id}/payslips/extract", response_model=PayslipExtractResponse)
async def upload_and_extract_payslip(
    tax_return_id: int,
    month: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tax_return = await _get_tax_return_owned(db, tax_return_id, current_user.id)
    if month < 1 or month > 12:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mois invalide")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Format non supporté (PDF requis)")

    content = await file.read()
    extracted = _extract_from_pdf_bytes(content)
    ocr_used = False
    ocr_error = None
    if (
        ("retenciones" not in extracted or "contribuciones_pension" not in extracted)
        and settings.OCR_SERVICE_ENABLED
    ):
        ocr_payload, ocr_error = await _call_ocr_service(file.filename, content)
        if isinstance(ocr_payload, dict) and ocr_payload:
            ocr_used = True
            extracted_ocr = _extract_from_ocr_json(ocr_payload)
            for k in ("ingresos_trabajo", "retenciones", "contribuciones_pension", "liquido"):
                if k in extracted_ocr:
                    extracted[k] = extracted_ocr[k]
            if extracted_ocr.get("raw_text_preview"):
                extracted["raw_text_preview"] = extracted_ocr["raw_text_preview"]

    folder = UPLOADS_DIR / str(tax_return_id)
    folder.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", Path(file.filename).name)
    save_path = folder / f"{month:02d}_{safe_name}"
    save_path.write_bytes(content)

    delta = {}
    if "ingresos_trabajo" in extracted:
        delta["ingresos_trabajo"] = extracted["ingresos_trabajo"]
    if "retenciones" in extracted:
        delta["retenciones"] = extracted["retenciones"]
    if "contribuciones_pension" in extracted:
        delta["contribuciones_pension"] = extracted["contribuciones_pension"]

    raw = json.loads(tax_return.raw_answers) if tax_return.raw_answers else {}
    raw = _upsert_nomina_and_totals(raw, month, {
        "month": month,
        "filename": save_path.name,
        "uploaded_at": datetime.utcnow().isoformat(),
        "source": "pdf_text" if not settings.OCR_SERVICE_ENABLED else ("ocr_service" if ocr_used else "pdf_text"),
        "extracted": extracted,
        "delta": delta,
        "ocr_used": ocr_used,
        "ocr_error": ocr_error,
    })
    tax_return.raw_answers = json.dumps(raw)
    await db.commit()

    return PayslipExtractResponse(
        month=month,
        filename=save_path.name,
        extracted=extracted,
        suggested_raw_answers_delta=delta,
        totals=raw.get("nominas_totals"),
        source="ocr_service" if ocr_used else "pdf_text",
        ocr_used=ocr_used,
        ocr_error=ocr_error,
    )


@router.post("/tax-returns/{tax_return_id}/payslips/ocr", response_model=PayslipExtractResponse)
async def upload_ocr_json_payslip(
    tax_return_id: int,
    payload: PayslipOcrRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tax_return = await _get_tax_return_owned(db, tax_return_id, current_user.id)
    month = int(payload.month)
    extracted = _extract_from_ocr_json(payload.ocr_json or {})

    delta = {}
    if "ingresos_trabajo" in extracted:
        delta["ingresos_trabajo"] = extracted["ingresos_trabajo"]
    if "retenciones" in extracted:
        delta["retenciones"] = extracted["retenciones"]
    if "contribuciones_pension" in extracted:
        delta["contribuciones_pension"] = extracted["contribuciones_pension"]

    preview = ""
    try:
        preview = json.dumps(payload.ocr_json, ensure_ascii=False)
    except Exception:
        preview = ""
    if len(preview) > 50000:
        preview = preview[:50000]

    raw = json.loads(tax_return.raw_answers) if tax_return.raw_answers else {}
    raw = _upsert_nomina_and_totals(raw, month, {
        "month": month,
        "filename": f"{month:02d}_ocr.json",
        "uploaded_at": datetime.utcnow().isoformat(),
        "source": "ocr_json",
        "extracted": extracted,
        "delta": delta,
        "ocr_json_preview": preview,
    })
    tax_return.raw_answers = json.dumps(raw)
    await db.commit()

    return PayslipExtractResponse(
        month=month,
        filename=f"{month:02d}_ocr.json",
        extracted=extracted,
        suggested_raw_answers_delta=delta,
        totals=raw.get("nominas_totals"),
        source="ocr_json",
    )


@router.get("/tax-returns/{tax_return_id}/payslips/export.xlsx")
async def export_payslips_excel(
    tax_return_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tax_return = await _get_tax_return_owned(db, tax_return_id, current_user.id)
    raw = json.loads(tax_return.raw_answers) if tax_return.raw_answers else {}
    nominas = raw.get("nominas", [])
    if not isinstance(nominas, list):
        nominas = []

    from openpyxl import Workbook
    from io import BytesIO
    from fastapi.responses import StreamingResponse

    wb = Workbook()
    ws = wb.active
    ws.title = "Nominas"

    ws.append(["Mois", "Fichier", "Source", "Brut", "IRPF", "SS", "Net", "Upload (UTC)"])
    for n in sorted([x for x in nominas if isinstance(x, dict)], key=lambda x: int(x.get("month", 0))):
        m = int(n.get("month", 0))
        delta = n.get("delta") if isinstance(n.get("delta"), dict) else {}
        extracted = n.get("extracted") if isinstance(n.get("extracted"), dict) else {}
        brut = float(delta.get("ingresos_trabajo", extracted.get("ingresos_trabajo", 0)) or 0)
        irpf = float(delta.get("retenciones", extracted.get("retenciones", 0)) or 0)
        ss = float(delta.get("contribuciones_pension", extracted.get("contribuciones_pension", 0)) or 0)
        net = extracted.get("liquido") if isinstance(extracted.get("liquido"), (int, float)) else None
        ws.append([
            m,
            n.get("filename", ""),
            n.get("source", ""),
            brut,
            irpf,
            ss,
            net if net is not None else "",
            n.get("uploaded_at", ""),
        ])

    totals = raw.get("nominas_totals") if isinstance(raw.get("nominas_totals"), dict) else {}
    ws.append([])
    ws.append(["TOTAL", "", "", totals.get("ingresos_trabajo", ""), totals.get("retenciones", ""), totals.get("contribuciones_pension", ""), "", ""])

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)

    filename = f"nominas_{tax_return.year}_{tax_return_id}.xlsx"
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


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


@router.post("/content/analyze", response_model=ContentAnalyzeResponse)
async def analyze_content(
    payload: ContentAnalyzeRequest,
    current_user: User = Depends(get_current_active_user),
):
    linkedin = None
    article = None
    combined_text_parts: list[str] = []

    if payload.linkedin_url:
        linkedin = await fetch_and_extract(payload.linkedin_url)
        if linkedin.text:
            combined_text_parts.append(linkedin.text[:20000])

    if payload.article_url:
        article = await fetch_and_extract(payload.article_url)
        if article.text:
            combined_text_parts.append(article.text[:20000])

    if payload.article_text:
        combined_text_parts.append(payload.article_text[:40000])

    combined_text = "\n\n".join([p for p in combined_text_parts if p]).strip()
    analysis = analyze_text(combined_text)

    def to_response(x):
        if x is None:
            return None
        return ExtractedContentResponse(
            url=x.url,
            ok=bool(x.ok),
            status_code=x.status_code,
            error=x.error,
            title=x.title,
            description=x.description,
            og_title=x.og_title,
            og_description=x.og_description,
            text_preview=(x.text or "")[:1200],
        )

    return ContentAnalyzeResponse(
        linkedin=to_response(linkedin),
        article=to_response(article),
        analysis=analysis,
    )
