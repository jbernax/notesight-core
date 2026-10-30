import logging
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import User
from app.schemas import (
    BillingStatusResponse,
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    CustomerPortalRequest,
    CustomerPortalResponse,
    OptionalBillingDetailsUpdate,
    ScheduleDowngradeRequest,
    UserQuotaResponse,
)
from app.services.billing_service import (
    create_checkout_session,
    create_customer_portal_session,
    get_user_billing_status,
    process_stripe_webhook,
    schedule_subscription_downgrade,
    resume_subscription,
)
from app.api.users import build_user_quota_response

router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/create-checkout-session", response_model=CheckoutSessionResponse)
def handle_create_checkout_session(
    request_data: CheckoutSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CheckoutSessionResponse:
    """
    Initiate a secure Stripe Hosted Checkout session.
    No card numbers or CVVs touch the NoteSight application.
    """
    success_url = f"{settings.FRONTEND_URL}/dashboard?payment=success&tier={request_data.tier.value}"
    cancel_url = f"{settings.FRONTEND_URL}/dashboard?payment=cancelled"
    url = create_checkout_session(
        user=current_user,
        target_tier=request_data.tier,
        success_url=success_url,
        cancel_url=cancel_url,
        db=db,
        locale=request_data.locale,
    )
    return CheckoutSessionResponse(checkout_url=url)


@router.post("/create-portal-session", response_model=CustomerPortalResponse)
def handle_create_portal_session(
    request_data: CustomerPortalRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CustomerPortalResponse:
    """
    Initiate a secure Stripe Customer Billing Portal session.
    Allows users to update payment methods, download invoices, or cancel their subscription.
    """
    return_url = f"{settings.FRONTEND_URL}/dashboard"
    url = create_customer_portal_session(
        user=current_user,
        return_url=return_url,
        db=db,
        locale=request_data.locale if request_data else None,
    )
    return CustomerPortalResponse(portal_url=url)


@router.get("/status", response_model=BillingStatusResponse)
def handle_get_billing_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BillingStatusResponse:
    """Retrieve live billing status, active subscription details, and customer reference."""
    status_data = get_user_billing_status(current_user, db)
    return BillingStatusResponse(**status_data)


@router.patch("/details", response_model=BillingStatusResponse)
def handle_update_billing_details(
    details: OptionalBillingDetailsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BillingStatusResponse:
    """
    Update optional billing contact details (name, email, country).
    Completely optional for free/starter tier users.
    """
    from app.models import BillingCustomer
    customer = db.query(BillingCustomer).filter(BillingCustomer.user_id == current_user.id).first()
    if not customer:
        customer = BillingCustomer(
            user_id=current_user.id,
            stripe_customer_id=f"cus_free_{current_user.id.hex[:14]}",
            billing_email=details.billing_email or current_user.email,
            billing_name=details.billing_name or current_user.full_name,
            billing_country=details.billing_country,
        )
        db.add(customer)
    else:
        if details.billing_name is not None:
            customer.billing_name = details.billing_name
        if details.billing_email is not None:
            customer.billing_email = details.billing_email
        if details.billing_country is not None:
            customer.billing_country = details.billing_country
    db.commit()
    db.refresh(customer)
    status_data = get_user_billing_status(current_user, db)
    return BillingStatusResponse(**status_data)


@router.post("/downgrade", response_model=UserQuotaResponse)
def handle_schedule_downgrade(
    request_data: ScheduleDowngradeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserQuotaResponse:
    """
    Schedule a downgrade to take effect at the end of the current billing cycle.
    Guarantees user maintains paid quotas and features until the end of the paid month.
    """
    schedule_subscription_downgrade(current_user, request_data.tier, db)
    return build_user_quota_response(current_user, db)


@router.post("/resume", response_model=UserQuotaResponse)
def handle_resume_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserQuotaResponse:
    """
    Cancel a pending downgrade / cancellation and keep the user's current subscription active.
    """
    resume_subscription(current_user, db)
    return build_user_quota_response(current_user, db)


logger = logging.getLogger(__name__)


@router.post("/webhook")
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(None, alias="Stripe-Signature"),
    db: Session = Depends(get_db),
) -> dict:
    """
    Receive and process asynchronous Stripe events with HMAC-SHA256 signature verification
    and idempotency deduplication.
    """
    payload = await request.body()
    try:
        result = await run_in_threadpool(process_stripe_webhook, payload, stripe_signature, db)
    except IntegrityError as exc:
        db.rollback()
        logger.info("Handled concurrent duplicate Stripe webhook event cleanly: %s", exc)
        return {"status": "already_processed", "message": "Concurrent duplicate webhook event ignored"}
    return result
