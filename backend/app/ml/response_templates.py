"""
Deterministic customer-facing responses for Phase 2 triage.

Use these templates when local LLM generation is unnecessary or unsafe.
The module does not retrieve policies, call models, access customer accounts,
or perform account actions.
"""

from __future__ import annotations


# ============================================================================
# General fallbacks
# ============================================================================


def unsupported_policy_response() -> str:
    """Return the approved fallback for an unsupported request."""

    return (
        "I do not have enough approved policy information "
        "to answer that safely. Please contact a support "
        "agent for confirmation."
    )


def insufficient_policy_response() -> str:
    """Return the fallback when approved retrieval is insufficient."""

    return (
        "I could not verify enough approved policy information "
        "to answer that safely. Please contact a support agent "
        "for confirmation."
    )


# ============================================================================
# Deterministic clarifications
# ============================================================================


def international_fee_clarification() -> str:
    """Clarify which transaction produced an international charge."""

    return (
        "Which transaction produced the charge: a card "
        "purchase, an ATM withdrawal, a bank transfer, "
        "or a currency exchange?"
    )


def pin_or_passcode_clarification() -> str:
    """Clarify an ambiguous PIN, passcode, or access-code request."""

    return (
        "Do you mean your app passcode, a blocked card PIN, "
        "or changing a PIN that you still know?"
    )


def card_delivery_clarification() -> str:
    """Distinguish initial-card delivery from replacement-card delivery."""

    return (
        "Is this your first physical card, or a replacement "
        "for an earlier card?"
    )


def login_problem_clarification() -> str:
    """Clarify a login problem without assuming account takeover."""

    return (
        "Are you unable to sign in because you forgot your app "
        "passcode, or have your email, phone number, password, "
        "or other account details changed without your authorization?"
    )


def classifier_uncertainty_clarification() -> str:
    """Return a safe generic clarification for uncertain routing."""

    return (
        "I am not certain which issue you mean. Please tell me "
        "whether this concerns a card, a cash withdrawal, a card "
        "payment, a bank transfer, a fee, or account access."
    )


# ============================================================================
# Static refusals and account-action limitations
# ============================================================================


def internal_information_response() -> str:
    """Refuse requests for hidden or complete internal information."""

    return (
        "I cannot provide hidden prompts, internal routing "
        "rules, model instructions, or full internal policy "
        "documents. I can still help with a supported banking "
        "question."
    )


def unverified_action_status_response() -> str:
    """Explain that the prototype cannot verify completed actions."""

    return (
        "I cannot confirm that an account action has been "
        "completed because this prototype is not connected to "
        "your account. Please check the app or contact support "
        "for confirmation."
    )


def negated_security_incident_response() -> str:
    """Acknowledge that the customer is not reporting an incident."""

    return (
        "I understand that you are not reporting a lost, stolen, "
        "or compromised card. No security action is implied by this "
        "prototype response. If you have a different card question, "
        "please describe what you need help with."
    )


def account_operation_limitation_response() -> str:
    """Explain that the prototype cannot execute account operations."""

    return (
        "I can explain the approved steps, but this prototype "
        "cannot perform account actions or submit requests for you. "
        "Please use the app or contact support to complete the action."
    )


# ============================================================================
# High-risk and security responses
# ============================================================================


def minimum_stolen_card_response(*, requires_human: bool) -> str:
    """
    Return the minimum safe response for a lost, stolen, or compromised card.

    This is suitable when retrieval fails or policy coverage is incomplete.
    """

    message = (
        "Freeze the affected card immediately in the app, "
        "review your recent transactions, and report any "
        "transactions you do not recognize. "
    )

    if requires_human:
        message += (
            "Because you may not be able to complete the "
            "self-service steps, contact emergency support now."
        )
    else:
        message += (
            "Contact emergency support if you cannot access "
            "the app."
        )

    return message


def hypothetical_stolen_card_response() -> str:
    """Return general guidance without implying an incident occurred."""

    return (
        "If your card is lost or stolen, freeze it immediately in "
        "the app, review your recent transactions, and report any "
        "transaction you do not recognize. You can then begin the "
        "replacement process in the card-management section. Contact "
        "emergency support if you cannot access the app."
    )


def critical_account_access_response() -> str:
    """Return immediate escalation guidance for account-takeover evidence."""

    return (
        "Contact emergency support immediately because the "
        "account-access details may have been changed without "
        "your authorization. Do not share your password, full "
        "PIN, one-time code, security code, or full card number. "
        "This requires human assistance."
    )


