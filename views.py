ADMIN_EMAIL = "admin@airline.com"
ADMIN_PASSWORD = "admin123"

from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import db
from models import Flight, Booking, User
from flask import session
import io
from PIL import Image
from reportlab.lib.utils import ImageReader
from flask import send_file
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from datetime import datetime



app_views = Blueprint('app_views', __name__)

# --- Homepage ---
@app_views.route('/')
def home():
    return render_template('home.html')

@app_views.route('/signup')
def signup_page():
    return render_template('signup.html')

@app_views.route('/signup', methods=['POST'])
def signup():
    name = request.form['name']
    email = request.form['email']
    password = request.form['password']

    existing = User.query.filter_by(email=email).first()
    if existing:
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
    return render_template('login.html')

@app_views.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            session['email'] = user.email
            session['name'] = user.name
            flash("Login successful!", "success")
            return redirect(url_for('app_views.home'))

        flash("Invalid email or password!", "danger")

    return render_template('login.html')



@app_views.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for('app_views.login_page'))


@app_views.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
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


# --- Booking Form Page ---
@app_views.route('/book/<int:flight_id>/<seat>')
def book_flight(flight_id, seat):
    if 'user_id' not in session:
        flash("Please login first!", "warning")
        return redirect(url_for('app_views.login_page'))

    flight = Flight.query.get_or_404(flight_id)

    # Build seat_class_map again (same as in select_seat)
    import string
    row_labels = list(string.ascii_uppercase)
    seat_class_map = {}
    current_row = 0

    # First Class
    first_rows = 2
    layout_fc = [1, 2, 1]
    for _ in range(first_rows):
        seat_num = 1
        row_label = row_labels[current_row]
        for block in layout_fc:
            for i in range(block):
                seat_name = f"{row_label}{seat_num}"
                seat_class_map[seat_name] = "First Class"
                seat_num += 1
        current_row += 1

    # Business Class
    business_rows = 4
    layout_bc = [2, 2]
    for _ in range(business_rows):
        seat_num = 1
        row_label = row_labels[current_row]
        for block in layout_bc:
            for i in range(block):
                seat_name = f"{row_label}{seat_num}"
                seat_class_map[seat_name] = "Business"
                seat_num += 1
        current_row += 1

    # Economy Class
    layout_ec = [3, 3]
    total_seats = flight.seats_available + Booking.query.filter_by(flight_id=flight_id).count()
    economy_seats = total_seats - (first_rows*sum(layout_fc) + business_rows*sum(layout_bc))
    rows_needed = (economy_seats + 6 - 1) // 6

    for _ in range(rows_needed):
        seat_num = 1
        row_label = row_labels[current_row]
        for block in layout_ec:
            for i in range(block):
                seat_name = f"{row_label}{seat_num}"
                seat_class_map[seat_name] = "Economy"
                seat_num += 1
        current_row += 1

    # Determine seat class
    seat_class = seat_class_map.get(seat, "Economy")

    # Price calculation
    multiplier = {"Economy": 1, "Business": 1.5, "First Class": 2.5}
    final_price = int(flight.price * multiplier[seat_class])

    return render_template(
        'booking.html',
        flight=flight,
        seat_number=seat,
        seat_class_map=seat_class_map,
        seat_class=seat_class,
        final_price=final_price
    )




# --- Booking Submission ---

