
import sqlite3
from pathlib import Path
from datetime import date, datetime


# ================= DATABASE PATH =================

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = INSTANCE_DIR / "ecoshare.db"


# ================= DATABASE CONNECTION =================

def get_connection():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# ================= INITIALIZE DATABASE =================

def init_db():
    with get_connection() as conn:

        # Donations table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS donations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                food_name TEXT NOT NULL,
                quantity TEXT NOT NULL,
                location TEXT NOT NULL,
                donor_name TEXT NOT NULL,
                contact TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Available',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expiry_date TEXT
            )
        """)

        # Safely add missing columns to an existing database
        donation_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(donations)"
            ).fetchall()
        }

        if "expiry_date" not in donation_columns:
            conn.execute("""
                ALTER TABLE donations
                ADD COLUMN expiry_date TEXT
            """)

        if "status" not in donation_columns:
            conn.execute("""
                ALTER TABLE donations
                ADD COLUMN status TEXT NOT NULL DEFAULT 'Available'
            """)

        # Users table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'donor',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()


# ================= REGISTER USER =================

def register_user(full_name, email, password_hash, role="donor"):
    full_name = (full_name or "").strip()
    email = (email or "").strip().lower()
    role = (role or "donor").strip().lower()

    if not full_name or not email or not password_hash:
        return False

    if role not in ("donor", "ngo"):
        return False

    try:
        with get_connection() as conn:
            conn.execute("""
                INSERT INTO users (
                    full_name,
                    email,
                    password_hash,
                    role
                )
                VALUES (?, ?, ?, ?)
            """, (
                full_name,
                email,
                password_hash,
                role
            ))

            conn.commit()
            return True

    except sqlite3.IntegrityError:
        return False


# ================= FIND USER BY EMAIL =================

def get_user_by_email(email):
    email = (email or "").strip().lower()

    with get_connection() as conn:
        row = conn.execute("""
            SELECT *
            FROM users
            WHERE email = ?
        """, (email,)).fetchone()

        return dict(row) if row else None


# ================= GET USER BY ID =================

def get_user_by_id(user_id):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT id, full_name, email, role, created_at
            FROM users
            WHERE id = ?
        """, (user_id,)).fetchone()

        return dict(row) if row else None


# ================= GET ALL DONATIONS =================

def get_all_donations():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT *
            FROM donations
            ORDER BY id DESC
        """).fetchall()

        return [dict(row) for row in rows]


# ================= GET ONE DONATION =================

def get_donation_by_id(donation_id):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT *
            FROM donations
            WHERE id = ?
        """, (donation_id,)).fetchone()

        return dict(row) if row else None


# ================= ADD DONATION =================

def add_donation(
    food_name,
    quantity,
    location,
    donor_name,
    contact,
    expiry_date=""
):
    food_name = (food_name or "").strip()
    quantity = (quantity or "").strip()
    location = (location or "").strip()
    donor_name = (donor_name or "").strip()
    contact = (contact or "").strip()
    expiry_date = (expiry_date or "").strip()

    if not all([
        food_name,
        quantity,
        location,
        donor_name,
        contact
    ]):
        raise ValueError("Please provide all required donation details.")

    if expiry_date:
        try:
            expiry_day = date.fromisoformat(expiry_date)
        except ValueError:
            raise ValueError("Expiry date must use YYYY-MM-DD format.")

        if expiry_day < date.today():
            raise ValueError("Expiry date cannot be in the past.")

    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO donations (
                food_name,
                quantity,
                location,
                donor_name,
                contact,
                status,
                expiry_date
            )
            VALUES (?, ?, ?, ?, ?, 'Available', ?)
        """, (
            food_name,
            quantity,
            location,
            donor_name,
            contact,
            expiry_date or None
        ))

        conn.commit()
        return cursor.lastrowid


# ================= CLAIM DONATION =================

def claim_donation(donation_id):
    today = date.today().isoformat()

    with get_connection() as conn:
        # Claim only available, non-expired donations.
        cursor = conn.execute("""
            UPDATE donations
            SET status = 'Claimed'
            WHERE id = ?
              AND LOWER(TRIM(status)) = 'available'
              AND (
                    expiry_date IS NULL
                    OR TRIM(expiry_date) = ''
                    OR expiry_date >= ?
              )
        """, (donation_id, today))

        conn.commit()
        return cursor.rowcount > 0


# ================= DASHBOARD STATISTICS =================

def get_statistics():
    with get_connection() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total,

                SUM(
                    CASE
                        WHEN LOWER(TRIM(status)) = 'available'
                        THEN 1 ELSE 0
                    END
                ) AS available,

                SUM(
                    CASE
                        WHEN LOWER(TRIM(status)) = 'claimed'
                        THEN 1 ELSE 0
                    END
                ) AS claimed

            FROM donations
        """).fetchone()

        return {
            "total": row["total"] or 0,
            "available": row["available"] or 0,
            "claimed": row["claimed"] or 0
        }


