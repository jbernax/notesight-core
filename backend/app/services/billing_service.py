import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any
import stripe
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.config import settings
from app.models import (
    BillingCustomer,
    ProcessedWebhookEvent,
    Subscription,
    SubscriptionStatus,
    User,
    UserTier,
)

logger = logging.getLogger(__name__)

TIER_RANKS = {
    UserTier.STARTER: 0,
    UserTier.PRO: 1,
    UserTier.VIRTUOSO: 2,
    UserTier.MAESTRO: 2,
}

# Configure Stripe API key
if settings.STRIPE_SECRET_KEY:
    stripe.api_key = settings.STRIPE_SECRET_KEY


def is_stripe_configured() -> bool:
    """Returns True if a live/test Stripe secret key is configured."""
    return bool(settings.STRIPE_SECRET_KEY and not settings.STRIPE_SECRET_KEY.startswith("mock_"))


def get_or_create_billing_customer(user: User, db: Session) -> BillingCustomer:
    """
    Retrieve existing BillingCustomer or create one in both Stripe and PostgreSQL.
    Guarantees that sensitive payment data is never stored locally.
    Self-heals if a customer ID from mock mode or a previous Stripe account is detected.
    """
    customer = db.query(BillingCustomer).filter(BillingCustomer.user_id == user.id).first()

    if is_stripe_configured():
        if customer:
            # If the customer was created in mock mode, re-provision in live Stripe
            if customer.stripe_customer_id.startswith("cus_mock_"):
                try:
                    stripe_customer = stripe.Customer.create(
                        email=user.email,
                        metadata={"user_id": str(user.id)},
                    )
                    customer.stripe_customer_id = stripe_customer.id
                    db.commit()
                    db.refresh(customer)
                    return customer
                except Exception as e:
                    logger.error("Failed to migrate mock Stripe customer for user %s: %s", user.id, e)
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Payment gateway communication error",
                    )

            # Verify the customer actually exists in the active Stripe account
            try:
                stripe.Customer.retrieve(customer.stripe_customer_id)
                return customer
            except stripe.error.InvalidRequestError as e:
                logger.warning(
                    "Stripe customer %s not found in active Stripe account (%s). Re-provisioning.",
                    customer.stripe_customer_id,
                    e,
                )
                try:
                    stripe_customer = stripe.Customer.create(
                        email=user.email,
                        metadata={"user_id": str(user.id)},
                    )
                    customer.stripe_customer_id = stripe_customer.id
                    db.commit()
                    db.refresh(customer)
                    return customer
                except Exception as create_exc:
                    logger.error("Failed to re-provision live customer for user %s: %s", user.id, create_exc)
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Payment gateway communication error",
                    )
        else:
            try:
                stripe_customer = stripe.Customer.create(
                    email=user.email,
                    metadata={"user_id": str(user.id)},
                )
                stripe_customer_id = stripe_customer.id
            except Exception as e:
                logger.error("Failed to create Stripe customer for user %s: %s", user.id, e)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Payment gateway communication error",
                )
            customer = BillingCustomer(
                user_id=user.id,
                stripe_customer_id=stripe_customer_id,
                billing_email=user.email,
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)
            return customer
    else:
        # Mock mode for development and local testing
        if customer:
            return customer
        stripe_customer_id = f"cus_mock_{user.id.hex[:14]}"
        customer = BillingCustomer(
            user_id=user.id,
            stripe_customer_id=stripe_customer_id,
            billing_email=user.email,
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)
        return customer


STRIPE_SUPPORTED_LOCALES = {
    "auto", "bg", "cs", "da", "de", "el", "en", "en-GB", "es", "es-419",
    "et", "fi", "fil", "fr", "fr-CA", "hr", "hu", "id", "it", "ja", "ko",
    "lt", "lv", "ms", "mt", "nb", "nl", "pl", "pt", "pt-BR", "ro", "ru",
    "sk", "sl", "sv", "th", "tr", "vi", "zh", "zh-HK", "zh-TW"
}


