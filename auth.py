# auth.py
import sqlite3
from pathlib import Path
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session
)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "users.db"

auth_bp = Blueprint("auth", __name__, template_folder="templates")


def init_db():
    """Create users.db and users table if missing."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def get_db_conn():
    return sqlite3.connect(DB_PATH)


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not name or not email or not password:
            flash("Please fill all required fields.", "warning")
            return redirect(url_for("auth.signup"))

        if password != confirm:
            flash("Passwords do not match.", "warning")
            return redirect(url_for("auth.signup"))

        pw_hash = generate_password_hash(password)

        try:
            conn = get_db_conn()
            c = conn.cursor()
            c.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, pw_hash),
            )
            conn.commit()
            conn.close()
            flash("Account created. You can now log in.", "success")
            return redirect(url_for("auth.login"))
        except:
            flash("An account with that email already exists.", "danger")
            return redirect(url_for("auth.signup"))

    return render_template("signup.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "on"

        if not email or not password:
            flash("Please provide email and password.", "warning")
            return redirect(url_for("auth.login"))

        conn = get_db_conn()
        c = conn.cursor()
        c.execute("SELECT id, name, password_hash FROM users WHERE email = ?", (email,))
        row = c.fetchone()
        conn.close()

        if not row:
            flash("Invalid email or password.", "danger")
            return redirect(url_for("auth.login"))

        user_id, name, pw_hash = row

        if not check_password_hash(pw_hash, password):
            flash("Invalid email or password.", "danger")
            return redirect(url_for("auth.login"))

        session["user_id"] = user_id
        session["user_name"] = name
        session["user_email"] = email
        session.permanent = remember  # remember me

        flash(f"Welcome back, {name}!", "success")
        next_url = request.args.get("next")
        return redirect(next_url or url_for("index"))

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))
