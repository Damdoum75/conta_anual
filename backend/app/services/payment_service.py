import stripe
from typing import Optional
from app.core.config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY


def create_checkout_session(
    tax_return_id: int,
    amount: float = 1000,
    currency: str = "eur",
    success_url: str = None,
    cancel_url: str = None
) -> stripe.checkout.Session:
    if success_url is None:
        success_url = f"{settings.FRONTEND_URL}/payment/success?tax_return_id={tax_return_id}"
    if cancel_url is None:
        cancel_url = f"{settings.FRONTEND_URL}/payment/cancel?tax_return_id={tax_return_id}"
    
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": currency,
                "product_data": {
                    "name": f"Declaración IRPF - Renta {tax_return_id}",
                    "description": "Generación del Modelo 100 IRPF",
                },
                "unit_amount": amount,
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "tax_return_id": str(tax_return_id),
        },
    )
    
    return session


def verify_payment(payment_intent_id: str) -> Optional[stripe.PaymentIntent]:
    try:
        return stripe.PaymentIntent.retrieve(payment_intent_id)
    except stripe.error.StripeError:
        return None


def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    return stripe.Webhook.construct_event(
        payload,
        sig_header,
        settings.STRIPE_WEBHOOK_SECRET
    )


def create_monthly_access_checkout_session(
    user_id: int,
    nie: str,
    amount_cents: Optional[int] = None,
    currency: str = "eur",
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
) -> stripe.checkout.Session:
    if amount_cents is None:
        amount_cents = settings.MONTHLY_ACCESS_PRICE_CENTS

    if success_url is None:
        success_url = f"{settings.FRONTEND_URL}/?payment=success"
    if cancel_url is None:
        cancel_url = f"{settings.FRONTEND_URL}/?payment=cancel"

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": currency,
                "product_data": {
                    "name": "Accès Déclaration Annuelle (1 mois)",
                    "description": "Accès pour 1 mois, valable pour 1 seul NIE/DNI",
                },
                "unit_amount": int(amount_cents),
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "kind": "monthly_access",
            "user_id": str(user_id),
            "nie": str(nie),
        },
    )

    return session