def _resolve_stripe_locale(locale: str | None) -> str:
    """Normalize and validate locale code for Stripe, defaulting to 'auto'."""
    if not locale:
        return "auto"
    cleaned = locale.strip().replace("_", "-")
    if cleaned in STRIPE_SUPPORTED_LOCALES:
        return cleaned
    base = cleaned.split("-")[0].lower()
    if base in STRIPE_SUPPORTED_LOCALES:
        return base
    return "auto"


def create_checkout_session(
    user: User,
    target_tier: UserTier,
    success_url: str,
    cancel_url: str,
    db: Session,
    locale: str | None = None,
) -> str:
    """
    Create a Stripe Hosted Checkout Session for subscription upgrade.
    Enforces PCI-DSS Level 1 compliance: raw card details never touch NoteSight servers.
    """
    if target_tier == UserTier.STARTER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Starter tier is free and does not require checkout",
        )

    price_id = (
        settings.STRIPE_PRO_PRICE_ID
        if target_tier == UserTier.PRO
        else settings.STRIPE_VIRTUOSO_PRICE_ID
    )

    customer = get_or_create_billing_customer(user, db)

    if not is_stripe_configured():
        # In mock development mode, provide a local mock callback URL
        logger.info(
            "Stripe not configured; simulating checkout session for user %s -> tier %s",
            user.id,
            target_tier.value,
        )
        return f"{settings.FRONTEND_URL}/dashboard?mock_payment=success&tier={target_tier.value}"

    try:
        stripe_locale = _resolve_stripe_locale(locale)
        session = stripe.checkout.Session.create(
            customer=customer.stripe_customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            allow_promotion_codes=True,
            billing_address_collection="auto",
            tax_id_collection={"enabled": True},
            customer_update={"name": "auto", "address": "auto"},
            locale=stripe_locale,
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=str(user.id),
            metadata={"user_id": str(user.id), "target_tier": target_tier.value},
            subscription_data={
                "metadata": {"user_id": str(user.id), "target_tier": target_tier.value}
            },
        )
        return session.url or success_url
    except Exception as e:
        logger.error("Error creating Stripe checkout session: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not initiate checkout session with payment provider",
        )


def create_customer_portal_session(
    user: User,
    return_url: str,
    db: Session,
    locale: str | None = None,
) -> str:
    """
    Generate a Stripe Customer Billing Portal session.
    Allows customers to manage payment methods, download invoices, or cancel their subscription.
    """
    customer = get_or_create_billing_customer(user, db)

    if not is_stripe_configured():
        return f"{settings.FRONTEND_URL}/dashboard?mock_portal=active"

    try:
        stripe_locale = _resolve_stripe_locale(locale)
        portal_session = stripe.billing_portal.Session.create(
            customer=customer.stripe_customer_id,
            return_url=return_url,
            locale=stripe_locale,
        )
        return portal_session.url
    except Exception as e:
        logger.error("Error creating billing portal session: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not initiate billing portal session",
        )


def _ensure_utc(dt: datetime | None) -> datetime:
    """Normalize datetime to UTC-aware datetime to prevent offset-naive vs offset-aware comparisons."""
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def sync_and_expire_subscription(user: User, db: Session) -> Subscription | None:
    """
    Self-healing expiration check: If a subscription was scheduled to cancel or downgrade
    and the current_period_end timestamp has passed, finalize the downgrade transition.
    Ensures users don't keep unpaid tiers indefinitely if a webhook was dropped,
    while guaranteeing paid tier benefits are retained strictly until current_period_end.
    """
    customer = db.query(BillingCustomer).filter(BillingCustomer.user_id == user.id).first()
    if not customer:
        return None

    sub = (
        db.query(Subscription)
        .filter(Subscription.customer_id == customer.id)
        .order_by(Subscription.created_at.desc())
        .first()
    )
    if not sub:
        return None

    now = datetime.now(timezone.utc)
    if sub.cancel_at_period_end and _ensure_utc(sub.current_period_end) <= now:
        target_tier = sub.pending_tier or UserTier.STARTER
        logger.info(
            "Billing period expired for user %s (sub %s). Finalizing scheduled downgrade to %s",
            user.id,
            sub.id,
            target_tier.value,
        )
        user.tier = target_tier
        if target_tier == UserTier.STARTER:
            sub.status = SubscriptionStatus.CANCELED
        else:
            sub.tier = target_tier
            sub.status = SubscriptionStatus.ACTIVE
            sub.current_period_start = now
            sub.current_period_end = now + timedelta(days=30)
            sub.stripe_price_id = (
                settings.STRIPE_PRO_PRICE_ID if target_tier == UserTier.PRO else settings.STRIPE_VIRTUOSO_PRICE_ID
            )

        sub.cancel_at_period_end = False
        sub.pending_tier = None
        sub.downgrade_scheduled_at = None
        db.commit()
        db.refresh(user)
        db.refresh(sub)

        from app.services.audit_logger import log_security_event
        log_security_event(
            "billing.downgrade_finalized",
            user_id=str(user.id),
            status="SUCCESS",
            details={"subscription_id": str(sub.id), "final_tier": target_tier.value},
        )

    return sub