@app_views.route('/select_seat/<int:flight_id>')
def select_seat(flight_id):
    flight = Flight.query.get_or_404(flight_id)

    # Total seats on aircraft = booked + available
    total_seats = flight.seats_available + \
        Booking.query.filter_by(flight_id=flight_id).count()

    import string
    row_labels = list(string.ascii_uppercase)

    seat_map = []
    seat_colors = {}
    seat_class_map = {}
    current_row = 0

    # ---- FIRST CLASS (2 rows - 1-2-1 layout) ----
    first_rows = 2
    layout_fc = [1, 2, 1]

    for _ in range(first_rows):
        row = []
        row_label = row_labels[current_row]
        seat_num = 1

        for block in layout_fc:
            for i in range(block):
                seat_name = f"{row_label}{seat_num}"
                row.append(seat_name)
                seat_class_map[seat_name] = "First Class"
                seat_colors[seat_name] = "first"
                seat_num += 1
            row.append(None)  # aisle

        seat_map.append(row)
        current_row += 1


    # ---- BUSINESS CLASS (4 rows - 2-2 layout) ----
    business_rows = 4
    layout_bc = [2, 2]

    for _ in range(business_rows):
        row = []
        row_label = row_labels[current_row]
        seat_num = 1

        for block in layout_bc:
            for i in range(block):
                seat_name = f"{row_label}{seat_num}"
                row.append(seat_name)
                seat_class_map[seat_name] = "Business"
                seat_colors[seat_name] = "business"
                seat_num += 1
            row.append(None)  # aisle

        seat_map.append(row)
        current_row += 1


    # ---- ECONOMY CLASS (remaining rows - 3-3 layout) ----
    layout_ec = [3, 3]

    occupied_first = first_rows * sum(layout_fc)
    occupied_business = business_rows * sum(layout_bc)
    used_seats = occupied_first + occupied_business

    economy_seats = total_seats - used_seats
    rows_needed = (economy_seats + 6 - 1) // 6

    for _ in range(rows_needed):
        row = []
        row_label = row_labels[current_row]
        seat_num = 1

        for block in layout_ec:
            for i in range(block):
                seat_name = f"{row_label}{seat_num}"
                row.append(seat_name)
                seat_class_map[seat_name] = "Economy"
                seat_colors[seat_name] = "economy"
                seat_num += 1
            row.append(None)  # aisle

        seat_map.append(row)
        current_row += 1


    # ---- Already booked seats ----
    booked_seats = [
        booking.seat_number
        for booking in Booking.query.filter_by(flight_id=flight_id).all()
    ]

    return render_template(
        'select_seat.html',
        flight=flight,
        seat_map=seat_map,
        booked_seats=booked_seats,
        seat_colors=seat_colors,
        seat_class_map=seat_class_map
    )


@app_views.route('/payment', methods=['POST'])
def payment():
    # User must be logged in
    if 'user_id' not in session:
        flash("Please login before booking a flight.", "warning")
        return redirect(url_for('app_views.login_page'))

    # Logged in user
    user = User.query.get(session['user_id'])
    if not user:
        flash("User not found!", "danger")
        return redirect(url_for('app_views.login_page'))

    # Get booking info from form
    flight_id = request.form['flight_id']
    seat_class = request.form['seat_class']
    seat_number = request.form['seat_number']
    final_price = request.form['final_price']

    flight = Flight.query.get_or_404(flight_id)

    # Send all required data to payment page
    return render_template(
        'payment.html',
        user=user,
        flight=flight,
        seat_class=seat_class,
        seat_number=seat_number,
        final_price=final_price
    )



@app_views.route('/verify_payment', methods=['POST'])
def verify_payment():
    if 'user_id' not in session:
        flash("Please login first!", "warning")
        return redirect(url_for('app_views.login_page'))

    flight_id = request.form['flight_id']
    seat_class = request.form['seat_class']
    seat_number = request.form['seat_number']
    final_price = request.form['final_price']

    return render_template(
        'otp.html',
        flight_id=flight_id,
        seat_class=seat_class,
        seat_number=seat_number,
        final_price=final_price
    )


@app_views.route('/finish_payment', methods=['POST'])
def finish_payment():
    if 'user_id' not in session:
        flash("Please login first!", "warning")
        return redirect(url_for('app_views.login_page'))

    otp = request.form['otp']

    if otp != "123456":
        flash("Invalid OTP. Payment Failed!", "danger")
        return redirect(url_for('app_views.home'))

    # Fetch logged-in user
    user = User.query.get(session['user_id'])
    if not user:
        flash("User not found!", "danger")
        return redirect(url_for('app_views.login_page'))

    # Retrieve all form values
    flight_id = int(request.form['flight_id'])
    seat_class = request.form['seat_class']
    seat_number = request.form['seat_number']
    final_price = int(request.form['final_price'])

    # Fetch flight
    flight = Flight.query.get_or_404(flight_id)

    # Create booking
    booking = Booking(
        user_id=user.id,
        flight_id=flight_id,
        seat_class=seat_class,
        seat_number=seat_number,
        final_price=final_price,
        payment_status="Paid"
    )

    # Reduce seat availability
    flight.seats_available -= 1

    db.session.add(booking)
    db.session.commit()

    flash("Payment Successful! Booking Confirmed.", "success")
    return redirect(url_for('app_views.my_bookings'))



