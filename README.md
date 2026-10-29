# Airlines Reservation

Flask + SQLite flight booking app.

## Run
    pip install -r requirements.txt
    python app.py            # or: gunicorn app:app

Tables/columns are created or upgraded automatically on start (existing `airlines.db` keeps working).
If every flight in the DB is in the past, dates are shifted forward once (disable: `AUTO_REFRESH_FLIGHT_DATES=0`).

## Booking flow
Seat -> Review -> Payment (Card / UPI / Net Banking, promo code) -> OTP -> Confirmation + boarding pass PDF.

* Prices are always computed on the server (fare x class multiplier, promo, 5% GST).
* Simulated gateway: test card `4242 4242 4242 4242`; `4000 0000 0000 0002` is always declined.
  The OTP is shown on screen in demo mode (no SMS provider). Full card number/CVV are never stored.
* Promo codes: `WELCOME10`, `FLY500`.
* Refund on cancel: 100% (48h+ before departure), 75% (24-48h), 50% (<24h), none after departure.

## Config (env vars, all optional)
`SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` (defaults admin@airline.com / admin123), `DATABASE_URL`.