def schedule_subscription_downgrade(
    user: User,
    target_tier: UserTier,
    db: Session,
) -> dict[str, Any]:
    """
    Schedule a downgrade to take effect at current_period_end.
    Guarantees that paid benefits remain active until the end of the paid billing period.
    """
    target_tier_norm = UserTier.VIRTUOSO if target_tier == UserTier.MAESTRO else target_tier
    current_tier_norm = UserTier.VIRTUOSO if user.tier == UserTier.MAESTRO else user.tier

    if TIER_RANKS.get(target_tier_norm, 0) >= TIER_RANKS.get(current_tier_norm, 0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Target tier '{target_tier_norm.value}' is not a downgrade from '{current_tier_norm.value}'.",
        )

    if current_tier_norm == UserTier.STARTER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Starter tier is already the baseline plan and cannot be downgraded.",
        )

    customer = get_or_create_billing_customer(user, db)
    now = datetime.now(timezone.utc)

    sub = (
        db.query(Subscription)
        .filter(Subscription.customer_id == customer.id, Subscription.status == SubscriptionStatus.ACTIVE)
        .order_by(Subscription.created_at.desc())
        .first()
    )

    if not sub:
        # User is in a paid tier without an active Stripe subscription (e.g. dev/mock mode or manual grant).
        # Provision a subscription record with 30-day billing cycle to honor grace period until month end.
        period_end = now + timedelta(days=30)
        sub = Subscription(
            customer_id=customer.id,
            stripe_subscription_id=f"sub_mock_{user.id.hex[:14]}",
            stripe_price_id=(
                settings.STRIPE_VIRTUOSO_PRICE_ID
                if current_tier_norm == UserTier.VIRTUOSO
                else settings.STRIPE_PRO_PRICE_ID
            ),
            tier=current_tier_norm,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=now,
            current_period_end=period_end,
            cancel_at_period_end=True,
            pending_tier=target_tier_norm,
            downgrade_scheduled_at=now,
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
    else:
        # If Stripe is configured and live subscription exists, instruct Stripe to cancel at period end
        if is_stripe_configured() and not sub.stripe_subscription_id.startswith("sub_mock_"):
            try:
                stripe.Subscription.modify(
                    sub.stripe_subscription_id,
                    cancel_at_period_end=True,
                    metadata={
                        "pending_downgrade_tier": target_tier_norm.value,
                        "downgrade_scheduled_at": now.isoformat(),
                    },
                )
            except Exception as e:
                logger.error("Failed to schedule Stripe cancellation for sub %s: %s", sub.stripe_subscription_id, e)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Could not schedule cancellation with payment provider.",
                )

        sub.cancel_at_period_end = True
        sub.pending_tier = target_tier_norm
        sub.downgrade_scheduled_at = now
        # If current_period_end is in the past, renew to 30 days out so user gets their grace period
        if _ensure_utc(sub.current_period_end) <= now:
            sub.current_period_end = now + timedelta(days=30)
        db.commit()
        db.refresh(sub)

    from app.services.audit_logger import log_security_event
    log_security_event(
        "billing.downgrade_scheduled",
        user_id=str(user.id),
        status="SUCCESS",
        details={
            "current_tier": user.tier.value,
            "target_tier": target_tier_norm.value,
            "effective_date": sub.current_period_end.isoformat(),
        },
    )

    return {
        "status": "scheduled",
        "current_tier": user.tier.value,
        "pending_tier": target_tier_norm.value,
        "effective_date": _ensure_utc(sub.current_period_end).isoformat(),
        "cancel_at_period_end": True,
    }


