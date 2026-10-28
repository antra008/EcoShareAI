
from datetime import date
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)

from werkzeug.security import generate_password_hash, check_password_hash

from database import (
    init_db,
    get_all_donations,
    add_donation,
    claim_donation,
    get_statistics,
    find_smart_matches,
    register_user,
    get_user_by_email,
)


# ---------------- APP CONFIGURATION ----------------

app = Flask(__name__)
app.secret_key = "ecoshare-demo-secret-key"

init_db()


# ---------------- HELPER FUNCTIONS ----------------

def get_stat_value(stats, *possible_keys):
    """Read a statistic using one of the supported dictionary keys."""
    for key in possible_keys:
        try:
            value = stats.get(key)
            if value is not None:
                return value
        except AttributeError:
            break

    return 0


def get_user_value(user, *possible_keys):
    """Read a user field from a dictionary or sqlite3.Row."""
    for key in possible_keys:
        try:
            value = user[key]
            if value is not None:
                return value
        except (KeyError, IndexError, TypeError):
            continue

    return None


# ---------------- ACCESS CONTROL ----------------

def login_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in first.", "error")
            return redirect(url_for("login"))

        return view_function(*args, **kwargs)

    return wrapped_view


def donor_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in first.", "error")
            return redirect(url_for("login"))

        if session.get("user_role") != "donor":
            flash("Only donor accounts can donate food.", "error")
            return redirect(url_for("home"))

        return view_function(*args, **kwargs)

    return wrapped_view


def ngo_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in first.", "error")
            return redirect(url_for("login"))

        if session.get("user_role") != "ngo":
            flash("Only NGO accounts can access this feature.", "error")
            return redirect(url_for("home"))

        return view_function(*args, **kwargs)

    return wrapped_view


# ---------------- HOME PAGE ----------------

@app.route("/")
def home():
    donations = get_all_donations()
    stats = get_statistics() or {}

    total = get_stat_value(
        stats, "total", "total_donations"
    )
    available = get_stat_value(
        stats, "available", "available_donations"
    )
    claimed = get_stat_value(
        stats, "claimed", "claimed_donations"
    )

    # Ensure common keys are available to the homepage template.
    stats_for_template = dict(stats)
    stats_for_template["total"] = total
    stats_for_template["available"] = available
    stats_for_template["claimed"] = claimed

    return render_template(
        "index.html",
        donations=donations,
        stats=stats_for_template,
        total_donations=total,
        available_donations=available,
        claimed_donations=claimed,
    )


# ---------------- REGISTER ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("home"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        role = request.form.get("role", "").strip().lower()

        if not full_name or not email or not password:
            flash("Please fill in all required fields.", "error")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html")

        if role not in ("donor", "ngo"):
            flash("Please select a valid account role.", "error")
            return render_template("register.html")

        try:
            existing_user = get_user_by_email(email)

            if existing_user:
                flash(
                    "This email is already registered. Please log in.",
                    "error",
                )
                return render_template("register.html")

            password_hash = generate_password_hash(password)

            register_user(
                full_name,
                email,
                password_hash,
                role,
            )

            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))

        except Exception:
            app.logger.exception("Registration failed")
            flash(
                "Registration failed. Please check database.py "
                "and the database table fields.",
                "error",
            )

    return render_template("register.html")


# ---------------- LOGIN ----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        try:
            user = get_user_by_email(email)
        except Exception:
            app.logger.exception("Could not retrieve user")
            flash("Login failed because of a database error.", "error")
            return render_template("login.html")

        if not user:
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        user_id = get_user_value(user, "id", "user_id")
        stored_hash = get_user_value(
            user, "password_hash", "password"
        )
        user_name = get_user_value(
            user, "full_name", "name", "username", "first_name"
        )
        user_role = get_user_value(user, "role", "user_role")

        if not user_id or not stored_hash or not user_role:
            app.logger.error(
                "User record is missing required login fields."
            )
            flash(
                "User database fields do not match the application.",
                "error",
            )
            return render_template("login.html")

        try:
            password_is_valid = check_password_hash(
                stored_hash, password
            )
        except (ValueError, TypeError):
            password_is_valid = False

        if not password_is_valid:
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        if user_role not in ("donor", "ngo"):
            flash("This account has an invalid role.", "error")
            return render_template("login.html")

        session.clear()
        session["user_id"] = user_id
        session["user_name"] = user_name or "User"
        session["user_role"] = user_role

        flash("Login successful!", "success")
        return redirect(url_for("home"))

    return render_template("login.html")


