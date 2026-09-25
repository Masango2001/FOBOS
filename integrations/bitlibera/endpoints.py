"""BitLibera REST endpoint paths (doc §15).

The only authority on routes: `client.py` builds URLs exclusively from these
constants so a contract change happens in exactly one place.
"""

from __future__ import annotations

#: On-ramp: request the Lumicash SMS OTP (phone + BIF amount).
ONRAMP_REQUEST_OTP = "/api/v1/onramp/request-otp"

#: On-ramp: validate the OTP & debit Lumicash (phone + amount + otp + order_id).
ONRAMP_EXECUTE = "/api/v1/onramp/execute"

#: Off-ramp: create a BOLT11 invoice for BIF → Lumicash settlement.
OFFRAMP_CREATE_INVOICE = "/api/v1/offramp/create-invoice"

#: Order status (on-ramp, off-ramp). {order_id} is the FOBOS order reference.
ORDER_STATUS = "/api/v1/orders/{order_id}"
