# reset_and_generate.py

import random
from datetime import datetime, timedelta
import string
import sys

from app import app
from extensions import db
from models import Flight, User

# ===============================================================
# CONFIG
# ===============================================================
NUM_FLIGHTS = 40
NUM_SOURCES_TO_PICK = 30

DOMESTIC_PRICE_RANGE = (3000, 15000)
INTERNATIONAL_PRICE_RANGE = (25000, 85000)
MIXED_PRICE_RANGE = (18000, 90000)

SEATS_DOMESTIC = (80, 180)
SEATS_INTERNATIONAL = (120, 340)

# ===============================================================
# CITY LISTS
# ===============================================================

domestic = [
    "Delhi", "Mumbai", "Chennai", "Bangalore", "Hyderabad",
    "Kolkata", "Pune", "Ahmedabad", "Goa", "Jaipur",
    "Lucknow", "Chandigarh", "Bhubaneswar", "Indore",
    "Mangalore", "Coimbatore", "Thiruvananthapuram", "Patna",
    "Varanasi", "Nagpur", "Amritsar", "Guwahati", "Raipur",
    "Mysore", "Surat"
]

international = [
    "New York", "London", "Dubai", "Singapore", "Toronto",
    "Sydney", "Tokyo", "Paris", "Frankfurt", "Bangkok",
    "Hong Kong", "Seoul", "Rome", "Barcelona",
    "Istanbul", "Zurich", "Doha", "Kuala Lumpur"
]

all_locations = domestic + international


# ===============================================================
# HELPER FUNCTIONS
# ===============================================================

def random_time():
    hour = random.randint(0, 22)
    minute = random.choice([0, 15, 30, 45])
    return f"{hour:02d}:{minute:02d}"


def unique_flight_no(existing):
    for _ in range(2000):
        num = random.randint(100, 9999)
        suffix = random.choice(string.ascii_uppercase) if random.random() < 0.3 else ""
        fn = f"AI{num}{suffix}"
        if fn not in existing:
            existing.add(fn)
            return fn
    raise RuntimeError("Unable to generate unique flight_no")


# ===============================================================
# MAIN RESET + GENERATE
# ===============================================================

with app.app_context():

    print("🔄 Dropping all existing tables...")
    db.drop_all()

    print("🧱 Recreating database tables...")
    db.create_all()

    print("👤 Creating default admin user...")
    admin = User(name="Admin", email="admin@airline.com")
    admin.set_password("admin123")
    db.session.add(admin)
    db.session.commit()

    print("👤 Creating sample user...")
    user = User(name="Demo User", email="demo@user.com")
    user.set_password("demo123")
    db.session.add(user)
    db.session.commit()

    print("\n✈ Generating Flights...\n")

    pick_pool = random.sample(all_locations, min(NUM_SOURCES_TO_PICK, len(all_locations)))
    existing_fnos = set()

    created = 0
    attempts = 0

    DATE_START = datetime.now().date()
    DATE_END = DATE_START + timedelta(days=120)

    while created < NUM_FLIGHTS and attempts < 500:
        attempts += 1

        source = random.choice(pick_pool)
        destination = random.choice(pick_pool)
        if source == destination:
            continue

        days_range = (DATE_END - DATE_START).days
        rand_day = random.randint(0, days_range)
        date = (DATE_START + timedelta(days=rand_day)).isoformat()

        departure = random_time()

        domestic_route = source in domestic and destination in domestic
        international_route = source in international and destination in international

        if domestic_route:
            duration = random.randint(1, 3)
            seats = random.randint(80,125)
            price = random.randint(*DOMESTIC_PRICE_RANGE)
        elif international_route:
            duration = random.randint(100,140)
            seats = random.randint(*SEATS_INTERNATIONAL)
            price = random.randint(*INTERNATIONAL_PRICE_RANGE)
        else:
            duration = random.randint(3, 10)
            seats = random.randint(90,140)
            price = random.randint(*MIXED_PRICE_RANGE)

        dh, dm = map(int, departure.split(':'))
        arrival_hour = (dh + duration) % 24
        arrival = f"{arrival_hour:02d}:{dm:02d}"

        airline_tag = random.choice(["AirIndia", "Vistara", "IndiGo", "SpiceJet", "AirAsia", "Emirates", "Qatar"])

        flight_no = unique_flight_no(existing_fnos)

        flight = Flight(
            flight_no=flight_no,
            airline=airline_tag,
            source=source,
            destination=destination,
            departure_time=departure,
            arrival_time=arrival,
            seats_available=seats,
            date=date,
            price=price
        )

        try:
            db.session.add(flight)
            db.session.commit()
            created += 1
            print(f"✔ {flight_no} | {airline_tag} | {source} → {destination} | {date} | {departure}-{arrival} | ₹{price} | Seats:{seats}")
        except Exception as e:
            db.session.rollback()
            print("❌ Failed to add flight:", e)

    print(f"\n🎉 DONE — Created {created} flights.")