# ---------------- LOGOUT ----------------

@app.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))


# ---------------- DONATE FOOD ----------------

@app.route("/donate", methods=["GET", "POST"])
@donor_required
def donate():
    if request.method == "POST":
        food_name = request.form.get("food_name", "").strip()
        quantity = request.form.get("quantity", "").strip()
        location = request.form.get("location", "").strip()
        donor_name = request.form.get("donor_name", "").strip()
        contact = request.form.get("contact", "").strip()
        expiry_date = request.form.get("expiry_date", "").strip()

        if not all([
            food_name,
            quantity,
            location,
            donor_name,
            contact,
        ]):
            flash("Please fill in all required fields.", "error")
            return render_template("donate.html")

        if expiry_date:
            try:
                parsed_expiry = date.fromisoformat(expiry_date)
            except ValueError:
                flash("Please enter a valid expiry date.", "error")
                return render_template("donate.html")

            if parsed_expiry < date.today():
                flash("Expiry date cannot be in the past.", "error")
                return render_template("donate.html")

        try:
            # Keep this call compatible with the existing database.py.
            # The current database function may accept five arguments.
            add_donation(
                food_name,
                quantity,
                location,
                donor_name,
                contact,
            )

            flash("Food donation added successfully!", "success")
            return redirect(url_for("donations"))

        except Exception:
            app.logger.exception("Could not add donation")
            flash(
                "Could not save the donation. Check database.py "
                "and the donation table fields.",
                "error",
            )

    return render_template("donate.html")


# ---------------- AVAILABLE DONATIONS ----------------

@app.route("/donations")
def donations():
    all_donations = get_all_donations()

    return render_template(
        "donations.html",
        donations=all_donations,
    )


# ---------------- CLAIM DONATION ----------------

@app.route("/claim/<int:donation_id>", methods=["POST"])
@ngo_required
def claim_donation_route(donation_id):
    try:
        all_donations = get_all_donations()
        selected_donation = None

        for donation in all_donations:
            if int(donation["id"]) == donation_id:
                selected_donation = donation
                break

        if selected_donation is None:
            flash("Donation not found.", "error")
            return redirect(url_for("donations"))

        if selected_donation["status"] != "Available":
            flash("This donation is no longer available.", "error")
            return redirect(url_for("donations"))

        # Check expiry only if the existing database exposes this field.
        try:
            expiry_value = selected_donation["expiry_date"]
        except (KeyError, IndexError, TypeError):
            expiry_value = None

        if expiry_value:
            try:
                expiry = date.fromisoformat(str(expiry_value)[:10])

                if expiry < date.today():
                    flash("This food donation has expired.", "error")
                    return redirect(url_for("donations"))

            except ValueError:
                app.logger.warning(
                    "Invalid expiry date for donation %s", donation_id
                )

        claim_donation(donation_id)

        flash("Donation claimed successfully!", "success")

    except Exception:
        app.logger.exception("Could not claim donation")
        flash(
            "Could not claim this donation. Please try again.",
            "error",
        )

    return redirect(url_for("donations"))


# ---------------- NGO DASHBOARD ----------------

@app.route("/ngo-dashboard")
@ngo_required
def ngo_dashboard():
    stats = get_statistics() or {}
    donations = get_all_donations()

    total_donations = get_stat_value(
        stats, "total", "total_donations"
    )
    available_donations = get_stat_value(
        stats, "available", "available_donations"
    )
    claimed_donations = get_stat_value(
        stats, "claimed", "claimed_donations"
    )

    return render_template(
        "ngo-dashboard.html",
        stats=stats,
        donations=donations,
        total_donations=total_donations,
        available_donations=available_donations,
        claimed_donations=claimed_donations,
    )


# ---------------- SMART MATCHING ----------------

@app.route("/smart-matching")
def smart_matching():
    try:
        matches = find_smart_matches()
    except Exception:
        app.logger.exception("Smart matching failed")
        matches = []

    return render_template(
        "matching.html",
        matches=matches,
    )


# ---------------- HEALTH CHECK ----------------

@app.route("/health")
def health():
    return {
        "status": "ok",
        "application": "EcoShare AI",
    }


# ---------------- START APPLICATION ----------------

if __name__ == "__main__":
    app.run(debug=True)
