from extensions import db
from werkzeug.security import generate_password_hash, check_password_hash


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=True)

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)


class Flight(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    flight_no = db.Column(db.String(20), unique=True, nullable=False)
    airline = db.Column(db.String(50), nullable=False)  # NEW
    source = db.Column(db.String(100), nullable=False)
    destination = db.Column(db.String(100), nullable=False)
    departure_time = db.Column(db.String(50), nullable=False)
    arrival_time = db.Column(db.String(50), nullable=False)
    seats_available = db.Column(db.Integer, nullable=False)
    date = db.Column(db.String(20), nullable=False)
    price = db.Column(db.Integer, nullable=False)  # NEW
    bookings = db.relationship("Booking", backref="flight", lazy=True)


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    flight_id = db.Column(db.Integer, db.ForeignKey("flight.id"), nullable=False)
    seat_class = db.Column(db.String(20), nullable=False)
    final_price = db.Column(db.Integer, nullable=False)
    seat_number = db.Column(db.String(5), nullable=False)
    payment_status = db.Column(db.String(20), default="Pending")
