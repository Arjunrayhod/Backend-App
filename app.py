import os
import datetime
import jwt
from functools import wraps
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_db_connection, init_db
from utils.ticket_generator import generate_qr_code, generate_pdf_ticket

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'cloudbus-secret-key-codealpha-2026')

# Initialize SQLite database on startup (ensures tables & default data exist on Render)
init_db()

CORS(app, resources={
    r"/api/*": {"origins": "*"}, 
    r"/static/*": {"origins": "*"}
})

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
TICKETS_DIR = os.path.join(STATIC_DIR, 'tickets')
QR_DIR = os.path.join(TICKETS_DIR, 'qr')
PDF_DIR = os.path.join(TICKETS_DIR, 'pdf')

os.makedirs(QR_DIR, exist_ok=True)
os.makedirs(PDF_DIR, exist_ok=True)

# ----------------- Auth Decorators -----------------

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')

        if auth_header:
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == 'bearer':
                token = parts[1]
            elif len(parts) == 1:
                token = parts[0]

        if not token:
            return jsonify({"error": "Authentication token is missing"}), 401

        try:
            payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            user_id = payload['user_id']
            
            conn = get_db_connection()
            user = conn.execute('SELECT id, name, email, role FROM users WHERE id = ?', (user_id,)).fetchone()
            conn.close()

            if not user:
                return jsonify({"error": "User not found or account deactivated"}), 401

            current_user = dict(user)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Session token has expired, please log in again"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        except Exception as e:
            return jsonify({"error": f"Auth error: {str(e)}"}), 401

        return f(current_user, *args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(current_user, *args, **kwargs):
        if current_user.get('role') != 'admin':
            return jsonify({"error": "Admin privileges required for this action"}), 403
        return f(current_user, *args, **kwargs)
    return decorated

# ----------------- Helper Functions -----------------

def generate_jwt_token(user_id, email, role):
    payload = {
        'user_id': user_id,
        'email': email,
        'role': role,
        'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
        'iat': datetime.datetime.now(datetime.timezone.utc)
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm="HS256")

# ----------------- Health & Info -----------------

@app.route('/', methods=['GET'])
@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "online",
        "service": "CloudBus Pass System API (Render.com)",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }), 200

# ----------------- Auth Routes -----------------

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    if not name or not email or not password:
        return jsonify({"error": "Name, email, and password are required"}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long"}), 400

    conn = get_db_connection()
    existing = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "An account with this email already exists"}), 409

    hashed_pw = generate_password_hash(password)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)',
        (name, email, hashed_pw, 'user')
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()

    token = generate_jwt_token(user_id, email, 'user')

    return jsonify({
        "message": "User registered successfully",
        "token": token,
        "user": {
            "id": user_id,
            "name": name,
            "email": email,
            "role": "user"
        }
    }), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    conn.close()

    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({"error": "Invalid email or password"}), 401

    token = generate_jwt_token(user['id'], user['email'], user['role'])

    return jsonify({
        "message": "Login successful",
        "token": token,
        "user": {
            "id": user['id'],
            "name": user['name'],
            "email": user['email'],
            "role": user['role']
        }
    }), 200

@app.route('/api/me', methods=['GET'])
@token_required
def get_current_user(current_user):
    return jsonify({"user": current_user}), 200

# ----------------- Routes API -----------------

@app.route('/api/routes', methods=['GET'])
def get_routes():
    conn = get_db_connection()
    routes = conn.execute('SELECT * FROM routes ORDER BY source ASC, destination ASC').fetchall()
    conn.close()
    return jsonify({"routes": [dict(r) for r in routes]}), 200

@app.route('/api/routes/<int:route_id>', methods=['GET'])
def get_route_by_id(route_id):
    conn = get_db_connection()
    route = conn.execute('SELECT * FROM routes WHERE id = ?', (route_id,)).fetchone()
    conn.close()
    if not route:
        return jsonify({"error": "Route not found"}), 404
    return jsonify({"route": dict(route)}), 200