def resume_subscription(user: User, db: Session) -> dict[str, Any]:
    """
    Cancel a pending downgrade / cancellation and keep the user's current subscription active.
    """
    customer = db.query(BillingCustomer).filter(BillingCustomer.user_id == user.id).first()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No billing customer found.",
        )

    sub = (
        db.query(Subscription)
        .filter(Subscription.customer_id == customer.id, Subscription.status == SubscriptionStatus.ACTIVE)
        .order_by(Subscription.created_at.desc())
        .first()
    )

    if not sub or not sub.cancel_at_period_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="There is no scheduled downgrade or cancellation to resume.",
        )

    if is_stripe_configured() and not sub.stripe_subscription_id.startswith("sub_mock_"):
        try:
            stripe.Subscription.modify(
                sub.stripe_subscription_id,
                cancel_at_period_end=False,
                metadata={"pending_downgrade_tier": ""},
            )
        except Exception as e:
            logger.error("Failed to resume Stripe subscription %s: %s", sub.stripe_subscription_id, e)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not resume subscription with payment provider.",
            )

    sub.cancel_at_period_end = False
    sub.pending_tier = None
    sub.downgrade_scheduled_at = None
    db.commit()
    db.refresh(sub)

    from app.services.audit_logger import log_security_event
    log_security_event(
        "billing.subscription_resumed",
        user_id=str(user.id),
        status="SUCCESS",
        details={"tier": user.tier.value, "subscription_id": str(sub.id)},
    )

    return {
        "status": "resumed",
        "tier": user.tier.value,
        "cancel_at_period_end": False,
    }


def get_user_billing_status(user: User, db: Session) -> dict[str, Any]:
    """Retrieve the current user's subscription, customer id, and billing details."""
    sub = sync_and_expire_subscription(user, db)
    customer = db.query(BillingCustomer).filter(BillingCustomer.user_id == user.id).first()
    if not customer:
        return {
            "tier": user.tier.value,
            "has_active_subscription": False,
            "subscription": None,
            "stripe_customer_id": None,
        }

    if not sub:
        sub = (
            db.query(Subscription)
            .filter(Subscription.customer_id == customer.id)
            .order_by(Subscription.created_at.desc())
            .first()
        )

    sub_data = None
    if sub:
        sub_data = {
            "id": str(sub.id),
            "tier": sub.tier.value,
            "status": sub.status.value,
            "current_period_start": _ensure_utc(sub.current_period_start).isoformat(),
            "current_period_end": _ensure_utc(sub.current_period_end).isoformat(),
            "cancel_at_period_end": sub.cancel_at_period_end,
            "pending_tier": sub.pending_tier.value if sub.pending_tier else None,
            "downgrade_scheduled_at": _ensure_utc(sub.downgrade_scheduled_at).isoformat() if sub.downgrade_scheduled_at else None,
        }

    return {
        "tier": user.tier.value,
        "has_active_subscription": sub is not None and sub.status == SubscriptionStatus.ACTIVE,
        "subscription": sub_data,
        "stripe_customer_id": customer.stripe_customer_id,
        "billing_name": customer.billing_name,
        "billing_email": customer.billing_email,
        "billing_country": customer.billing_country,
    }


