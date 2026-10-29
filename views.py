import hmac
import io
import os
import string
import time
from datetime import datetime, timedelta
from functools import wraps

import qrcode
from flask import (Blueprint, render_template, request, redirect, url_for, flash,
                   session, send_file, jsonify, current_app, abort)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Flight, Booking, User
import payments

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@airline.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

app_views = Blueprint('app_views', __name__)


# ===================== helpers =====================

@app_views.app_template_filter('inr')
def inr(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return value


def safe_next(target):
    """Only allow same-site relative redirects."""
    if target and target.startswith('/') and not target.startswith('//'):
        return target
    return None


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please login first!", "warning")
            return redirect(url_for('app_views.login_page', next=request.full_path.rstrip('?')
                                    if request.method == 'GET' else None))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash("Admin login required.", "warning")
            return redirect(url_for('app_views.admin_login'))
        return view(*args, **kwargs)
    return wrapper


def current_user():
    user = User.query.get(session.get('user_id'))
    if not user:
        session.clear()
    return user


def build_seat_layout(flight):
    """Seat map for a flight: 2 first-class rows (1-2-1), 4 business rows (2-2), rest economy (3-3)."""
    row_labels = list(string.ascii_uppercase)
    total_seats = flight.seats_available + Booking.query.filter_by(flight_id=flight.id).count()

    seat_map, seat_colors, seat_class_map = [], {}, {}
    current_row = 0

    def add_rows(count, layout, cls, color):
        nonlocal current_row
        for _ in range(count):
            row, seat_num = [], 1
            label = row_labels[current_row % len(row_labels)]
            for block in layout:
                for _ in range(block):
                    name = f"{label}{seat_num}"
                    row.append(name)
                    seat_class_map[name] = cls
                    seat_colors[name] = color
                    seat_num += 1
                row.append(None)  # aisle
            seat_map.append(row)
            current_row += 1

    first_rows, layout_fc = 2, [1, 2, 1]
    business_rows, layout_bc = 4, [2, 2]
    add_rows(first_rows, layout_fc, "First Class", "first")
    add_rows(business_rows, layout_bc, "Business", "business")

    economy_seats = total_seats - (first_rows * sum(layout_fc) + business_rows * sum(layout_bc))
    rows_needed = max(0, (economy_seats + 5) // 6)
    add_rows(rows_needed, [3, 3], "Economy", "economy")

    return seat_map, seat_colors, seat_class_map


def seat_is_taken(flight_id, seat):
    return Booking.query.filter_by(flight_id=flight_id, seat_number=seat).first() is not None


def check_bookable(flight, seat):
    """Return (seat_class, error_message). error_message is None when the seat can be booked."""
    if payments.has_departed(flight):
        return None, "This flight has already departed."
    _, _, seat_class_map = build_seat_layout(flight)
    if seat not in seat_class_map:
        return None, "That seat does not exist on this flight."
    if seat_is_taken(flight.id, seat):
        return None, f"Seat {seat} was just taken. Please pick another seat."
    if flight.seats_available <= 0:
        return None, "This flight is sold out."
    return seat_class_map[seat], None


def get_pending():
    pending = session.get('pending_payment')
    if not pending:
        return None
    return pending


# ===================== pages & auth =====================

@app_views.route('/')
def home():
    return render_template('home.html')


@app_views.route('/signup')
def signup_page():
    return render_template('signup.html')


@app_views.route('/signup', methods=['POST'])
def signup():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')

    if not name or not email:
        flash("Name and email are required.", "danger")
        return redirect(url_for('app_views.signup_page'))
    if len(password) < 6:
        flash("Password must be at least 6 characters.", "danger")
        return redirect(url_for('app_views.signup_page'))

    if User.query.filter(func.lower(User.email) == email).first():
        flash("Email already exists. Please login.", "danger")
        return redirect(url_for('app_views.login_page'))

    user = User(name=name, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    flash("Account created successfully! Please login.", "success")
    return redirect(url_for('app_views.login_page'))


@app_views.route('/login')
def login_page():
    return render_template('login.html', next=safe_next(request.args.get('next')))


@app_views.route('/login', methods=['POST'])
def login():
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    nxt = safe_next(request.form.get('next'))

    user = User.query.filter(func.lower(User.email) == email).first()
    if user and user.password and user.check_password(password):
        session.pop('pending_payment', None)
        session['user_id'] = user.id
        session['email'] = user.email
        session['name'] = user.name
        session.permanent = True
        flash("Login successful!", "success")
        return redirect(nxt or url_for('app_views.home'))

    flash("Invalid email or password!", "danger")
    return render_template('login.html', next=nxt)


@app_views.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('email', None)
    session.pop('name', None)
    session.pop('pending_payment', None)
    flash("Logged out successfully.", "success")
    return redirect(url_for('app_views.login_page'))


@app_views.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email', '')
        password = request.form.get('password', '')

        if hmac.compare_digest(email, ADMIN_EMAIL) and hmac.compare_digest(password, ADMIN_PASSWORD):
            session['admin_logged_in'] = True
            flash("Admin login successful!", "success")
            return redirect(url_for('app_views.admin_panel'))

        flash("Invalid credentials!", "danger")
        return redirect(url_for('app_views.admin_login'))

    return render_template('admin_login.html')


@app_views.route('/admin_logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash("Logged out successfully!", "success")
    return redirect(url_for('app_views.home'))


# ===================== flights & seats =====================

@app_views.route('/flights', methods=['GET', 'POST'])
def flights_page():
    sources = sorted(row[0] for row in db.session.query(Flight.source).distinct())
    destinations = sorted(row[0] for row in db.session.query(Flight.destination).distinct())

    # POST (flights page form) and GET (home page search box) both work.
    values = request.values
    source = values.get('source', '').strip() or "Any"
    destination = values.get('destination', '').strip() or "Any"
    date = values.get('date', '').strip()

    query = Flight.query
    if source != "Any":
        query = query.filter(func.lower(Flight.source) == source.lower())
    if destination != "Any":
        query = query.filter(func.lower(Flight.destination) == destination.lower())
    if date:
        query = query.filter_by(date=date)

    flights = [f for f in query.order_by(Flight.date, Flight.departure_time).all()
               if not payments.has_departed(f)]

    return render_template('flights.html', flights=flights, sources=sources,
                           destinations=destinations, selected_source=source,
                           selected_destination=destination, selected_date=date)


@app_views.route('/select_seat/<int:flight_id>')
def select_seat(flight_id):
    flight = Flight.query.get_or_404(flight_id)
    if payments.has_departed(flight):
        flash("This flight has already departed.", "warning")
        return redirect(url_for('app_views.flights_page'))

    seat_map, seat_colors, seat_class_map = build_seat_layout(flight)
    booked_seats = [b.seat_number for b in Booking.query.filter_by(flight_id=flight_id).all()]
    prices = {cls: payments.fare_for(flight, cls) for cls in payments.SEAT_MULTIPLIER}

    return render_template('select_seat.html', flight=flight, seat_map=seat_map,
                           booked_seats=booked_seats, seat_colors=seat_colors,
                           seat_class_map=seat_class_map, prices=prices)


# ===================== checkout =====================

@app_views.route('/book/<int:flight_id>/<seat>')
@login_required
def book_flight(flight_id, seat):
    """Step 2: review the selection and fare."""
    user = current_user()
    if not user:
        return redirect(url_for('app_views.login_page'))
    flight = Flight.query.get_or_404(flight_id)

    seat_class, error = check_bookable(flight, seat)
    if error:
        flash(error, "warning")
        return redirect(url_for('app_views.select_seat', flight_id=flight_id))

    return render_template('booking.html', flight=flight, user=user, seat_number=seat,
                           seat_class=seat_class, q=payments.quote(flight, seat_class))


@app_views.route('/payment', methods=['POST'])
@login_required
def payment():
    """Step 3: choose a payment method."""
    user = current_user()
    if not user:
        return redirect(url_for('app_views.login_page'))

    flight = Flight.query.get_or_404(request.form.get('flight_id', type=int))
    seat = request.form.get('seat_number', '')

    seat_class, error = check_bookable(flight, seat)
    if error:
        flash(error, "warning")
        return redirect(url_for('app_views.select_seat', flight_id=flight.id))

    return render_template('payment.html', user=user, flight=flight, seat_number=seat,
                           seat_class=seat_class, q=payments.quote(flight, seat_class),
                           errors={}, form={}, banks=payments.NET_BANKS, promos=payments.PROMOS)


@app_views.route('/apply_promo', methods=['POST'])
@login_required
def apply_promo():
    flight = Flight.query.get_or_404(request.form.get('flight_id', type=int))
    seat_class, error = check_bookable(flight, request.form.get('seat_number', ''))
    if error:
        return jsonify(ok=False, message=error), 400
    q = payments.quote(flight, seat_class, request.form.get('promo', ''))
    return jsonify(ok=q['promo_valid'], message=q['promo_message'], fare=q['fare'],
                   discount=q['discount'], tax=q['tax'], total=q['total'])


@app_views.route('/verify_payment', methods=['POST'])
@login_required
def verify_payment():
    """Validate payment details server-side, then move on to OTP."""
    user = current_user()
    if not user:
        return redirect(url_for('app_views.login_page'))

    flight = Flight.query.get_or_404(request.form.get('flight_id', type=int))
    seat = request.form.get('seat_number', '')

    seat_class, error = check_bookable(flight, seat)
    if error:
        flash(error, "warning")
        return redirect(url_for('app_views.select_seat', flight_id=flight.id))

    q = payments.quote(flight, seat_class, request.form.get('promo', ''))
    errors, method, detail, declined = payments.validate_payment(request.form)
    if not q['promo_valid']:
        errors['promo'] = q['promo_message']

    if errors:
        # Never echo card number / CVV back into the page.
        form = {k: v for k, v in request.form.items() if k not in ('card_no', 'cvv')}
        return render_template('payment.html', user=user, flight=flight, seat_number=seat,
                               seat_class=seat_class, q=q, errors=errors, form=form,
                               banks=payments.NET_BANKS, promos=payments.PROMOS), 400

    if declined:
        flash("Payment declined by your bank. No money was charged. Try another card or method.", "danger")
        form = {k: v for k, v in request.form.items() if k not in ('card_no', 'cvv')}
        return render_template('payment.html', user=user, flight=flight, seat_number=seat,
                               seat_class=seat_class, q=q, errors={}, form=form,
                               banks=payments.NET_BANKS, promos=payments.PROMOS), 402

    txn_id = payments.new_transaction_id()
    otp = payments.new_otp()
    session['pending_payment'] = {
        'flight_id': flight.id,
        'seat': seat,
        'seat_class': seat_class,
        'fare': q['fare'], 'tax': q['tax'], 'discount': q['discount'],
        'total': q['total'], 'promo': q['promo'],
        'method': method, 'detail': detail,
        'txn_id': txn_id,
        'otp_hash': payments.otp_digest(current_app.config['SECRET_KEY'], txn_id, otp),
        'otp_expires': int(time.time()) + payments.OTP_TTL_SECONDS,
        'attempts': 0, 'resends': 0,
    }
    # Demo gateway: there is no SMS provider, so the OTP is shown on the next page.
    session['demo_otp'] = otp
    return redirect(url_for('app_views.otp_page'))


@app_views.route('/otp')
@login_required
def otp_page():
    """Step 4: OTP confirmation."""
    pending = get_pending()
    if not pending:
        flash("Your payment session expired. Please start again.", "warning")
        return redirect(url_for('app_views.flights_page'))

    flight = Flight.query.get_or_404(pending['flight_id'])
    seconds_left = max(0, pending['otp_expires'] - int(time.time()))
    return render_template('otp.html', flight=flight, p=pending, seconds_left=seconds_left,
                           demo_otp=session.get('demo_otp'),
                           attempts_left=payments.OTP_MAX_ATTEMPTS - pending['attempts'],
                           can_resend=pending['resends'] < payments.OTP_MAX_RESENDS)


@app_views.route('/resend_otp', methods=['POST'])
@login_required
def resend_otp():
    pending = get_pending()
    if not pending:
        return redirect(url_for('app_views.flights_page'))
    if pending['resends'] >= payments.OTP_MAX_RESENDS:
        flash("Resend limit reached. Please restart the payment.", "danger")
        return redirect(url_for('app_views.otp_page'))

    otp = payments.new_otp()
    pending['otp_hash'] = payments.otp_digest(current_app.config['SECRET_KEY'], pending['txn_id'], otp)
    pending['otp_expires'] = int(time.time()) + payments.OTP_TTL_SECONDS
    pending['resends'] += 1
    pending['attempts'] = 0
    session['pending_payment'] = pending
    session['demo_otp'] = otp
    flash("A new OTP has been sent.", "info")
    return redirect(url_for('app_views.otp_page'))


@app_views.route('/cancel_payment', methods=['POST'])
@login_required
def cancel_payment():
    pending = session.pop('pending_payment', None)
    session.pop('demo_otp', None)
    flash("Payment cancelled. You have not been charged.", "info")
    if pending:
        return redirect(url_for('app_views.select_seat', flight_id=pending['flight_id']))
    return redirect(url_for('app_views.flights_page'))


@app_views.route('/finish_payment', methods=['POST'])
@login_required
def finish_payment():
    """Step 5: verify OTP and issue the booking."""
    user = current_user()
    if not user:
        return redirect(url_for('app_views.login_page'))

    pending = get_pending()
    if not pending:
        flash("Your payment session expired. Please start again.", "warning")
        return redirect(url_for('app_views.flights_page'))

    flight = Flight.query.get_or_404(pending['flight_id'])

    if time.time() > pending['otp_expires']:
        flash("OTP expired. Request a new one.", "danger")
        return redirect(url_for('app_views.otp_page'))

    otp = request.form.get('otp', '').strip()
    expected = payments.otp_digest(current_app.config['SECRET_KEY'], pending['txn_id'], otp)
    if not hmac.compare_digest(expected, pending['otp_hash']):
        pending['attempts'] += 1
        if pending['attempts'] >= payments.OTP_MAX_ATTEMPTS:
            session.pop('pending_payment', None)
            session.pop('demo_otp', None)
            flash("Too many wrong OTP attempts. Payment failed and you have not been charged.", "danger")
            return redirect(url_for('app_views.select_seat', flight_id=flight.id))
        session['pending_payment'] = pending
        flash(f"Invalid OTP. {payments.OTP_MAX_ATTEMPTS - pending['attempts']} attempt(s) left.", "danger")
        return redirect(url_for('app_views.otp_page'))

    # OTP correct. Re-check availability: someone may have taken the seat while paying.
    _, error = check_bookable(flight, pending['seat'])
    if error:
        session.pop('pending_payment', None)
        session.pop('demo_otp', None)
        flash(f"{error} Your payment was not completed and you have not been charged.", "warning")
        return redirect(url_for('app_views.select_seat', flight_id=flight.id))

    booking = Booking(
        user_id=user.id, flight_id=flight.id,
        seat_class=pending['seat_class'], seat_number=pending['seat'],
        final_price=pending['total'], payment_status="Paid",
        transaction_id=pending['txn_id'], payment_method=pending['method'],
        payment_detail=pending['detail'], promo_code=pending['promo'] or None,
        discount=pending['discount'],
    )
    flight.seats_available -= 1
    db.session.add(booking)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        session.pop('pending_payment', None)
        session.pop('demo_otp', None)
        flash("That seat was just taken. You have not been charged. Please pick another seat.", "warning")
        return redirect(url_for('app_views.select_seat', flight_id=flight.id))

    session.pop('pending_payment', None)
    session.pop('demo_otp', None)
    flash("Payment successful! Booking confirmed.", "success")
    return redirect(url_for('app_views.confirmation', booking_id=booking.id))


@app_views.route('/booking/<int:booking_id>/confirmation')
@login_required
def confirmation(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != session['user_id'] and not session.get('admin_logged_in'):
        abort(403)
    return render_template('confirmation.html', booking=booking, flight=booking.flight)


# ===================== my bookings =====================

@app_views.route('/my_bookings')
@login_required
def my_bookings():
    user = current_user()
    if not user:
        return redirect(url_for('app_views.login_page'))

    rows = (db.session.query(Booking, Flight).join(Flight)
            .filter(Booking.user_id == user.id).order_by(Booking.id.desc()).all())

    items = []
    for booking, flight in rows:
        allowed, pct, amount = payments.refund_policy(booking, flight)
        items.append({'booking': booking, 'flight': flight, 'can_cancel': allowed,
                      'refund_pct': pct, 'refund_amount': amount,
                      'departed': payments.has_departed(flight)})

    return render_template('show_bookings.html', items=items, email=user.email)


@app_views.route('/show_bookings', methods=['GET', 'POST'])
def show_bookings():
    # Kept so old links keep working; bookings are only ever shown to their owner.
    return redirect(url_for('app_views.my_bookings'))


@app_views.route('/cancel_booking/<int:booking_id>', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != session['user_id']:
        abort(403)
    flight = Flight.query.get_or_404(booking.flight_id)

    allowed, pct, amount = payments.refund_policy(booking, flight)
    if not allowed:
        flash("This flight has already departed, so the booking can no longer be cancelled.", "danger")
        return redirect(url_for('app_views.my_bookings'))

    flight.seats_available += 1
    where = booking.payment_detail or booking.payment_method or "your original payment method"
    ref = booking.reference
    db.session.delete(booking)
    db.session.commit()

    flash(f"Booking {ref} cancelled. Refund of ₹{amount:,} ({pct}%) will be credited to {where} "
          f"in 5-7 working days.", "success")
    return redirect(url_for('app_views.my_bookings'))


# ===================== admin panel =====================

@app_views.route('/admin')
@admin_required
def admin_panel():
    flights = Flight.query.order_by(Flight.date, Flight.departure_time).all()
    return render_template('admin.html', flights=flights)


def read_flight_form(form):
    """Parse and validate the add/edit flight form. Returns (data, error)."""
    try:
        data = {
            'flight_no': form['flight_no'].strip().upper(),
            'airline': form['airline'].strip(),
            'source': form['source'].strip(),
            'destination': form['destination'].strip(),
            'departure_time': form['departure_time'].strip(),
            'arrival_time': form['arrival_time'].strip(),
            'date': form['date'].strip(),
            'seats_available': int(form['seats_available']),
            'price': int(form['price']),
        }
    except (KeyError, ValueError):
        return None, "Please fill in every field with valid values."
    if not all(str(v) for v in data.values()):
        return None, "Please fill in every field."
    if data['source'].lower() == data['destination'].lower():
        return None, "Source and destination must be different."
    if data['seats_available'] < 0 or data['price'] <= 0:
        return None, "Seats and price must be positive."
    try:
        datetime.strptime(data['date'], "%Y-%m-%d")
    except ValueError:
        return None, "Date must be YYYY-MM-DD."
    return data, None


@app_views.route('/add_flight', methods=['GET', 'POST'])
@admin_required
def add_flight():
    if request.method == 'POST':
        data, error = read_flight_form(request.form)
        if error:
            flash(error, "danger")
            return redirect(url_for('app_views.add_flight'))
        if Flight.query.filter_by(flight_no=data['flight_no']).first():
            flash(f"Flight {data['flight_no']} already exists.", "danger")
            return redirect(url_for('app_views.add_flight'))

        db.session.add(Flight(**data))
        db.session.commit()
        flash(f"Flight {data['flight_no']} added successfully!", "success")
        return redirect(url_for('app_views.admin_panel'))

    return render_template('add_flight.html')


@app_views.route('/delete_flight/<int:flight_id>', methods=['POST'])
@admin_required
def delete_flight(flight_id):
    flight = Flight.query.get_or_404(flight_id)
    if Booking.query.filter_by(flight_id=flight_id).count():
        flash(f"Flight {flight.flight_no} has bookings. Remove its passengers first.", "danger")
        return redirect(url_for('app_views.admin_panel'))
    db.session.delete(flight)
    db.session.commit()
    flash(f"Flight {flight.flight_no} deleted successfully!", "success")
    return redirect(url_for('app_views.admin_panel'))


@app_views.route('/edit_flight/<int:flight_id>', methods=['GET', 'POST'])
@admin_required
def edit_flight(flight_id):
    flight = Flight.query.get_or_404(flight_id)

    if request.method == 'POST':
        data, error = read_flight_form(request.form)
        if error:
            flash(error, "danger")
            return redirect(url_for('app_views.edit_flight', flight_id=flight_id))
        clash = Flight.query.filter(Flight.flight_no == data['flight_no'], Flight.id != flight_id).first()
        if clash:
            flash(f"Flight {data['flight_no']} already exists.", "danger")
            return redirect(url_for('app_views.edit_flight', flight_id=flight_id))

        for key, value in data.items():
            setattr(flight, key, value)
        db.session.commit()
        flash("Flight updated successfully!", "success")
        return redirect(url_for('app_views.admin_panel'))

    return render_template('edit_flight.html', flight=flight)


@app_views.route('/passengers/<int:flight_id>')
@admin_required
def passenger_list(flight_id):
    flight = Flight.query.get_or_404(flight_id)
    passengers = (db.session.query(Booking, User).join(User)
                  .filter(Booking.flight_id == flight_id).all())
    return render_template('passenger_list.html', flight=flight, passengers=passengers)


@app_views.route('/cancel_booking_admin/<int:booking_id>/<int:flight_id>', methods=['POST'])
@admin_required
def cancel_booking_admin(booking_id, flight_id):
    booking = Booking.query.get_or_404(booking_id)
    flight = Flight.query.get_or_404(booking.flight_id)

    flight.seats_available += 1
    db.session.delete(booking)
    db.session.commit()

    flash("Passenger booking removed (full refund due to the passenger).", "success")
    return redirect(url_for('app_views.passenger_list', flight_id=flight_id))


# ===================== boarding pass PDF =====================

def generate_qr_image(data):
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


@app_views.route('/ticket/<int:booking_id>/pdf')
@login_required
def download_ticket(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != session['user_id'] and not session.get('admin_logged_in'):
        abort(403)
    flight = Flight.query.get_or_404(booking.flight_id)
    user = User.query.get_or_404(booking.user_id)

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    navy = colors.HexColor("#003366")
    grey = colors.HexColor("#667085")

    # Header band
    p.setFillColor(navy)
    p.rect(0, height - 90, width, 90, stroke=0, fill=1)
    p.setFillColor(colors.white)
    p.setFont("Helvetica-Bold", 24)
    p.drawString(40, height - 55, "BOARDING PASS")
    p.setFont("Helvetica", 11)
    p.drawRightString(width - 40, height - 45, flight.airline)
    p.drawRightString(width - 40, height - 62, f"Flight {flight.flight_no}")

    # Route
    p.setFillColor(navy)
    p.setFont("Helvetica-Bold", 26)
    p.drawString(40, height - 140, flight.source)
    p.drawCentredString(width / 2, height - 140, "->")
    p.drawRightString(width - 40, height - 140, flight.destination)
    p.setFillColor(grey)
    p.setFont("Helvetica", 10)
    p.drawString(40, height - 158, f"Departs {flight.departure_time}")
    p.drawRightString(width - 40, height - 158, f"Arrives {flight.arrival_time}")

    p.setStrokeColor(colors.HexColor("#d0d5dd"))
    p.line(40, height - 175, width - 40, height - 175)

    def field(x, y, label, value):
        p.setFillColor(grey)
        p.setFont("Helvetica", 9)
        p.drawString(x, y, label.upper())
        p.setFillColor(colors.black)
        p.setFont("Helvetica-Bold", 13)
        p.drawString(x, y - 18, str(value))

    y = height - 215
    field(40, y, "Passenger", user.name)
    field(300, y, "Booking ref", booking.reference)
    y -= 55
    field(40, y, "Date", flight.date)
    field(190, y, "Seat", booking.seat_number)
    field(300, y, "Class", booking.seat_class)
    y -= 55
    field(40, y, "Email", user.email)
    field(300, y, "Amount paid", f"INR {booking.final_price:,}")
    y -= 55
    if booking.transaction_id:
        field(40, y, "Transaction ID", booking.transaction_id)
        field(300, y, "Paid via", f"{booking.payment_method} ({booking.payment_detail})"
              if booking.payment_detail else booking.payment_method)

    # QR code
    qr_data = f"{booking.reference} | Seat:{booking.seat_number} | Flight:{flight.flight_no} | {flight.date}"
    p.drawImage(generate_qr_image(qr_data), width - 190, 120, 150, 150)
    p.setFillColor(grey)
    p.setFont("Helvetica", 9)
    p.drawCentredString(width - 115, 105, "Scan at the gate")

    p.setFont("Helvetica-Oblique", 9)
    p.drawString(40, 50, "This is a computer-generated boarding pass. Please carry a valid photo ID.")

    p.showPage()
    p.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name=f"boarding_pass_{booking.reference}.pdf",
                     mimetype='application/pdf')