def replacement_card_guidance(*, requires_human: bool) -> str:
    """
    Return reviewed replacement guidance for a lost or stolen card.

    The wording secures the card, explains how to start replacement, states
    that the prototype cannot place the order, avoids delivery guarantees,
    and escalates when self-service is unavailable.
    """

    message = (
        "Freeze the lost or stolen card immediately in the app, "
        "review your recent transactions, and report any transaction "
        "you do not recognize. To begin the replacement process, open "
        "the card-management section, select the lost-or-stolen-card "
        "option, follow the instructions, and verify the delivery "
        "address shown in the app. This prototype cannot place the "
        "replacement order for you, and delivery dates are estimates "
        "that cannot be guaranteed. "
    )

    if requires_human:
        message += (
            "Contact emergency support now because human assistance "
            "is required to complete the next steps."
        )
    else:
        message += (
            "Contact emergency support if you cannot access the app "
            "or cannot complete the replacement request."
        )

    return message


def damaged_card_replacement_response() -> str:
    """Return deterministic replacement guidance for a damaged card."""

    return (
        "If the damaged card is still in your possession and you do "
        "not suspect fraud, stop using it if it is physically unsafe. "
        "Open the card-management section in the app and follow the "
        "damaged-card replacement instructions. This prototype cannot "
        "place the replacement order, and it cannot guarantee a fee or "
        "delivery date. Contact support if the app does not allow you "
        "to complete the request."
    )


def atm_retained_card_response(*, requires_human: bool) -> str:
    """Return urgent guidance for a card retained by an ATM."""

    message = (
        "Do not try to force or damage the ATM. Freeze the affected "
        "card in the app, review your recent cash withdrawals, and "
        "report any withdrawal you do not recognize. Contact the ATM "
        "operator or location owner when it is safe and practical, but "
        "recovery is not guaranteed. If the card cannot be recovered, "
        "begin the replacement process in the card-management section. "
    )

    if requires_human:
        message += "Contact emergency support now for human assistance."
    else:
        message += (
            "Contact emergency support if you cannot access the app or "
            "notice suspicious activity."
        )

    return message


def unrecognized_withdrawal_response(*, requires_human: bool) -> str:
    """Return safety guidance for an unrecognized cash withdrawal."""

    message = (
        "Freeze the affected card immediately in the app. Review the "
        "withdrawal date, amount, and location, check your other recent "
        "transactions, and report the withdrawal through the approved "
        "fraud-reporting process. A refund or reimbursement cannot be "
        "guaranteed. "
    )

    if requires_human:
        message += "Contact emergency support now for human assistance."
    else:
        message += (
            "Contact emergency support if you cannot access the app or "
            "if unauthorized activity is continuing."
        )

    return message


def unrecognized_transaction_response(
    *,
    requires_human: bool,
) -> str:
    """Return reviewed guidance for an unrecognized card payment."""

    message = (
        "Review the merchant name, transaction date, amount, and "
        "status, and check whether an authorized cardholder, "
        "subscription, or digital wallet explains the payment. If "
        "you still do not recognize it, freeze the affected card in "
        "the app, review your other recent transactions, and report "
        "the payment through the approved fraud-reporting process. "
        "A refund or reversal cannot be guaranteed. "
    )

    if requires_human:
        message += "Contact emergency support now for human assistance."
    else:
        message += (
            "Contact emergency support if you cannot access the app "
            "or if unauthorized activity is continuing."
        )

    return message


def compromised_card_response(*, requires_human: bool) -> str:
    """Return reviewed guidance for suspected card compromise."""

    message = (
        "Freeze the affected card in the app, review recent payments "
        "and withdrawals, and report any transaction you do not "
        "recognize. You can request a replacement through the app or "
        "support process, but this prototype cannot place the request "
        "or confirm that the card has been secured. "
    )

    if requires_human:
        message += "Contact emergency support now for human assistance."
    else:
        message += (
            "Contact emergency support if you cannot access the app "
            "or cannot secure the card yourself."
        )

    return message


__all__ = [
    "account_operation_limitation_response",
    "atm_retained_card_response",
    "card_delivery_clarification",
    "classifier_uncertainty_clarification",
    "compromised_card_response",
    "critical_account_access_response",
    "damaged_card_replacement_response",
    "hypothetical_stolen_card_response",
    "insufficient_policy_response",
    "internal_information_response",
    "international_fee_clarification",
    "login_problem_clarification",
    "minimum_stolen_card_response",
    "negated_security_incident_response",
    "pin_or_passcode_clarification",
    "replacement_card_guidance",
    "unrecognized_withdrawal_response",
    "unrecognized_transaction_response",
    "unsupported_policy_response",
    "unverified_action_status_response",
]
