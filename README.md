# Smart EV Parking Management

A Flask + MySQL web app for managing a hybrid parking lot with EV charging bays. It tracks parking sessions, charging progress, a waitlist for charger bays, automatic billing, and user notifications.

## Features

- **Dashboard** – live bay status (free / occupied / held) with charging progress
- **Parking** – vehicle entry and exit; exit generates an invoice
- **Charging** – start sessions, update kWh / battery %, and mark charging complete
- **Waitlist** – EV owners queue for charger bays and get notified when one frees up
- **Invoices** – itemised parking, energy, and idle fees
- **Notifications** – message log per user

Business rules (validation, billing, waitlist promotion) live in the database as triggers and stored procedures (`end_parking`, `complete_charging`). Trigger errors are shown in the UI as flash messages.

## Tech Stack

Python, Flask, MySQL (`mysql-connector-python`), Jinja2 templates, plain CSS

## Project Structure

```
├── app.py            # Flask routes and DB helpers
├── requirements.txt
├── static/style.css
└── templates/        # dashboard, parking, charging, waitlist, invoices, notifications
```

## Setup

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
2. **Create the database** – set up a MySQL database named `ev_parking` using your SQL schema scripts (tables, triggers, and the `end_parking` / `complete_charging` procedures).
3. **Configure credentials** – edit `DB_CONFIG` in `app.py` (host, user, password) and change `app.secret_key`.
4. **Run**
   ```bash
   python app.py
   ```
   Open http://127.0.0.1:5000

## Database Tables Used

`users`, `vehicles`, `parking_bays`, `ev_chargers`, `parking_sessions`, `charging_sessions`, `slot_waitlist`, `billing_invoices`, `notifications`