def process_stripe_webhook(payload: bytes, sig_header: str | None, db: Session) -> dict[str, Any]:
    """
    Process incoming Stripe webhooks with cryptographic HMAC signature verification
    and idempotency deduplication to prevent double-processing or replay attacks.
    """
    event: dict[str, Any]
    if settings.STRIPE_WEBHOOK_SECRET:
        if not sig_header:
            logger.warning("Stripe webhook received without Stripe-Signature header")
            from app.services.audit_logger import log_security_event
            log_security_event("billing.webhook_rejected", status="FAILURE", details={"reason": "missing_signature"})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing Stripe-Signature header",
            )
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            logger.warning("Invalid webhook payload format")
            from app.services.audit_logger import log_security_event
            log_security_event("billing.webhook_rejected", status="FAILURE", details={"reason": "invalid_payload"})
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")
        except stripe.error.SignatureVerificationError:
            logger.warning("Stripe webhook HMAC signature verification failed")
            from app.services.audit_logger import log_security_event
            log_security_event("billing.webhook_rejected", status="FAILURE", details={"reason": "signature_verification_failed"})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid signature verification",
            )
    else:
        # If in production, NEVER allow unsigned webhook processing!
        if settings.ENVIRONMENT in ("production", "prod"):
            logger.error("Rejecting webhook in production: STRIPE_WEBHOOK_SECRET is not configured")
            from app.services.audit_logger import log_security_event
            log_security_event("billing.webhook_rejected", status="FAILURE", details={"reason": "webhook_secret_missing_in_production"})
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Stripe webhook signing secret is not configured in production",
            )
        # Fallback only for local development/testing where webhook secret is not configured
        try:
            event = json.loads(payload.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    if hasattr(event, "to_dict"):
        event = event.to_dict()

    event_id = event.get("id")
    event_type = event.get("type")

    if not event_id or not event_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing event metadata")

    # Idempotency check: Guarantee at-most-once processing
    existing_event = (
        db.query(ProcessedWebhookEvent)
        .filter(ProcessedWebhookEvent.event_id == event_id)
        .first()
    )
    if existing_event:
        logger.info("Webhook event %s already processed; skipping (idempotent)", event_id)
        return {"status": "duplicate", "event_id": event_id}

    # Record event in idempotency table
    processed_record = ProcessedWebhookEvent(
        event_id=event_id,
        event_type=event_type,
    )
    db.add(processed_record)

    event_data = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(event_data, db)
    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        _handle_subscription_updated(event_data, db)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(event_data, db)
    elif event_type == "invoice.payment_succeeded":
        _handle_invoice_succeeded(event_data, db)
    elif event_type == "invoice.payment_failed":
        _handle_invoice_failed(event_data, db)

    db.commit()
    return {"status": "processed", "event_id": event_id, "type": event_type}


def _handle_checkout_completed(session_obj: dict[str, Any], db: Session) -> None:
    """Handle successful checkout session and immediately activate tier."""
    customer_id = session_obj.get("customer")
    sub_id = session_obj.get("subscription")
    metadata = session_obj.get("metadata", {})
    target_tier_str = metadata.get("target_tier")

    if not customer_id:
        return

    billing_customer = (
        db.query(BillingCustomer)
        .filter(BillingCustomer.stripe_customer_id == customer_id)
        .first()
    )
    if not billing_customer:
        user_id_str = session_obj.get("client_reference_id") or metadata.get("user_id")
        if user_id_str:
            billing_customer = db.query(BillingCustomer).filter(BillingCustomer.user_id == user_id_str).first()

    if not billing_customer:
        logger.warning("Could not find BillingCustomer for Stripe customer %s", customer_id)
        return

    # Update User Tier
    user = billing_customer.user
    if target_tier_str:
        try:
            tier_enum = UserTier(target_tier_str)
            user.tier = tier_enum
        except ValueError:
            user.tier = UserTier.PRO
    else:
        user.tier = UserTier.PRO

    # If subscription ID is provided, create or update subscription record
    if sub_id:
        existing_sub = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id == sub_id)
            .first()
        )
        now = datetime.now(timezone.utc)
        target_price_id = (
            settings.STRIPE_VIRTUOSO_PRICE_ID
            if user.tier == UserTier.VIRTUOSO
            else settings.STRIPE_PRO_PRICE_ID
        )
        if not existing_sub:
            new_sub = Subscription(
                customer_id=billing_customer.id,
                stripe_subscription_id=sub_id,
                stripe_price_id=target_price_id,
                tier=user.tier,
                status=SubscriptionStatus.ACTIVE,
                current_period_start=now,
                current_period_end=now,  # Will be refreshed on subscription.updated webhook
                cancel_at_period_end=False,
            )
            db.add(new_sub)
        else:
            existing_sub.tier = user.tier
            existing_sub.stripe_price_id = target_price_id
            existing_sub.status = SubscriptionStatus.ACTIVE

    # Log security & billing audit event
    from app.services.audit_logger import log_security_event
    log_security_event(
        "billing.checkout_completed",
        user_id=str(user.id),
        status="SUCCESS",
        details={"tier": user.tier.value, "subscription_id": sub_id},
    )

    # Dispatch transactional confirmation email
    try:
        from app.services.email import build_subscription_confirmed_email, get_email_service
        from app.services.quota import get_tier_config
        tier_cfg = get_tier_config(user.tier)
        email_svc = get_email_service()
        html, text = build_subscription_confirmed_email(
            recipient_email=user.email,
            tier_name=tier_cfg.display_name,
            storage_mb=tier_cfg.storage_limit_mb,
            monthly_pages=tier_cfg.monthly_page_limit,
            dashboard_link=f"{settings.FRONTEND_URL}/dashboard",
        )
        email_svc.send_email(
            to_email=user.email,
            subject=f"Welcome to NoteSight {tier_cfg.display_name}! 🎼",
            html_body=html,
            text_body=text,
        )
    except Exception as exc:
        logger.warning("Could not send subscription confirmation email for user %s: %s", user.id, exc)


