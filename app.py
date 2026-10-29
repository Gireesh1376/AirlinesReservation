import os
from datetime import date, datetime, timedelta

from flask import Flask
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import inspect, text

from extensions import db
from views import app_views


def ensure_schema():
    """Create tables and add any columns introduced after the first release.

    Keeps an existing airlines.db working without a manual migration.
    """
    db.create_all()
    inspector = inspect(db.engine)
    existing = {c["name"] for c in inspector.get_columns("booking")}
    new_columns = {
        "transaction_id": "VARCHAR(30)",
        "payment_method": "VARCHAR(20)",
        "payment_detail": "VARCHAR(60)",
        "promo_code": "VARCHAR(20)",
        "discount": "INTEGER DEFAULT 0",
        "created_at": "DATETIME",
    }
    with db.engine.begin() as conn:
        for name, ddl in new_columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE booking ADD COLUMN {name} {ddl}"))
        # One seat can only be sold once per flight (guards against double booking).
        try:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_flight_seat "
                    "ON booking (flight_id, seat_number)"
                )
            )
        except Exception:
            pass


def refresh_stale_flight_dates():
    """If every flight is already in the past (e.g. an old demo DB), shift all
    flight dates forward together so the earliest departs tomorrow. Bookings
    follow their flights, so nothing becomes inconsistent. Disable with
    AUTO_REFRESH_FLIGHT_DATES=0."""
    if os.environ.get("AUTO_REFRESH_FLIGHT_DATES", "1") == "0":
        return
    from models import Flight

    flights = Flight.query.all()
    parsed = []
    for f in flights:
        try:
            parsed.append((f, datetime.strptime(f.date, "%Y-%m-%d").date()))
        except (ValueError, TypeError):
            return
    if not parsed or any(d >= date.today() for _, d in parsed):
        return
    shift = (date.today() + timedelta(days=1)) - min(d for _, d in parsed)
    for f, d in parsed:
        f.date = (d + shift).isoformat()
    db.session.commit()
    print(
        f"[startup] All flights were in the past; shifted dates forward by {shift.days} days."
    )


def create_app():
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///airlines.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    db.init_app(app)
    CSRFProtect(app)
    app.register_blueprint(app_views)

    with app.app_context():
        ensure_schema()
        refresh_stale_flight_dates()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
