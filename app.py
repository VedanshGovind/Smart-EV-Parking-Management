# EV Charging & Hybrid Parking - simple Flask front end
# Talks to the MySQL database "ev_parking" created by the SQL scripts.

from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
import mysql.connector

app = Flask(__name__)
app.secret_key = "change-this-secret"

# ---- change these to match your MySQL setup ----
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "Workbench Password",
    "database": "ev_parking",
}


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
    Errors from triggers (SIGNAL) come back as mysql.connector.Error
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


def read_time(text):
    """Time from the form (datetime-local). If empty use the current time."""
    if text:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M")
    return datetime.now().replace(microsecond=0)


def show_result(ok, error, success_message):
    if ok:
        flash(success_message, "ok")
    else:
        flash("Rejected by database: " + error, "error")


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
    return render_template("dashboard.html", bays=bays, counts=counts, waiting=waiting)


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
        action = request.form["action"]
        if action == "start":
            # find the charger installed in the bay where the car is parked
            rows = run_query("""
                SELECT e.charger_id FROM parking_sessions p
                JOIN ev_chargers e ON e.bay_id = p.bay_id
                WHERE p.parking_id = %s""", (request.form["parking_id"],))
            if not rows:
                flash("This bay has no charger.", "error")
            else:
                ok, err = run_action(
                    "INSERT INTO charging_sessions (parking_id, charger_id, start_time) VALUES (%s, %s, %s)",
                    (request.form["parking_id"], rows[0]["charger_id"], read_time(request.form.get("time"))))
                show_result(ok, err, "Charging started.")
        elif action == "update":
            ok, err = run_action(
                "UPDATE charging_sessions SET energy_kwh = %s, charge_percent = %s "
                "WHERE charging_id = %s AND status = 'CHARGING'",
                (request.form["energy"], request.form["percent"], request.form["charging_id"]))
            show_result(ok, err, "Charging progress updated.")
        else:  # battery reached 100%
            ok, err = run_action(
                "UPDATE charging_sessions SET energy_kwh = %s WHERE charging_id = %s",
                (request.form["energy"], request.form["charging_id"]))
            if ok:
                ok, err = run_action(None, (request.form["charging_id"], read_time(request.form.get("time"))),
                                     proc="complete_charging")
            show_result(ok, err, "Charging complete. Waitlist checked and users notified.")
        return redirect(url_for("charging"))

    parked = run_query("""
        SELECT p.parking_id, v.plate_no, v.model, v.connector_type, b.bay_name
        FROM parking_sessions p
        JOIN vehicles v ON v.vehicle_id = p.vehicle_id
        JOIN parking_bays b ON b.bay_id = p.bay_id
        WHERE p.exit_time IS NULL
        ORDER BY b.bay_name
    """)
    active = run_query("""
        SELECT c.charging_id, v.plate_no, v.model, b.bay_name, e.connector_type,
               c.start_time, c.energy_kwh, c.charge_percent, c.status
        FROM charging_sessions c
        JOIN parking_sessions p ON p.parking_id = c.parking_id
        JOIN vehicles v ON v.vehicle_id = p.vehicle_id
        JOIN parking_bays b ON b.bay_id = p.bay_id
        JOIN ev_chargers e ON e.charger_id = c.charger_id
        WHERE p.exit_time IS NULL
        ORDER BY c.start_time
    """)
    return render_template("charging.html", parked=parked, active=active)


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
    return render_template("invoices.html", invoices=rows)


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
