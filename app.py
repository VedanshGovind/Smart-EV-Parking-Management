# ChargePark - EV Charging & Hybrid Parking: Flask front end
# Talks to the MySQL database "ev_parking" created by the SQL scripts.

from datetime import datetime
from functools import wraps
import hmac

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, session)
import mysql.connector

app = Flask(__name__)
app.secret_key = "change-this-secret"

# ---- change these to match your MySQL setup ----
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "vedu",
    "database": "ev_parking",
}

# ---- admin login (fixed account for this project) ----
ADMIN_USER = "admin"
ADMIN_PASSWORD = "1234"


# ------------------------------------------------------------ database helpers
def get_db():
    return mysql.connector.connect(**DB_CONFIG)


def run_query(sql, params=None):
    """Run a SELECT and return all rows as dictionaries."""
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute(sql, params or ())
    rows = cur.fetchall()
    cur.close()
    db.close()
    return rows


def run_action(sql, params=None, proc=None):
    """Run an INSERT/UPDATE or call a stored procedure.
    Errors raised by triggers (SIGNAL) come back as mysql.connector.Error
    and are shown to the user as a message."""
    db = get_db()
    cur = db.cursor()
    try:
        if proc:
            cur.callproc(proc, params)
        else:
            cur.execute(sql, params or ())
        db.commit()
        return True, None
    except mysql.connector.Error as err:
        db.rollback()
        return False, err.msg
    finally:
        cur.close()
        db.close()


# ------------------------------------------------------------ small helpers
@app.template_filter("dt")
def format_datetime(value):
    """Show a datetime as 01 Nov 2026, 10:20"""
    if not value:
        return "-"
    return value.strftime("%d %b %Y, %H:%M")


@app.template_filter("tm")
def format_time(value):
    """Show only the time, e.g. 10:20"""
    if not value:
        return "-"
    return value.strftime("%H:%M")


@app.template_filter("money")
def format_money(value):
    return "\u20b9{:,.2f}".format(value or 0)


def read_time(text):
    """Time from the form (datetime-local). If empty use the current time."""
    if text:
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                pass
    return datetime.now().replace(microsecond=0)


def show_result(ok, error, success_message):
    if ok:
        flash(success_message, "ok")
    else:
        flash("Rejected by database: " + error, "error")


# ------------------------------------------------------------ login
@app.before_request
def require_login():
    """Everything except the login page and static files needs a login."""
    if request.endpoint in ("login", "static"):
        return None
    if not session.get("admin"):
        return redirect(url_for("login", next=request.path))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin"):
        return redirect(url_for("dashboard"))

    error = None
    if request.method == "POST":
        user = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user_ok = hmac.compare_digest(user, ADMIN_USER)
        pass_ok = hmac.compare_digest(password, ADMIN_PASSWORD)
        if user_ok and pass_ok:
            session["admin"] = True
            target = request.args.get("next", "")
            if target.startswith("/") and not target.startswith("//"):
                return redirect(target)
            return redirect(url_for("dashboard"))
        error = "Incorrect username or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------ dashboard
@app.route("/")
def dashboard():
    bays = run_query("""
        SELECT b.bay_id, b.bay_name, b.bay_type, b.status,
               e.connector_type, e.power_kw,
               p.parking_id, v.plate_no, v.model,
               c.charging_id, c.charge_percent, c.status AS charge_status
        FROM parking_bays b
        LEFT JOIN ev_chargers e ON e.bay_id = b.bay_id
        LEFT JOIN parking_sessions p ON p.bay_id = b.bay_id AND p.exit_time IS NULL
        LEFT JOIN vehicles v ON v.vehicle_id = p.vehicle_id
        LEFT JOIN charging_sessions c ON c.parking_id = p.parking_id
                                     AND c.status IN ('CHARGING', 'FULL')
        ORDER BY b.bay_id
    """)
    counts = run_query("""
        SELECT SUM(status = 'FREE') AS free_bays,
               SUM(status = 'OCCUPIED') AS occupied,
               SUM(status = 'HELD') AS held
        FROM parking_bays
    """)[0]
    waiting = run_query("SELECT COUNT(*) AS n FROM slot_waitlist WHERE status = 'WAITING'")[0]["n"]

    latest_invoices = run_query("""
        SELECT i.total, v.plate_no, b.bay_name, p.exit_time
        FROM billing_invoices i
        JOIN parking_sessions p ON p.parking_id = i.parking_id
        JOIN vehicles v ON v.vehicle_id = p.vehicle_id
        JOIN parking_bays b ON b.bay_id = p.bay_id
        ORDER BY i.invoice_id DESC LIMIT 4
    """)
    queue = run_query("""
        SELECT u.name, v.plate_no, v.model, v.connector_type, w.status, b.bay_name
        FROM slot_waitlist w
        JOIN users u ON u.user_id = w.user_id
        JOIN vehicles v ON v.vehicle_id = w.vehicle_id
        LEFT JOIN parking_bays b ON b.bay_id = w.bay_id
        WHERE w.status IN ('WAITING', 'NOTIFIED')
        ORDER BY w.joined_at LIMIT 4
    """)
    return render_template("dashboard.html", bays=bays, counts=counts, waiting=waiting,
                           latest_invoices=latest_invoices, queue=queue)