# ================= SMART FOOD MATCHING =================

def find_smart_matches(food="", location=""):
    food = (food or "").strip().casefold()
    location = (location or "").strip().casefold()
    today = date.today()

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT *
            FROM donations
            WHERE LOWER(TRIM(status)) = 'available'
            ORDER BY id DESC
        """).fetchall()

    matches = []

    for row in rows:
        donation = dict(row)

        expiry = donation.get("expiry_date")
        donation["expiry_status"] = "Not provided"
        donation["days_until_expiry"] = None
        donation["priority"] = "Normal"
        donation["priority_score"] = 0

        # -------- EXPIRY CHECK --------

        if expiry:
            try:
                expiry_day = datetime.strptime(
                    str(expiry)[:10], "%Y-%m-%d"
                ).date()

                days_left = (expiry_day - today).days
                donation["days_until_expiry"] = days_left

                if days_left < 0:
                    donation["expiry_status"] = "Expired"
                    continue

                elif days_left == 0:
                    donation["expiry_status"] = "Expires today"
                    donation["priority"] = "Urgent"
                    donation["priority_score"] = 50

                elif days_left <= 2:
                    donation["expiry_status"] = "Expiring soon"
                    donation["priority"] = "High"
                    donation["priority_score"] = 35

                elif days_left <= 5:
                    donation["expiry_status"] = "Within date"
                    donation["priority"] = "Medium"
                    donation["priority_score"] = 20

                else:
                    donation["expiry_status"] = "Within date"
                    donation["priority"] = "Normal"
                    donation["priority_score"] = 0

            except (ValueError, TypeError):
                donation["expiry_status"] = "Invalid date"
                continue

        # -------- FOOD MATCHING --------

        food_name = (
            donation.get("food_name") or ""
        ).strip().casefold()

        donation_location = (
            donation.get("location") or ""
        ).strip().casefold()

        score = 0
        reasons = []

        if food:
            if food == food_name:
                score += 40
                reasons.append("Exact food name match")

            elif food in food_name or food_name in food:
                score += 30
                reasons.append("Food name partially matches")

            else:
                matching_words = [
                    word for word in food.split()
                    if len(word) > 2 and word in food_name
                ]

                if matching_words:
                    score += 15
                    reasons.append("Some food keywords match")
                else:
                    continue

        # -------- LOCATION MATCHING --------

        if location:
            if location == donation_location:
                score += 60
                reasons.append("Exact location match")

            elif (
                location in donation_location
                or donation_location in location
            ):
                score += 40
                reasons.append("Location partially matches")

            else:
                continue

        if not food and not location:
            reasons.append("No filters applied")

        # -------- EXPIRY PRIORITY BONUS --------

        if donation["priority_score"] > 0:
            score += donation["priority_score"]
            reasons.append(
                "Priority: "
                + donation["priority"]
                + " - "
                + donation["expiry_status"]
            )

        donation["match_score"] = min(score, 100)
        donation["match_reasons"] = reasons

        matches.append(donation)

    # Sort urgent and high-priority food first.
    matches.sort(
        key=lambda item: (
            item["priority_score"],
            item["match_score"],
            item["id"]
        ),
        reverse=True
    )

    return matches


# ================= EXPIRY SUMMARY =================

def get_expiry_summary():
    today = date.today()

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT id, food_name, quantity, location, expiry_date, status
            FROM donations
            WHERE LOWER(TRIM(status)) = 'available'
              AND expiry_date IS NOT NULL
              AND TRIM(expiry_date) != ''
            ORDER BY expiry_date ASC
        """).fetchall()

    summary = []

    for row in rows:
        donation = dict(row)

        try:
            expiry_day = datetime.strptime(
                str(donation["expiry_date"])[:10],
                "%Y-%m-%d"
            ).date()
        except (ValueError, TypeError):
            donation["expiry_status"] = "Invalid date"
            donation["days_until_expiry"] = None
            continue

        days_left = (expiry_day - today).days
        donation["days_until_expiry"] = days_left

        if days_left < 0:
            donation["expiry_status"] = "Expired"
        elif days_left == 0:
            donation["expiry_status"] = "Expires today"
        elif days_left <= 2:
            donation["expiry_status"] = "Expiring soon"
        else:
            donation["expiry_status"] = "Within date"

        summary.append(donation)

    return summary


# ================= TEST ENTRY POINT =================

if __name__ == "__main__":
    init_db()
    print("EcoShare AI database initialized successfully.")
    print("Database location:", DB_PATH)
