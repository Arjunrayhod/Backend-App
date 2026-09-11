import sqlite3
import os
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), 'buspass.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA foreign_keys=ON;')
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create routes table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            destination TEXT NOT NULL,
            distance_km REAL NOT NULL,
            price REAL NOT NULL,
            departure_time TEXT NOT NULL
        )
    ''')

    # Create tickets table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            route_id INTEGER NOT NULL,
            travel_date TEXT NOT NULL,
            seat_number INTEGER NOT NULL,
            pass_type TEXT DEFAULT 'single',
            valid_until TEXT,
            student_id_number TEXT,
            amount_paid REAL,
            is_boarded INTEGER DEFAULT 0,
            qr_filename TEXT,
            pdf_filename TEXT,
            status TEXT DEFAULT 'CONFIRMED',
            booked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (route_id) REFERENCES routes (id) ON DELETE CASCADE
        )
    ''')

    # Create support_messages table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            sender_role TEXT NOT NULL DEFAULT 'user',
            subject TEXT,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'OPEN',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    ''')

    # Safe column migrations if database already existed
    cursor.execute("PRAGMA table_info(tickets)")
    existing_cols = [col['name'] for col in cursor.fetchall()]
    new_cols = [
        ('pass_type', "TEXT DEFAULT 'single'"),
        ('valid_until', "TEXT"),
        ('student_id_number', "TEXT"),
        ('amount_paid', "REAL"),
        ('is_boarded', "INTEGER DEFAULT 0")
    ]
    for col_name, col_def in new_cols:
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE tickets ADD COLUMN {col_name} {col_def}")

    # Seed Admin account if not present
    cursor.execute('SELECT id FROM users WHERE email = ?', ('admin@buspass.com',))
    admin_user = cursor.fetchone()
    if not admin_user:
        hashed_pw = generate_password_hash('Admin@123')
        cursor.execute('''
            INSERT INTO users (name, email, password_hash, role)
            VALUES (?, ?, ?, ?)
        ''', ('System Administrator', 'admin@buspass.com', hashed_pw, 'admin'))
        print("Default admin created: admin@buspass.com / Admin@123")

    # Seed Demo passenger user if not present
    cursor.execute('SELECT id FROM users WHERE email = ?', ('user@buspass.com',))
    demo_user = cursor.fetchone()
    if not demo_user:
        hashed_pw = generate_password_hash('User@123')
        cursor.execute('''
            INSERT INTO users (name, email, password_hash, role)
            VALUES (?, ?, ?, ?)
        ''', ('Rahul Sharma', 'user@buspass.com', hashed_pw, 'user'))
        print("Demo user created: user@buspass.com / User@123")

    # Seed Sample Routes if empty
    cursor.execute('SELECT COUNT(*) as count FROM routes')
    route_count = cursor.fetchone()['count']
    if route_count == 0:
        sample_routes = [
            ('Delhi', 'Jaipur', 280.0, 450.0, '06:00 AM'),
            ('Mumbai', 'Pune', 150.0, 300.0, '07:30 AM'),
            ('Bengaluru', 'Mysore', 145.0, 250.0, '08:00 AM'),
            ('Hyderabad', 'Vijayawada', 275.0, 400.0, '09:15 AM'),
            ('Chennai', 'Pondicherry', 150.0, 220.0, '10:00 AM'),
            ('Kolkata', 'Durgapur', 170.0, 280.0, '06:45 AM'),
            ('Ahmedabad', 'Surat', 260.0, 380.0, '07:00 AM'),
            ('Chandigarh', 'Shimla', 115.0, 350.0, '08:30 AM')
        ]
        cursor.executemany('''
            INSERT INTO routes (source, destination, distance_km, price, departure_time)
            VALUES (?, ?, ?, ?, ?)
        ''', sample_routes)
        print(f"Seeded {len(sample_routes)} default bus routes.")

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")