# ------------------------------------------------------------ parking
@app.route("/parking", methods=["GET", "POST"])
def parking():
    if request.method == "POST":
        action = request.form["action"]
        if action == "enter":
            ok, err = run_action(
                "INSERT INTO parking_sessions (vehicle_id, bay_id, entry_time) VALUES (%s, %s, %s)",
                (request.form["vehicle_id"], request.form["bay_id"], read_time(request.form.get("time"))))
            show_result(ok, err, "Vehicle parked.")
        else:
            ok, err = run_action(None, (request.form["parking_id"], read_time(request.form.get("time"))),
                                 proc="end_parking")
            show_result(ok, err, "Vehicle exited and invoice generated.")
        return redirect(url_for("parking"))

    vehicles = run_query("SELECT vehicle_id, plate_no, model, vehicle_type, connector_type FROM vehicles")
    bays = run_query("SELECT bay_id, bay_name, bay_type, status FROM parking_bays")
    open_sessions = run_query("""
        SELECT p.parking_id, v.plate_no, v.model, b.bay_name, p.entry_time
        FROM parking_sessions p
        JOIN vehicles v ON v.vehicle_id = p.vehicle_id
        JOIN parking_bays b ON b.bay_id = p.bay_id
        WHERE p.exit_time IS NULL
        ORDER BY p.entry_time
    """)
    return render_template("parking.html", vehicles=vehicles, bays=bays, open_sessions=open_sessions)


# ------------------------------------------------------------ charging
@app.route("/charging", methods=["GET", "POST"])
def charging():
    if request.method == "POST":
        action = request.form.get("action")
        when = read_time(request.form.get("time"))

        if action == "start":
            # the charger installed in the bay where the car is parked
            rows = run_query("""
                SELECT e.charger_id FROM parking_sessions p
                JOIN ev_chargers e ON e.bay_id = p.bay_id
                WHERE p.parking_id = %s""", (request.form["parking_id"],))
            if not rows:
                flash("This bay has no charger.", "error")
            else:
                ok, err = run_action(
                    "INSERT INTO charging_sessions (parking_id, charger_id, start_time) VALUES (%s, %s, %s)",
                    (request.form["parking_id"], rows[0]["charger_id"], when))
                show_result(ok, err, "Charging started.")

        elif action == "update":
            percent = request.form.get("percent", "").strip()
            if not percent.isdigit() or not 0 <= int(percent) <= 99:
                flash("Enter a charge level between 0 and 99, or use 'Mark as 100%'.", "error")
            else:
                ok, err = run_action(
                    "UPDATE charging_sessions SET energy_kwh = %s, charge_percent = %s "
                    "WHERE charging_id = %s AND status = 'CHARGING'",
                    (request.form["energy"], percent, request.form["charging_id"]))
                show_result(ok, err, "Progress saved.")

        elif action == "complete":
            ok, err = run_action(
                "UPDATE charging_sessions SET energy_kwh = %s WHERE charging_id = %s",
                (request.form["energy"], request.form["charging_id"]))
            if ok:
                ok, err = run_action(None, (request.form["charging_id"], when), proc="complete_charging")
            show_result(ok, err, "Battery marked as full. Waitlist checked and users notified.")

        return redirect(url_for("charging"))

    # one card per charger, with whatever is parked on it right now
    chargers = run_query("""
        SELECT e.charger_id, e.connector_type, e.power_kw,
               b.bay_id, b.bay_name, b.status AS bay_status,
               p.parking_id, p.entry_time, v.plate_no, v.model,
               c.charging_id, c.start_time, c.full_time, c.energy_kwh,
               c.charge_percent, c.status AS charge_status
        FROM ev_chargers e
        JOIN parking_bays b ON b.bay_id = e.bay_id
        LEFT JOIN parking_sessions p ON p.bay_id = b.bay_id AND p.exit_time IS NULL
        LEFT JOIN vehicles v ON v.vehicle_id = p.vehicle_id
        LEFT JOIN charging_sessions c ON c.parking_id = p.parking_id
                                     AND c.status IN ('CHARGING', 'FULL')
        ORDER BY b.bay_id
    """)
    summary = {"available": 0, "charging": 0, "full": 0}
    for c in chargers:
        if c["charge_status"] == "CHARGING":
            c["state"] = "charging"
        elif c["charge_status"] == "FULL":
            c["state"] = "full"
        elif c["parking_id"]:
            c["state"] = "parked"
        elif c["bay_status"] == "HELD":
            c["state"] = "held"
        else:
            c["state"] = "available"
        if c["state"] in ("available", "held"):
            summary["available"] += 1
        elif c["state"] in summary:
            summary[c["state"]] += 1

    history = run_query("""
        SELECT c.charging_id, v.plate_no, v.model, b.bay_name, e.connector_type,
               c.start_time, c.full_time, c.energy_kwh, c.charge_percent, c.status
        FROM charging_sessions c
        JOIN parking_sessions p ON p.parking_id = c.parking_id
        JOIN vehicles v ON v.vehicle_id = p.vehicle_id
        JOIN parking_bays b ON b.bay_id = p.bay_id
        JOIN ev_chargers e ON e.charger_id = c.charger_id
        ORDER BY c.start_time DESC, c.charging_id DESC
        LIMIT 12
    """)
    return render_template("charging.html", chargers=chargers, summary=summary, history=history)


