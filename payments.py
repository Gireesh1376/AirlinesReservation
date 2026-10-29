"""Payment helpers: pricing, promo codes, card/UPI/net-banking validation, refunds.

This is a *simulated* payment gateway for a college/demo project. No real money
moves and the full card number / CVV are never stored -- only the brand and last
four digits are kept on the booking.
"""
import hashlib
import hmac
import re
import secrets
from datetime import datetime

GST_RATE = 0.05

SEAT_MULTIPLIER = {"Economy": 1, "Business": 1.5, "First Class": 2.5}

PROMOS = {
    "WELCOME10": {"type": "percent", "value": 10, "cap": 1500, "min_fare": 2000,
                  "desc": "10% off (up to ₹1,500) on fares of ₹2,000 or more"},
    "FLY500": {"type": "flat", "value": 500, "cap": 500, "min_fare": 5000,
               "desc": "Flat ₹500 off on fares of ₹5,000 or more"},
}

NET_BANKS = ["State Bank of India", "HDFC Bank", "ICICI Bank", "Axis Bank",
             "Kotak Mahindra Bank", "Punjab National Bank", "Bank of Baroda", "Canara Bank"]

OTP_TTL_SECONDS = 300
OTP_MAX_ATTEMPTS = 3
OTP_MAX_RESENDS = 3

# Test card that is always declined, so the failure path can be demonstrated.
DECLINED_TEST_CARD = "4000000000000002"


# ---------------------------------------------------------------- pricing
def fare_for(flight, seat_class):
    return int(flight.price * SEAT_MULTIPLIER.get(seat_class, 1))


def evaluate_promo(code, fare):
    """Return (discount, message, valid) for a promo code against a base fare."""
    code = (code or "").strip().upper()
    if not code:
        return 0, "", True
    promo = PROMOS.get(code)
    if not promo:
        return 0, "Invalid promo code.", False
    if fare < promo["min_fare"]:
        return 0, f"{code} needs a fare of at least ₹{promo['min_fare']:,}.", False
    if promo["type"] == "percent":
        discount = min(int(fare * promo["value"] / 100), promo["cap"])
    else:
        discount = min(promo["value"], promo["cap"])
    return discount, f"{code} applied: {promo['desc']}.", True


def quote(flight, seat_class, promo_code=""):
    """Full price breakdown, always computed server-side."""
    fare = fare_for(flight, seat_class)
    discount, message, valid = evaluate_promo(promo_code, fare)
    taxable = fare - discount
    tax = round(taxable * GST_RATE)
    return {
        "fare": fare,
        "discount": discount,
        "tax": tax,
        "total": taxable + tax,
        "promo": (promo_code or "").strip().upper() if valid and discount else "",
        "promo_message": message,
        "promo_valid": valid,
    }


# ---------------------------------------------------------------- validation
def luhn_ok(number):
    total, alt = 0, False
    for ch in reversed(number):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def card_brand(number):
    if re.match(r"^4", number):
        return "Visa"
    if re.match(r"^(5[1-5]|2(2[2-9][1-9]|2[3-9]\d|[3-6]\d\d|7[01]\d|720))", number):
        return "Mastercard"
    if re.match(r"^3[47]", number):
        return "Amex"
    if re.match(r"^(60|65|81|82|508)", number):
        return "RuPay"
    return "Card"


def validate_payment(form, now=None):
    """Validate the payment form. Returns (errors: dict, method, detail, declined)."""
    now = now or datetime.now()
    errors = {}
    method = form.get("method", "")
    detail = ""
    declined = False

    if method == "Card":
        number = re.sub(r"[\s-]", "", form.get("card_no", ""))
        brand = "Card"
        if not number.isdigit() or not 13 <= len(number) <= 19 or not luhn_ok(number):
            errors["card_no"] = "Enter a valid card number."
        else:
            brand = card_brand(number)
            detail = f"{brand} •••• {number[-4:]}"
            declined = number == DECLINED_TEST_CARD

        name = form.get("card_name", "").strip()
        if len(name) < 2 or not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", name):
            errors["card_name"] = "Enter the name as printed on the card."

        m = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{2}|\d{4})\s*", form.get("expiry", ""))
        if not m:
            errors["expiry"] = "Use MM/YY."
        else:
            month, year = int(m.group(1)), int(m.group(2))
            if year < 100:
                year += 2000
            if not 1 <= month <= 12:
                errors["expiry"] = "Invalid month."
            elif (year, month) < (now.year, now.month):
                errors["expiry"] = "This card has expired."

        cvv_len = 4 if brand == "Amex" else 3
        if not re.fullmatch(rf"\d{{{cvv_len}}}", form.get("cvv", "")):
            errors["cvv"] = f"Enter the {cvv_len}-digit CVV."

    elif method == "UPI":
        upi = form.get("upi_id", "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{2,256}@[A-Za-z]{2,64}", upi):
            errors["upi_id"] = "Enter a valid UPI ID, e.g. name@upi."
        else:
            detail = upi

    elif method == "Net Banking":
        bank = form.get("bank", "")
        if bank not in NET_BANKS:
            errors["bank"] = "Select your bank."
        else:
            detail = bank
    else:
        errors["method"] = "Choose a payment method."

    return errors, method, detail, declined


# ---------------------------------------------------------------- ids / OTP
def new_transaction_id():
    return "TXN" + datetime.now().strftime("%y%m%d") + secrets.token_hex(4).upper()


def new_otp():
    return f"{secrets.randbelow(900000) + 100000}"


def otp_digest(secret_key, txn_id, otp):
    return hmac.new(secret_key.encode(), f"{txn_id}:{otp}".encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- refunds
def parse_departure(flight):
    """Departure as a datetime. Tolerates 'HH:MM' and 'hh:MM AM'; falls back to end of day."""
    try:
        day = datetime.strptime(flight.date.strip(), "%Y-%m-%d")
    except (ValueError, AttributeError):
        return None
    t = (flight.departure_time or "").strip()
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(t, fmt)
            return day.replace(hour=parsed.hour, minute=parsed.minute)
        except ValueError:
            continue
    return day.replace(hour=23, minute=59)


def has_departed(flight, now=None):
    dep = parse_departure(flight)
    return bool(dep and dep <= (now or datetime.now()))


def refund_policy(booking, flight, now=None):
    """(allowed, percent, amount) for a customer cancellation."""
    now = now or datetime.now()
    dep = parse_departure(flight)
    if dep is None:
        return True, 100, booking.final_price
    hours = (dep - now).total_seconds() / 3600
    if hours <= 0:
        return False, 0, 0
    pct = 100 if hours >= 48 else 75 if hours >= 24 else 50
    return True, pct, round(booking.final_price * pct / 100)
