"""Stripe payment service — checkout sessions and webhook verification."""
import os
import stripe as _stripe


def _s():
    _stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    return _stripe


def create_subscription_checkout(
    plan: str,
    billing_period: str,
    amount_usd: float,
    merchant_ref: str,
    user_email: str,
    success_url: str,
    cancel_url: str,
    discount_pct: int = 0,
):
    """Create a Stripe Checkout Session for a subscription period (one-time payment)."""
    s = _s()

    period_labels = {
        "monthly":  "1 Month",
        "halfyear": "6 Months",
        "yearly":   "12 Months",
    }
    plan_labels = {
        "basic":     "Basic",
        "standard":  "Standard",
        "unlimited": "Unlimited",
    }
    period_label = period_labels.get(billing_period, billing_period.title())
    plan_label   = plan_labels.get(plan, plan.title())

    final_amount = round(amount_usd * (1 - discount_pct / 100), 2) if discount_pct else amount_usd
    desc = f"Smart Study Guides {plan_label} — {period_label}"
    if discount_pct:
        desc += f" ({discount_pct}% discount applied)"

    session = s.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "unit_amount": int(round(final_amount * 100)),
                "product_data": {
                    "name": desc,
                    "description": (
                        f"Access to {plan_label} plan features for {period_label}. "
                        f"Includes humanizer & AI checker tools."
                    ),
                },
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=cancel_url,
        customer_email=user_email or None,
        client_reference_id=merchant_ref,
        metadata={
            "merchant_ref":   merchant_ref,
            "plan":           plan,
            "billing_period": billing_period,
            "amount_usd":     str(final_amount),
            "discount_pct":   str(discount_pct),
            "type":           "subscription",
        },
        billing_address_collection="auto",
    )
    return session


def create_checkout_session(
    amount_usd: float,
    credits: int,
    merchant_ref: str,
    user_email: str,
    success_url: str,
    cancel_url: str,
):
    """Create a Stripe Checkout Session and return the session object."""
    s = _s()
    session = s.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "unit_amount": int(round(amount_usd * 100)),
                "product_data": {
                    "name": f"{credits:,} Smart Study Guides Credits",
                    "description": (
                        f"Top-up your account with {credits:,} credits "
                        f"(${amount_usd:.2f} USD)"
                    ),
                },
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=cancel_url,
        customer_email=user_email or None,
        client_reference_id=merchant_ref,
        metadata={
            "merchant_ref": merchant_ref,
            "credits": str(credits),
            "amount_usd": str(amount_usd),
        },
        billing_address_collection="auto",
    )
    return session


def retrieve_session(session_id: str):
    """Fetch a Checkout Session by ID (used on the success page)."""
    return _s().checkout.Session.retrieve(session_id)


def construct_webhook_event(payload: bytes, sig_header: str, secret: str):
    """Verify Stripe webhook signature and return the event dict."""
    return _s().Webhook.construct_event(payload, sig_header, secret)