# ------------------------------------------------------------ waitlist
@app.route("/waitlist", methods=["GET", "POST"])
def waitlist():
    if request.method == "POST":
        vehicle = run_query("SELECT user_id, connector_type FROM vehicles WHERE vehicle_id = %s",
                            (request.form["vehicle_id"],))[0]
        already = run_query("SELECT COUNT(*) AS n FROM slot_waitlist "
                            "WHERE vehicle_id = %s AND status IN ('WAITING', 'NOTIFIED')",
                            (request.form["vehicle_id"],))[0]["n"]
        if vehicle["connector_type"] is None:
            flash("Only EVs can join the waitlist.", "error")
        elif already > 0:
            flash("This vehicle is already on the waitlist.", "error")
        else:
            ok, err = run_action(
                "INSERT INTO slot_waitlist (user_id, vehicle_id, joined_at) VALUES (%s, %s, %s)",
                (vehicle["user_id"], request.form["vehicle_id"], read_time(request.form.get("time"))))
            show_result(ok, err, "Added to the waitlist.")
        return redirect(url_for("waitlist"))

    evs = run_query("SELECT vehicle_id, plate_no, model, connector_type FROM vehicles "
                    "WHERE vehicle_type = 'EV'")
    queue = run_query("""
        SELECT w.waitlist_id, u.name, v.plate_no, v.model, v.connector_type,
               w.joined_at, w.status, b.bay_name
        FROM slot_waitlist w
        JOIN users u ON u.user_id = w.user_id
        JOIN vehicles v ON v.vehicle_id = w.vehicle_id
        LEFT JOIN parking_bays b ON b.bay_id = w.bay_id
        ORDER BY w.joined_at
    """)
    return render_template("waitlist.html", evs=evs, queue=queue)


# ------------------------------------------------------------ invoices
@app.route("/invoices")
def invoices():
    rows = run_query("""
        SELECT i.invoice_id, u.name, v.plate_no, b.bay_name,
               p.entry_time, p.exit_time,
               i.parking_fee, i.energy_fee, i.idle_fee, i.total
        FROM billing_invoices i
        JOIN parking_sessions p ON p.parking_id = i.parking_id
        JOIN vehicles v ON v.vehicle_id = p.vehicle_id
        JOIN users u ON u.user_id = v.user_id
        JOIN parking_bays b ON b.bay_id = p.bay_id
        ORDER BY i.invoice_id DESC
    """)
    totals = run_query("""
        SELECT COUNT(*) AS n,
               COALESCE(SUM(total), 0) AS total,
               COALESCE(SUM(parking_fee), 0) AS parking,
               COALESCE(SUM(energy_fee), 0) AS energy,
               COALESCE(SUM(idle_fee), 0) AS idle
        FROM billing_invoices
    """)[0]
    return render_template("invoices.html", invoices=rows, totals=totals)


# ------------------------------------------------------------ notifications
@app.route("/notifications")
def notifications():
    rows = run_query("""
        SELECT n.created_at, u.name, n.message
        FROM notifications n JOIN users u ON u.user_id = n.user_id
        ORDER BY n.created_at DESC, n.notif_id DESC
    """)
    return render_template("notifications.html", notifications=rows)


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