def _handle_subscription_updated(sub_obj: dict[str, Any], db: Session) -> None:
    """Sync subscription status, price, tier, and dates with Stripe."""
    sub_id = sub_obj.get("id")
    customer_id = sub_obj.get("customer")
    status_str = sub_obj.get("status", "active")
    cancel_at_period_end = sub_obj.get("cancel_at_period_end", False)

    period_start_ts = sub_obj.get("current_period_start")
    period_end_ts = sub_obj.get("current_period_end")

    period_start = (
        datetime.fromtimestamp(period_start_ts, tz=timezone.utc)
        if period_start_ts
        else datetime.now(timezone.utc)
    )
    period_end = (
        datetime.fromtimestamp(period_end_ts, tz=timezone.utc)
        if period_end_ts
        else datetime.now(timezone.utc)
    )

    billing_customer = (
        db.query(BillingCustomer)
        .filter(BillingCustomer.stripe_customer_id == customer_id)
        .first()
    )
    if not billing_customer:
        return

    subscription = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == sub_id)
        .first()
    )

    try:
        sub_status = SubscriptionStatus(status_str)
    except ValueError:
        sub_status = SubscriptionStatus.ACTIVE

    metadata = sub_obj.get("metadata", {})
    tier_str = metadata.get("target_tier")
    tier_enum = UserTier.PRO

    # Extract price ID from line items (supporting plan switches in Customer Portal)
    stripe_price_id: str | None = None
    items_data = sub_obj.get("items", {}).get("data", [])
    if items_data:
        price_obj = items_data[0].get("price", {})
        stripe_price_id = price_obj.get("id")
        price_meta = price_obj.get("metadata", {})
        if price_meta.get("tier"):
            try:
                tier_enum = UserTier(price_meta.get("tier"))
            except ValueError:
                pass

    if stripe_price_id:
        if stripe_price_id == settings.STRIPE_VIRTUOSO_PRICE_ID:
            tier_enum = UserTier.VIRTUOSO
        elif stripe_price_id == settings.STRIPE_PRO_PRICE_ID:
            tier_enum = UserTier.PRO

    if tier_str:
        try:
            tier_enum = UserTier(tier_str)
        except ValueError:
            pass

    if not subscription:
        subscription = Subscription(
            customer_id=billing_customer.id,
            stripe_subscription_id=sub_id,
            stripe_price_id=stripe_price_id,
            tier=tier_enum,
            status=sub_status,
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=cancel_at_period_end,
        )
        db.add(subscription)
    else:
        subscription.status = sub_status
        subscription.current_period_start = period_start
        subscription.current_period_end = period_end
        subscription.cancel_at_period_end = cancel_at_period_end
        subscription.tier = tier_enum
        if stripe_price_id:
            subscription.stripe_price_id = stripe_price_id

    # Sync User.tier
    user = billing_customer.user
    if sub_status == SubscriptionStatus.ACTIVE:
        user.tier = subscription.tier
    elif sub_status in (SubscriptionStatus.CANCELED, SubscriptionStatus.UNPAID):
        user.tier = UserTier.STARTER