@app_views.route('/flights', methods=['GET', 'POST'])
def flights_page():
    sources = [row[0] for row in db.session.query(Flight.source).distinct()]
    destinations = [row[0] for row in db.session.query(Flight.destination).distinct()]
    flights = Flight.query.all()

    if request.method == 'POST':
        source = request.form['source']
        destination = request.form['destination']
        date = request.form['date']

        query = Flight.query

        if source != "Any":
            query = query.filter_by(source=source)

        if destination != "Any":
            query = query.filter_by(destination=destination)

        if date != "":
            query = query.filter_by(date=date)

        flights = query.all()

        return render_template(
            'flights.html',
            flights=flights,
            sources=sources,
            destinations=destinations,
            selected_source=source,
            selected_destination=destination,
            selected_date=date
        )

    return render_template(
        'flights.html',
        flights=flights,
        sources=sources,
        destinations=destinations,
        selected_source="Any",
        selected_destination="Any",
        selected_date=""
    )


# --- View My Bookings Form ---
@app_views.route('/my_bookings')
def my_bookings():
    if 'user_id' not in session:
        flash("Please login first!", "warning")
        return redirect(url_for('app_views.login_page'))

    if 'user_id' not in session:
        flash("Please login to view your bookings", "warning")
        return redirect(url_for('app_views.login_page'))

    user = User.query.get(session['user_id'])

    bookings = db.session.query(Booking, Flight)\
        .join(Flight)\
        .filter(Booking.user_id == user.id)\
        .all()

    return render_template("show_bookings.html",
                           bookings=bookings,
                           email=user.email)



# --- Display User's Bookings ---
@app_views.route('/show_bookings', methods=['POST'])
def show_bookings():
    email = request.form['email']

    # Find the user
    user = User.query.filter_by(email=email).first()

    if not user:
        return render_template('show_bookings.html', bookings=None, email=email)

    # Join bookings with flight details
    bookings = db.session.query(Booking, Flight).join(Flight).filter(Booking.user_id == user.id).all()

    return render_template('show_bookings.html', bookings=bookings, email=email)

@app_views.route('/cancel_booking/<int:booking_id>')
def cancel_booking(booking_id):

    booking = Booking.query.get_or_404(booking_id)
    flight = Flight.query.get(booking.flight_id)

    # Increase seats once
    flight.seats_available += 1

    db.session.delete(booking)
    db.session.commit()

    flash("Booking cancelled successfully!", "success")
    return redirect(url_for('app_views.my_bookings'))

# ===================== ADMIN PANEL =====================

@app_views.route('/admin')
def admin_panel():
    if not session.get('admin_logged_in'):
        return redirect(url_for('app_views.admin_login'))
    flights = Flight.query.all()
    return render_template('admin.html', flights=flights)


@app_views.route('/add_flight', methods=['GET', 'POST'])
def add_flight():
    if request.method == 'POST':
        flight_no = request.form['flight_no']
        airline = request.form['airline']
        price = request.form['price']
        source = request.form['source']
        destination = request.form['destination']
        departure_time = request.form['departure_time']
        arrival_time = request.form['arrival_time']
        date = request.form['date']
        seats_available = request.form['seats_available']

        new_flight = Flight(
            flight_no=flight_no,
            airline=airline,
            source=source,
            destination=destination,
            departure_time=departure_time,
            arrival_time=arrival_time,
            seats_available=seats_available,
            date=date,
            price=price
        )

        db.session.add(new_flight)
        db.session.commit()

        flash(f"Flight {flight_no} added successfully!", "success")
        return redirect(url_for('app_views.admin_panel'))

    return render_template('add_flight.html')


@app_views.route('/delete_flight/<int:flight_id>')
def delete_flight(flight_id):
    flight = Flight.query.get_or_404(flight_id)
    db.session.delete(flight)
    db.session.commit()
    flash(f"Flight {flight.flight_no} deleted successfully!", "success")
    return redirect(url_for('app_views.admin_panel'))