@app.route('/api/routes', methods=['POST'])
@token_required
@admin_required
def add_route(current_user):
    data = request.get_json() or {}
    source = data.get('source', '').strip()
    destination = data.get('destination', '').strip()
    distance_km = data.get('distance_km')
    price = data.get('price')
    departure_time = data.get('departure_time', '').strip()

    if not source or not destination or distance_km is None or price is None or not departure_time:
        return jsonify({"error": "Source, destination, distance_km, price, and departure_time are all required"}), 400

    try:
        distance_km = float(distance_km)
        price = float(price)
    except ValueError:
        return jsonify({"error": "Distance and price must be valid numbers"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO routes (source, destination, distance_km, price, departure_time)
        VALUES (?, ?, ?, ?, ?)
    ''', (source, destination, distance_km, price, departure_time))
    route_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        "message": "Bus route created successfully",
        "route": {
            "id": route_id,
            "source": source,
            "destination": destination,
            "distance_km": distance_km,
            "price": price,
            "departure_time": departure_time
        }
    }), 201

@app.route('/api/routes/<int:route_id>', methods=['PUT'])
@token_required
@admin_required
def update_route(current_user, route_id):
    data = request.get_json() or {}
    source = data.get('source', '').strip()
    destination = data.get('destination', '').strip()
    distance_km = data.get('distance_km')
    price = data.get('price')
    departure_time = data.get('departure_time', '').strip()

    if not source or not destination or distance_km is None or price is None or not departure_time:
        return jsonify({"error": "All fields are required"}), 400

    try:
        distance_km = float(distance_km)
        price = float(price)
    except ValueError:
        return jsonify({"error": "Distance and price must be valid numbers"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    route = cursor.execute('SELECT id FROM routes WHERE id = ?', (route_id,)).fetchone()
    if not route:
        conn.close()
        return jsonify({"error": "Route not found"}), 404

    cursor.execute('''
        UPDATE routes
        SET source = ?, destination = ?, distance_km = ?, price = ?, departure_time = ?
        WHERE id = ?
    ''', (source, destination, distance_km, price, departure_time, route_id))
    conn.commit()
    conn.close()

    return jsonify({"message": "Route updated successfully"}), 200

@app.route('/api/routes/<int:route_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_route(current_user, route_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    route = cursor.execute('SELECT id FROM routes WHERE id = ?', (route_id,)).fetchone()
    if not route:
        conn.close()
        return jsonify({"error": "Route not found"}), 404

    cursor.execute('DELETE FROM routes WHERE id = ?', (route_id,))
    conn.commit()
    conn.close()

    return jsonify({"message": "Route deleted successfully"}), 200

@app.route('/api/routes/<int:route_id>/booked-seats', methods=['GET'])
def get_booked_seats(route_id):
    travel_date = request.args.get('date')
    if not travel_date:
        return jsonify({"error": "date query parameter (YYYY-MM-DD) is required"}), 400

    conn = get_db_connection()
    booked = conn.execute('''
        SELECT seat_number FROM tickets
        WHERE route_id = ? AND travel_date = ? AND status IN ('CONFIRMED', 'PENDING')
    ''', (route_id, travel_date)).fetchall()
    conn.close()

    seats = [row['seat_number'] for row in booked]
    return jsonify({"booked_seats": seats}), 200

# ----------------- Ticket Booking & Retrieval -----------------

@app.route('/api/book', methods=['POST'])
@token_required
def book_ticket(current_user):
    data = request.get_json() or {}
    route_id = data.get('route_id')
    travel_date = data.get('travel_date', '').strip()
    seat_number = data.get('seat_number')
    pass_type = data.get('pass_type', 'single') # 'single', 'daily', 'student', 'monthly'
    student_id_number = data.get('student_id_number', '').strip()

    if not route_id or not travel_date or not seat_number:
        return jsonify({"error": "route_id, travel_date, and seat_number are required"}), 400

    try:
        seat_number = int(seat_number)
        if seat_number < 1 or seat_number > 40:
            return jsonify({"error": "Seat number must be between 1 and 40"}), 400
    except ValueError:
        return jsonify({"error": "Invalid seat number"}), 400

    # Validate date format YYYY-MM-DD
    try:
        parsed_date = datetime.datetime.strptime(travel_date, "%Y-%m-%d").date()
        if parsed_date < datetime.date.today():
            return jsonify({"error": "Travel date cannot be in the past"}), 400
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify route exists
    route = cursor.execute('SELECT * FROM routes WHERE id = ?', (route_id,)).fetchone()
    if not route:
        conn.close()
        return jsonify({"error": "Selected route does not exist"}), 404

    # Calculate pass validity and fare
    base_price = float(route['price'])
    valid_until = travel_date
    if pass_type == 'daily':
        amount_paid = round(base_price * 1.5, 2)
        valid_until = travel_date
    elif pass_type == 'student':
        if not student_id_number:
            student_id_number = f"STU-{current_user['id']:04d}"
        amount_paid = round(base_price * 8.0, 2) # 50% discount on monthly pass
        valid_until = (parsed_date + datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    elif pass_type == 'monthly':
        amount_paid = round(base_price * 14.0, 2) # Commuter monthly pass
        valid_until = (parsed_date + datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    else:
        pass_type = 'single'
        amount_paid = base_price
        valid_until = travel_date

    # Check if seat is already booked or pending for that date on that route
    conflict = cursor.execute('''
        SELECT id FROM tickets
        WHERE route_id = ? AND travel_date = ? AND seat_number = ? AND status IN ('CONFIRMED', 'PENDING')
    ''', (route_id, travel_date, seat_number)).fetchone()

    if conflict:
        conn.close()
        return jsonify({"error": f"Seat #{seat_number} is already booked/pending for {travel_date}. Please choose another seat."}), 409

    # Insert ticket record with initial PENDING status (Awaiting Admin Approval)
    cursor.execute('''
        INSERT INTO tickets (
            user_id, route_id, travel_date, seat_number, pass_type,
            valid_until, student_id_number, amount_paid, is_boarded, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'PENDING')
    ''', (current_user['id'], route_id, travel_date, seat_number, pass_type, valid_until, student_id_number, amount_paid))
    ticket_id = cursor.lastrowid
    conn.commit()

    # Query full ticket data for QR and PDF generation
    ticket_row = cursor.execute('''
        SELECT t.*, u.name as user_name, u.email as user_email,
               r.source, r.destination, r.distance_km, r.price, r.departure_time
        FROM tickets t
        JOIN users u ON t.user_id = u.id
        JOIN routes r ON t.route_id = r.id
        WHERE t.id = ?
    ''', (ticket_id,)).fetchone()

    ticket_data = dict(ticket_row)

    # Generate QR Code and PDF
    try:
        qr_filename, qr_filepath = generate_qr_code(ticket_data, QR_DIR)
        pdf_filename, _ = generate_pdf_ticket(ticket_data, qr_filepath, PDF_DIR)

        # Update ticket record with filenames
        cursor.execute('''
            UPDATE tickets
            SET qr_filename = ?, pdf_filename = ?
            WHERE id = ?
        ''', (qr_filename, pdf_filename, ticket_id))
        conn.commit()

        ticket_data['qr_filename'] = qr_filename
        ticket_data['pdf_filename'] = pdf_filename
    except Exception as e:
        print(f"Error generating ticket artifacts: {e}")
    finally:
        conn.close()

    return jsonify({
        "message": "Pass application submitted successfully! Status is PENDING Admin Approval.",
        "ticket": ticket_data
    }), 201

@app.route('/api/my-tickets', methods=['GET'])
@token_required
def get_my_tickets(current_user):
    conn = get_db_connection()
    tickets = conn.execute('''
        SELECT t.*, u.name as user_name, u.email as user_email,
               r.source, r.destination, r.distance_km, r.price, r.departure_time
        FROM tickets t
        JOIN users u ON t.user_id = u.id
        JOIN routes r ON t.route_id = r.id
        WHERE t.user_id = ?
        ORDER BY t.booked_at DESC
    ''', (current_user['id'],)).fetchall()
    conn.close()

    return jsonify({"tickets": [dict(t) for t in tickets]}), 200

@app.route('/api/ticket/qr/<int:ticket_id>', methods=['GET'])
def get_ticket_qr(ticket_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    ticket_row = cursor.execute('''
        SELECT t.*, u.name as user_name, u.email as user_email,
               r.source, r.destination, r.distance_km, r.price, r.departure_time
        FROM tickets t
        JOIN users u ON t.user_id = u.id
        JOIN routes r ON t.route_id = r.id
        WHERE t.id = ?
    ''', (ticket_id,)).fetchone()

    if not ticket_row:
        conn.close()
        return jsonify({"error": "Ticket not found"}), 404

    ticket_data = dict(ticket_row)
    qr_filename = ticket_data.get('qr_filename') or f"ticket_qr_{ticket_id}.png"
    qr_path = os.path.join(QR_DIR, qr_filename)

    if not os.path.exists(qr_path):
        try:
            qr_filename, qr_path = generate_qr_code(ticket_data, QR_DIR)
            cursor.execute('UPDATE tickets SET qr_filename = ? WHERE id = ?', (qr_filename, ticket_id))
            conn.commit()
        except Exception as e:
            print(f"Error regenerating QR: {e}")
    conn.close()

    if not os.path.exists(qr_path):
        return jsonify({"error": "QR image missing"}), 404

    return send_file(qr_path, mimetype='image/png', as_attachment=False)

@app.route('/api/ticket/pdf/<int:ticket_id>', methods=['GET'])
def get_ticket_pdf(ticket_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    ticket_row = cursor.execute('''
        SELECT t.*, u.name as user_name, u.email as user_email,
               r.source, r.destination, r.distance_km, r.price, r.departure_time
        FROM tickets t
        JOIN users u ON t.user_id = u.id
        JOIN routes r ON t.route_id = r.id
        WHERE t.id = ?
    ''', (ticket_id,)).fetchone()

    if not ticket_row:
        conn.close()
        return jsonify({"error": "Ticket not found"}), 404

    ticket_data = dict(ticket_row)
    pdf_filename = ticket_data.get('pdf_filename') or f"ticket_{ticket_id}.pdf"
    pdf_path = os.path.join(PDF_DIR, pdf_filename)

    # Regenerate on the fly if disk was reset by Render
    if not os.path.exists(pdf_path):
        try:
            qr_filename, qr_path = generate_qr_code(ticket_data, QR_DIR)
            pdf_filename, pdf_path = generate_pdf_ticket(ticket_data, qr_path, PDF_DIR)
            cursor.execute('UPDATE tickets SET qr_filename = ?, pdf_filename = ? WHERE id = ?', (qr_filename, pdf_filename, ticket_id))
            conn.commit()
        except Exception as e:
            print(f"Error regenerating PDF: {e}")
    conn.close()

    if not os.path.exists(pdf_path):
        return jsonify({"error": "PDF file could not be generated"}), 500

    download_mode = request.args.get('download', '1') == '1'
    response = send_file(
        pdf_path,
        mimetype='application/pdf',
        as_attachment=download_mode,
        download_name=f"CloudBus_Pass_BP{ticket_id:06d}.pdf"
    )
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Content-Disposition'] = f'{"attachment" if download_mode else "inline"}; filename="CloudBus_Pass_BP{ticket_id:06d}.pdf"'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

@app.route('/api/tickets/<int:ticket_id>', methods=['DELETE'])
@token_required
def cancel_ticket(current_user, ticket_id):
    """
    Cancels and deletes a booked bus pass.
    Allows passenger (owner) or Admin to cancel.
    Frees up the booked seat immediately.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    ticket = cursor.execute('SELECT * FROM tickets WHERE id = ?', (ticket_id,)).fetchone()
    if not ticket:
        conn.close()
        return jsonify({"error": "Ticket not found"}), 404

    # Permission check: must be ticket owner or admin
    if current_user['role'] != 'admin' and ticket['user_id'] != current_user['id']:
        conn.close()
        return jsonify({"error": "Unauthorized to cancel this ticket"}), 403

    # Delete ticket from database to free up seat
    cursor.execute('DELETE FROM tickets WHERE id = ?', (ticket_id,))
    conn.commit()
    conn.close()

    # Clean up generated artifacts if they exist
    try:
        if ticket['qr_filename']:
            qr_file = os.path.join(QR_DIR, ticket['qr_filename'])
            if os.path.exists(qr_file):
                os.remove(qr_file)
        if ticket['pdf_filename']:
            pdf_file = os.path.join(PDF_DIR, ticket['pdf_filename'])
            if os.path.exists(pdf_file):
                os.remove(pdf_file)
    except Exception as e:
        print(f"Notice: Artifact removal error for ticket #{ticket_id}: {e}")

    return jsonify({
        "message": f"Pass #BP-{ticket_id:06d} cancelled and seat #{ticket['seat_number']} has been freed.",
        "cancelled_ticket_id": ticket_id,
        "freed_seat": ticket['seat_number']
    }), 200

# ----------------- Conductor / Admin Ticket Verification -----------------

@app.route('/api/verify-ticket/<ticket_ref>', methods=['GET'])
def verify_ticket(ticket_ref):
    """
    Validates ticket by numeric ID or BP-000001 format or JSON string payload.
    """
    clean_id = None
    ref_str = str(ticket_ref).strip()

    if ref_str.upper().startswith('BP-'):
        try:
            clean_id = int(ref_str.split('-')[1])
        except ValueError:
            clean_id = None
    elif ref_str.isdigit():
        clean_id = int(ref_str)

    conn = get_db_connection()
    ticket = None
    if clean_id:
        ticket = conn.execute('''
            SELECT t.*, u.name as user_name, u.email as user_email,
                   r.source, r.destination, r.distance_km, r.price, r.departure_time
            FROM tickets t
            JOIN users u ON t.user_id = u.id
            JOIN routes r ON t.route_id = r.id
            WHERE t.id = ?
        ''', (clean_id,)).fetchone()

    conn.close()

    if not ticket:
        return jsonify({
            "valid": False,
            "error": f"Ticket #{ticket_ref} was not found in system records."
        }), 404

    ticket_data = dict(ticket)
    # Check validity date and approval status
    valid_until = ticket_data.get('valid_until') or ticket_data['travel_date']
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    is_expired = valid_until < today_str
    is_confirmed = (ticket_data.get('status') == 'CONFIRMED')
    is_pending = (ticket_data.get('status') == 'PENDING')
    is_valid = (not is_expired) and is_confirmed

    status_message = "Pass is Confirmed & Active" if is_valid else (
        "Pass is PENDING Admin Approval (Not yet active for boarding)" if is_pending else (
            "Pass has EXPIRED" if is_expired else f"Pass status: {ticket_data.get('status')}"
        )
    )

    return jsonify({
        "valid": is_valid,
        "is_expired": is_expired,
        "is_pending": is_pending,
        "status_message": status_message,
        "is_boarded": bool(ticket_data.get('is_boarded')),
        "ticket": ticket_data
    }), 200

@app.route('/api/tickets/<int:ticket_id>/board', methods=['POST'])
@token_required
def mark_ticket_boarded(current_user, ticket_id):
    """
    Conductor marks passenger as boarded.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    ticket = cursor.execute('SELECT * FROM tickets WHERE id = ?', (ticket_id,)).fetchone()
    if not ticket:
        conn.close()
        return jsonify({"error": "Ticket not found"}), 404

    cursor.execute('UPDATE tickets SET is_boarded = 1 WHERE id = ?', (ticket_id,))
    conn.commit()
    conn.close()

    return jsonify({"message": f"Ticket #BP-{ticket_id:06d} marked as BOARDED successfully", "is_boarded": True}), 200

# ----------------- Admin Management & Analytics Routes -----------------

@app.route('/api/admin/tickets/<int:ticket_id>/approve', methods=['POST'])
@token_required
@admin_required
def approve_ticket(current_user, ticket_id):
    """
    Admin approves a pending bus pass / ticket application.
    Updates status to 'CONFIRMED' and regenerates official QR & PDF.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    ticket_row = cursor.execute('''
        SELECT t.*, u.name as user_name, u.email as user_email,
               r.source, r.destination, r.distance_km, r.price, r.departure_time
        FROM tickets t
        JOIN users u ON t.user_id = u.id
        JOIN routes r ON t.route_id = r.id
        WHERE t.id = ?
    ''', (ticket_id,)).fetchone()

    if not ticket_row:
        conn.close()
        return jsonify({"error": "Ticket not found"}), 404

    ticket_data = dict(ticket_row)
    ticket_data['status'] = 'CONFIRMED'

    # Update database status to CONFIRMED
    cursor.execute("UPDATE tickets SET status = 'CONFIRMED' WHERE id = ?", (ticket_id,))
    conn.commit()

    # Regenerate artifacts with CONFIRMED stamp
    try:
        qr_filename, qr_filepath = generate_qr_code(ticket_data, QR_DIR)
        pdf_filename, _ = generate_pdf_ticket(ticket_data, qr_filepath, PDF_DIR)
        cursor.execute("UPDATE tickets SET qr_filename = ?, pdf_filename = ? WHERE id = ?", (qr_filename, pdf_filename, ticket_id))
        conn.commit()
        ticket_data['qr_filename'] = qr_filename
        ticket_data['pdf_filename'] = pdf_filename
    except Exception as e:
        print(f"Error regenerating approved artifacts: {e}")
    finally:
        conn.close()

    return jsonify({
        "message": f"Pass #BP-{ticket_id:06d} has been APPROVED and is now active!",
        "ticket": ticket_data
    }), 200

@app.route('/api/admin/tickets/<int:ticket_id>/reject', methods=['POST'])
@token_required
@admin_required
def reject_ticket(current_user, ticket_id):
    """
    Admin rejects a bus pass application.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    ticket = cursor.execute('SELECT * FROM tickets WHERE id = ?', (ticket_id,)).fetchone()
    if not ticket:
        conn.close()
        return jsonify({"error": "Ticket not found"}), 404

    cursor.execute("UPDATE tickets SET status = 'REJECTED' WHERE id = ?", (ticket_id,))
    conn.commit()
    conn.close()

    return jsonify({
        "message": f"Pass #BP-{ticket_id:06d} application was REJECTED.",
        "ticket_id": ticket_id,
        "status": "REJECTED"
    }), 200

@app.route('/api/admin/bookings', methods=['GET'])
@token_required
@admin_required
def get_all_bookings(current_user):
    conn = get_db_connection()
    bookings = conn.execute('''
        SELECT t.*, u.name as user_name, u.email as user_email,
               r.source, r.destination, r.distance_km, r.price, r.departure_time
        FROM tickets t
        JOIN users u ON t.user_id = u.id
        JOIN routes r ON t.route_id = r.id
        ORDER BY t.booked_at DESC
    ''').fetchall()
    conn.close()

    return jsonify({"bookings": [dict(b) for b in bookings]}), 200

@app.route('/api/admin/users', methods=['GET'])
@token_required
@admin_required
def get_all_users(current_user):
    conn = get_db_connection()
    users = conn.execute('SELECT id, name, email, role, created_at FROM users ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify({"users": [dict(u) for u in users]}), 200

@app.route('/api/admin/stats', methods=['GET'])
@token_required
@admin_required
def get_admin_stats(current_user):
    conn = get_db_connection()
    total_users = conn.execute('SELECT COUNT(*) as c FROM users WHERE role = "user"').fetchone()['c']
    total_routes = conn.execute('SELECT COUNT(*) as c FROM routes').fetchone()['c']
    total_tickets = conn.execute('SELECT COUNT(*) as c FROM tickets').fetchone()['c']
    revenue_res = conn.execute('''
        SELECT SUM(COALESCE(amount_paid, r.price)) as total_rev
        FROM tickets t
        JOIN routes r ON t.route_id = r.id
        WHERE t.status = 'CONFIRMED'
    ''').fetchone()
    total_revenue = revenue_res['total_rev'] or 0.0
    conn.close()

    return jsonify({
        "stats": {
            "total_users": total_users,
            "total_routes": total_routes,
            "total_tickets": total_tickets,
            "total_revenue": total_revenue
        }
    }), 200

@app.route('/api/admin/analytics', methods=['GET'])
@token_required
@admin_required
def get_admin_analytics(current_user):
    """
    Returns chart data: 7-day revenue, pass type distribution, route occupancy.
    """
    conn = get_db_connection()

    # 1. Pass type breakdown
    pass_types = conn.execute('''
        SELECT COALESCE(pass_type, 'single') as pass_type, COUNT(*) as count,
               SUM(COALESCE(amount_paid, 0)) as revenue
        FROM tickets
        WHERE status = 'CONFIRMED'
        GROUP BY COALESCE(pass_type, 'single')
    ''').fetchall()

    # 2. Route occupancy & bookings
    route_stats = conn.execute('''
        SELECT r.source || ' ➔ ' || r.destination as route_name,
               COUNT(t.id) as bookings,
               ROUND(COUNT(t.id) * 100.0 / 40.0, 1) as occupancy_pct,
               SUM(COALESCE(t.amount_paid, r.price)) as revenue
        FROM routes r
        LEFT JOIN tickets t ON r.id = t.route_id AND t.status = 'CONFIRMED'
        GROUP BY r.id
        ORDER BY bookings DESC
        LIMIT 6
    ''').fetchall()

    # 3. Last 7 days trend
    daily_stats = conn.execute('''
        SELECT DATE(booked_at) as booking_date,
               COUNT(*) as count,
               SUM(COALESCE(amount_paid, 0)) as daily_revenue
        FROM tickets
        WHERE status = 'CONFIRMED'
        GROUP BY DATE(booked_at)
        ORDER BY booking_date DESC
        LIMIT 7
    ''').fetchall()

    conn.close()

    return jsonify({
        "pass_breakdown": [dict(p) for p in pass_types],
        "route_occupancy": [dict(r) for r in route_stats],
        "daily_trends": [dict(d) for d in daily_stats]
    }), 200

# ----------------- Passenger Helpdesk & Support Messaging API -----------------

@app.route('/api/support/my-messages', methods=['GET'])
@token_required
def get_user_support_messages(current_user):
    """
    Returns all support messages and admin replies for the current user.
    """
    conn = get_db_connection()
    messages = conn.execute('''
        SELECT sm.*, u.name as user_name, u.email as user_email
        FROM support_messages sm
        JOIN users u ON sm.user_id = u.id
        WHERE sm.user_id = ?
        ORDER BY sm.created_at ASC
    ''', (current_user['id'],)).fetchall()
    conn.close()

    return jsonify({"messages": [dict(m) for m in messages]}), 200

@app.route('/api/support/send', methods=['POST'])
@token_required
def send_support_message(current_user):
    """
    User sends a query or question to transit support team.
    """
    data = request.get_json() or {}
    message_text = data.get('message', '').strip()
    subject = data.get('subject', 'General Inquiry').strip()

    if not message_text:
        return jsonify({"error": "Message content cannot be empty"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO support_messages (user_id, sender_role, subject, message, status)
        VALUES (?, 'user', ?, ?, 'OPEN')
    ''', (current_user['id'], subject, message_text))
    msg_id = cursor.lastrowid
    conn.commit()

    new_msg = cursor.execute('''
        SELECT sm.*, u.name as user_name, u.email as user_email
        FROM support_messages sm
        JOIN users u ON sm.user_id = u.id
        WHERE sm.id = ?
    ''', (msg_id,)).fetchone()
    conn.close()

    return jsonify({
        "message": "Inquiry sent successfully to transit support desk",
        "data": dict(new_msg)
    }), 201

@app.route('/api/admin/support/all', methods=['GET'])
@token_required
@admin_required
def get_all_support_queries(current_user):
    """
    Admin fetches all incoming passenger queries and conversations.
    """
    conn = get_db_connection()
    messages = conn.execute('''
        SELECT sm.*, u.name as user_name, u.email as user_email
        FROM support_messages sm
        JOIN users u ON sm.user_id = u.id
        ORDER BY sm.created_at DESC
    ''').fetchall()
    conn.close()

    return jsonify({"queries": [dict(m) for m in messages]}), 200

@app.route('/api/admin/support/reply', methods=['POST'])
@token_required
@admin_required
def admin_reply_support(current_user):
    """
    Admin replies to a passenger's inquiry.
    """
    data = request.get_json() or {}
    target_user_id = data.get('user_id')
    reply_text = data.get('message', '').strip()
    subject = data.get('subject', 'Support Team Response').strip()

    if not target_user_id or not reply_text:
        return jsonify({"error": "Target user_id and message are required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check user exists
    user_exists = cursor.execute('SELECT id, name FROM users WHERE id = ?', (target_user_id,)).fetchone()
    if not user_exists:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    cursor.execute('''
        INSERT INTO support_messages (user_id, sender_role, subject, message, status)
        VALUES (?, 'admin', ?, ?, 'RESOLVED')
    ''', (target_user_id, subject, reply_text))
    
    # Also update previous user inquiries for this user to RESOLVED
    cursor.execute('''
        UPDATE support_messages
        SET status = 'RESOLVED'
        WHERE user_id = ? AND sender_role = 'user' AND status = 'OPEN'
    ''', (target_user_id,))
    
    msg_id = cursor.lastrowid
    conn.commit()

    reply_row = cursor.execute('''
        SELECT sm.*, u.name as user_name, u.email as user_email
        FROM support_messages sm
        JOIN users u ON sm.user_id = u.id
        WHERE sm.id = ?
    ''', (msg_id,)).fetchone()
    conn.close()

    return jsonify({
        "message": f"Reply successfully sent to passenger {user_exists['name']}",
        "data": dict(reply_row)
    }), 201

@app.route('/api/admin/support/<int:msg_id>/resolve', methods=['PUT'])
@token_required
@admin_required
def resolve_support_query(current_user, msg_id):
    """
    Mark an inquiry as resolved.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE support_messages SET status = "RESOLVED" WHERE id = ?', (msg_id,))
    conn.commit()
    conn.close()

    return jsonify({"message": "Query marked as resolved"}), 200

# ----------------- Server Bootstrap -----------------

if __name__ == '__main__':
    init_db()
    port = int(os.getenv('PORT', 5000))
    print(f"🚌 CloudBus Flask API server starting on port {port}...")
    app.run(host='0.0.0.0', port=port, threaded=True, debug=True)