def _handle_subscription_deleted(sub_obj: dict[str, Any], db: Session) -> None:
    """When a subscription is canceled/deleted, downgrade user back to Starter."""
    sub_id = sub_obj.get("id")
    subscription = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == sub_id)
        .first()
    )
    if subscription:
        subscription.status = SubscriptionStatus.CANCELED
        user = subscription.customer.user
        target_tier = subscription.pending_tier or UserTier.STARTER
        user.tier = target_tier
        subscription.cancel_at_period_end = False
        subscription.pending_tier = None
        subscription.downgrade_scheduled_at = None
        from app.services.audit_logger import log_security_event
        log_security_event(
            "billing.subscription_cancelled",
            user_id=str(user.id),
            status="SUCCESS",
            details={"subscription_id": sub_id, "downgraded_to": target_tier.value},
        )
        logger.info(
            "User %s subscription %s canceled; transitioned to %s tier",
            user.id,
            sub_id,
            target_tier.value,
        )


def _handle_invoice_succeeded(invoice_obj: dict[str, Any], db: Session) -> None:
    """Handle successful recurring or initial invoice payment."""
    sub_id = invoice_obj.get("subscription")
    if not sub_id:
        return

    subscription = (
        db.query(Subscription)
        .filter(Subscription.stripe_subscription_id == sub_id)
        .first()
    )
    if subscription:
        subscription.status = SubscriptionStatus.ACTIVE
        from app.services.audit_logger import log_security_event
        user_id = str(subscription.customer.user_id) if subscription.customer else None
        log_security_event(
            "billing.invoice_paid",
            user_id=user_id,
            status="SUCCESS",
            details={"subscription_id": sub_id, "amount_paid": invoice_obj.get("amount_paid")},
        )
        logger.info("Invoice paid successfully for subscription %s", sub_id)


def _handle_invoice_failed(invoice_obj: dict[str, Any], db: Session) -> None:
    """When a recurring invoice fails, mark subscription as past_due."""
    sub_id = invoice_obj.get("subscription")
    if sub_id:
        subscription = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id == sub_id)
            .first()
        )
        if subscription:
            subscription.status = SubscriptionStatus.PAST_DUE
            user = subscription.customer.user if subscription.customer else None
            user_id = str(user.id) if user else None
            from app.services.audit_logger import log_security_event
            log_security_event(
                "billing.payment_failed",
                user_id=user_id,
                status="FAILURE",
                details={"subscription_id": sub_id},
            )
            logger.warning(
                "Payment failed on invoice for subscription %s; status marked as past_due",
                sub_id,
            )
            if user and user.email:
                try:
                    from app.services.email import build_payment_failed_email, get_email_service
                    from app.services.quota import get_tier_config
                    tier_cfg = get_tier_config(subscription.tier)
                    email_svc = get_email_service()
                    portal_link = f"{settings.FRONTEND_URL}/dashboard?tab=settings"
                    html, text = build_payment_failed_email(
                        recipient_email=user.email,
                        tier_name=tier_cfg.display_name,
                        portal_link=portal_link,
                    )
                    email_svc.send_email(
                        to_email=user.email,
                        subject=f"Action Required: NoteSight {tier_cfg.display_name} Payment Failed ⚠️",
                        html_body=html,
                        text_body=text,
                    )
                except Exception as exc:
                    logger.warning("Could not dispatch payment failed email for user %s: %s", user.id, exc)
