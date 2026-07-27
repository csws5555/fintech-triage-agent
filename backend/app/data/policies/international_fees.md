---
document_id: international_fees
title: International Fees Policy
version: "1.0"
effective_date: "2026-07-01"
review_date: "2026-10-01"
owner: Payments Operations
status: approved
product: payments
policy_type: fees
jurisdiction: fictional_prototype
---

# International Fees Policy

## Purpose

This fictional prototype policy defines approved guidance for international card purchases, foreign ATM fees, currency conversion, dynamic currency conversion, and international-transfer fees.

It does not provide live exchange rates, guarantee fee reversals, or authorize refunds.

## International Card Purchase

An international card purchase may involve:

- a transaction made outside the customer’s home country;
- a merchant processing the transaction in another country;
- a purchase made in a currency different from the account currency;
- currency conversion by the platform, card network, or merchant.

When a customer asks about an international card-purchase charge:

1. Ask for the type of transaction if it is not clear.
2. Ask whether the merchant charged in local currency or the customer’s home currency.
3. Explain that currency conversion or merchant-side charges may affect the final amount.
4. Direct the customer to the transaction details in the application.
5. Escalate when the customer believes the amount is incorrect or unauthorized.

Do not state that every international purchase has the same fee.

## Card-Payment Fees

A card-payment fee may come from:

- the merchant;
- a payment processor;
- currency conversion;
- dynamic currency conversion;
- a product-specific fee listed in the application.

When the source of the charge is unclear, do not assume it is a platform fee.

Ask the customer to identify:

- the merchant;
- the transaction currency;
- the account currency;
- the displayed fee description;
- whether the payment was made in local or home currency.

The assistant must not guarantee that the fee will be refunded.

## Foreign ATM Fee

A foreign ATM withdrawal may include separate charges from:

- the ATM operator;
- the customer’s financial product;
- currency conversion;
- dynamic currency conversion;
- the card network.

When a customer reports a foreign ATM fee:

1. Ask whether the fee appeared on the ATM screen before confirmation.
2. Ask whether the ATM offered conversion into the customer’s home currency.
3. Explain that an ATM operator fee may be separate from other charges.
4. Direct the customer to review the withdrawal details in the application.
5. Escalate when the fee appears inconsistent with the displayed information or the withdrawal is unrecognized.

Do not promise that an ATM operator fee can be reversed.

## ATM Operator Fee

An ATM operator may charge its own usage fee.

The operator should normally display this fee before the customer confirms the withdrawal.

The assistant may explain that:

- the fee may be controlled by the ATM operator;
- the platform may not set or receive that fee;
- fee visibility can vary by ATM;
- the customer may choose another ATM before confirming a future withdrawal.

The assistant must not claim that the platform can automatically refund an operator fee.

## Dynamic Currency Conversion

Dynamic currency conversion occurs when a merchant or ATM offers to convert a transaction into the customer’s home currency.

The offered conversion may use a rate and fee set by the merchant or ATM provider.

Approved guidance:

1. Explain that the customer may be offered a choice between local currency and home currency.
2. Explain that choosing home currency may allow the merchant or ATM provider to set the conversion terms.
3. Recommend reviewing the displayed rate and fee before confirmation.
4. Do not claim that one option is always cheaper.
5. Direct the customer to support when the displayed charge appears inconsistent with the confirmed amount.

## Currency Conversion

When a transaction requires conversion:

1. Direct the customer to the transaction details for the recorded exchange rate and fee.
2. Explain that the final rate may depend on when the transaction was authorized or completed.
3. Explain that a pending amount may differ from the final completed amount.
4. Do not provide an invented live or future exchange rate.
5. Do not guarantee the final converted amount before the transaction completes.

For questions about future rates, state that the exact future exchange rate cannot be known or guaranteed.

## International Transfer Fee

An international transfer may involve:

- a transfer fee;
- intermediary-bank charges;
- recipient-bank charges;
- currency-conversion costs;
- differences between the sent amount and received amount.

When a customer asks about an international-transfer fee:

1. Confirm that the transaction was a bank transfer rather than a card purchase, ATM withdrawal, or currency exchange.
2. Direct the customer to the transfer details and fee breakdown.
3. Explain that other institutions may apply separate charges.
4. Escalate when the charged amount differs from the confirmed transfer summary.
5. Do not guarantee the amount the recipient will receive unless a trusted system confirms it.

## Ambiguous International Charge

When a customer says only that they were charged an extra fee abroad, ask:

“Which transaction produced the charge: a card purchase, an ATM withdrawal, a bank transfer, or a currency exchange?”

Do not generate a detailed policy answer until the transaction type is known.

If the customer cannot identify the transaction type, direct them to review the transaction details or contact support.

## Duplicate International Charge

When a customer reports being charged twice abroad:

1. Ask whether both entries are completed or whether one remains pending.
2. Confirm whether the merchant, amount, date, and currency are the same.
3. Explain that a pending authorization may temporarily appear with a completed transaction.
4. If two completed charges remain, direct the customer to support for review.
5. If either charge is unrecognized, apply the Fraud and Unauthorized Activity Policy.
6. Do not guarantee that either charge will be reversed.

## Incorrect or Unexpected Exchange Rate

When a customer questions an exchange rate:

1. Direct them to the rate recorded in the completed transaction details.
2. Ask whether the merchant or ATM performed dynamic currency conversion.
3. Explain that authorization and completion may occur at different times.
4. Explain that the displayed pending amount may change when completed.
5. Escalate if the recorded rate or fee appears inconsistent with the confirmed transaction information.

Do not invent a rate or compare it with an unsupported external rate.

## Escalation Conditions

Escalate to human support when:

- the transaction type cannot be determined;
- the fee differs from the confirmed transaction summary;
- a duplicate completed charge remains;
- a transaction or withdrawal is unrecognized;
- the customer alleges misleading fee disclosure;
- the customer disputes dynamic currency conversion;
- the exchange rate appears inconsistent with the completed transaction details;
- the amount received through an international transfer differs unexpectedly;
- the available policy information is insufficient.

## Approved Wording

Approved wording includes:

- “The charge may depend on the transaction type.”
- “Check whether the ATM or merchant offered currency conversion.”
- “An ATM operator may charge a separate fee.”
- “The exact future exchange rate cannot be guaranteed.”
- “A fee reversal or refund cannot be guaranteed.”
- “Which transaction produced the charge?”

## Prohibited Claims

The assistant must not claim that:

- every international transaction has the same fee;
- a fee will definitely be reversed;
- a refund is guaranteed;
- a future exchange rate is known;
- the final conversion amount is guaranteed before completion;
- an ATM operator fee was charged by the platform without evidence;
- the recipient will receive an exact amount unless confirmed by a trusted system;
- a duplicate transaction has already been disputed;
- support has approved reimbursement.

## Prohibited Data Requests

The assistant must never request:

- a password;
- a complete PIN;
- an OTP or authentication code;
- a CVV or security code;
- a full card number;
- complete online-banking credentials.