@app_views.route('/edit_flight/<int:flight_id>', methods=['GET', 'POST'])
def edit_flight(flight_id):
    flight = Flight.query.get_or_404(flight_id)

    if request.method == 'POST':
        flight.flight_no = request.form['flight_no']
        flight.airline = request.form['airline']
        flight.source = request.form['source']
        flight.destination = request.form['destination']
        flight.departure_time = request.form['departure_time']
        flight.arrival_time = request.form['arrival_time']
        flight.seats_available = request.form['seats_available']
        flight.date = request.form['date']
        flight.price = request.form['price']

        db.session.commit()
        flash("Flight updated successfully!", "success")
        return redirect(url_for('app_views.admin_panel'))

    return render_template('edit_flight.html', flight=flight)


@app_views.route('/passengers/<int:flight_id>')
def passenger_list(flight_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('app_views.admin_login'))

    flight = Flight.query.get_or_404(flight_id)

    # Join Booking with User table
    passengers = db.session.query(Booking, User).join(User).filter(Booking.flight_id == flight_id).all()

    return render_template('passenger_list.html', flight=flight, passengers=passengers)

@app_views.route('/cancel_booking_admin/<int:booking_id>/<int:flight_id>')
def cancel_booking_admin(booking_id, flight_id):

    if not session.get('admin_logged_in'):
        return redirect(url_for('app_views.admin_login'))

    booking = Booking.query.get_or_404(booking_id)
    flight = Flight.query.get(flight_id)

    # Increase seats
    flight.seats_available += 1

    # Delete booking
    db.session.delete(booking)
    db.session.commit()

    flash("Passenger booking removed successfully!", "success")
    return redirect(url_for('app_views.passenger_list', flight_id=flight_id))


def generate_qr_code(data):
    import qrcode
    qr = qrcode.make(data)

    # Save to BytesIO
    byte_stream = io.BytesIO()
    qr.save(byte_stream, format="PNG")
    byte_stream.seek(0)

    # Convert to PIL Image
    pil_img = Image.open(byte_stream)

    return pil_img


@app_views.route('/ticket/<int:booking_id>/pdf')
def download_ticket(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    flight = Flight.query.get_or_404(booking.flight_id)
    user = User.query.get_or_404(booking.user_id)

    # PDF in memory
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)

    width, height = A4
    y = height - 50

    # TITLE
    p.setFont("Helvetica-Bold", 22)
    p.drawString(50, y, "BOARDING PASS")

    # Passenger Info
    y -= 40
    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, y, "Passenger Details")
    p.setFont("Helvetica", 12)
    y -= 25
    p.drawString(50, y, f"Name: {user.name}")
    y -= 20
    p.drawString(50, y, f"Email: {user.email}")

    # Flight Info
    y -= 40
    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, y, "Flight Details")
    p.setFont("Helvetica", 12)
    y -= 25
    p.drawString(50, y, f"Flight No: {flight.flight_no}")
    y -= 20
    p.drawString(50, y, f"Route: {flight.source} → {flight.destination}")
    y -= 20
    p.drawString(50, y, f"Date: {flight.date}")
    y -= 20
    p.drawString(50, y, f"Departure: {flight.departure_time}")
    y -= 20
    p.drawString(50, y, f"Arrival: {flight.arrival_time}")

    # Booking Info
    y -= 40
    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, y, "Booking Details")
    p.setFont("Helvetica", 12)
    y -= 25
    p.drawString(50, y, f"Seat: {booking.seat_number}")
    y -= 20
    p.drawString(50, y, f"Class: {booking.seat_class}")
    y -= 20
    p.drawString(50, y, f"Price: ₹{booking.final_price}")

    # QR Code
    qr_data = f"Booking:{booking.id} | Seat:{booking.seat_number} | Flight:{flight.flight_no}"
    qr_img = generate_qr_code(qr_data)

    if qr_img:
        qr_path = "temp_qr.png"
        qr_img.save(qr_path, format="PNG")
        p.drawImage(qr_path, width - 180, height - 250, 120, 120)
    else:
        p.drawString(width - 180, height - 250, "QR Unavailable")

    # Footer
    y -= 60
    p.setFont("Helvetica-Oblique", 10)
    p.drawString(50, 50, "This is a computer-generated boarding pass.")

    # Save + return
    p.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"boarding_pass_{booking.id}.pdf",
        mimetype='application/pdf'
    )

