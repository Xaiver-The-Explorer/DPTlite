"""
app.py -- DPTlite (DNA Protein Toolbox, light version)
-------------------------------------------------------
This file is just routes. The actual science lives in biology.py; the database, auth, rate limiting, caching, and report/plot generation live
in helpers.py. That's the same app.py + helpers.py split CS50's own Finance problem set uses -- it just imports biology.py alongside it.

  biology.py  -> clean_sequence_data, detect_sequence_type, analyze_protein, ...
  helpers.py  -> login_required, api_key_required, rate_limit, run_full_analysis, get_db, init_db, render_*_figure, ...

IMPORTANT: These are bioinformatic heuristics, not lab-grade predictions. They do not replace TMHMM, PSIPRED, or IUPred.
"""

import os
import secrets
from datetime import datetime, timedelta

from flask import (
    Flask, render_template, request, jsonify, session, redirect,
    url_for, flash, g, make_response,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import HTTPException

from biology import clean_sequence_data
from helpers import (
    init_db, get_db, close_db, log_history, get_user_stats, clean_name, get_bookmarks,
    login_required, api_key_required, rate_limit,
    run_full_analysis, build_report_file,
    render_hydropathy_figure, render_charge_ph_figure, render_disorder_figure,
    MAX_SEQUENCE_LENGTH,
)

app = Flask(__name__)

# In a real deployment, set a long random SECRET_KEY as an environment variable instead of hard-coding one. This one is fine for CS50 final project.
app.secret_key = os.environ.get("DPTLITE_SECRET_KEY", "dev-secret-key-change-me")

# Basic request-size safety net (on top of the character-count check in helpers.py).
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB

app.teardown_appcontext(close_db)


# ========================================================
# Error Handling: always return JSON, never a stack trace.
# ========================================================

# Handle HTTP-level errors (e.g., 404, 405, 500) with JSON responses instead of HTML pages.
@app.errorhandler(HTTPException)

def handle_http_exception(err):
    # Customize responses for client-facing HTTP errors with description and status code.
    response = jsonify({"error": err.description, "code": err.code})
    response.status_code = err.code
    # Return JSON response instead of HTML for HTTP errors.
    return response


# Handle unexpected exceptions (e.g., programming errors) with a generic JSON response.
@app.errorhandler(Exception)

def handle_unexpected_exception(err):
    # Log the exception with traceback for debugging purposes.
    app.logger.exception("Unexpected error")
    # Return a user-friendly JSON error message.
    return jsonify({"error": "Something went wrong on the server. Please try again."}), 500


# ===================================
# Page Routes: render HTML templates.
# ===================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/donate")
def donate():
    return render_template("donate.html")


@app.route("/register", methods=["GET", "POST"])
@rate_limit(max_requests=10, window_seconds=60, json_response=False)

def register():

    if request.method == "POST":
        # Get register information (name, email, password, and confirmation) submitted by the user.
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirmation = request.form.get("confirmation", "")

        # Ensure all the input fields have been submitted.
        if not name or not email or not password:
            flash("Please fill in every field.", "error")
        # Ensure confirmation matches password.
        elif password != confirmation:
            flash("Passwords do not match.", "error")
        # Ensure password is long enough.
        elif len(password) < 6:
            flash("Password should be at least 6 characters.", "error")
        else:
            db = get_db()
            # Ensure no email duplicates in the database.
            if db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
                flash("An account with that email already exists.", "error")
            # Insert the new valid user into the database.
            else:
                db.execute(
                    "INSERT INTO users (name, email, hash, api_key, created_at) VALUES (?, ?, ?, ?, ?)",
                    (name, email, generate_password_hash(password), secrets.token_hex(24),
                     datetime.utcnow().isoformat(timespec="seconds")),
                )
                db.commit()
                # Provide a feedback to the new valid user.
                flash("Account created! You can log in now.", "success")
                # Redirect the new valid user to login page.
                return redirect(url_for("login"))

    # User reached route via GET instead of POST.
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
@rate_limit(max_requests=15, window_seconds=60, json_response=False)

def login():

    if request.method == "POST":
        # Get login information (email and password) submitted by the user.
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        # Query the database for the user's email.
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        # Ensure email exists in the database and password is correct.
        if user is None or not check_password_hash(user["hash"], password):
            flash("Invalid email or password.", "error")
        else:
            # Clear all session data.
            session.clear()
            # Add user_id and user_name to a new session.
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            # Provide a feedback to the logged-in user.
            flash(f"Welcome back, {user['name']}!", "success")
            # Redirect the logged-in user to analysis page.
            return redirect(url_for("analysis_page"))

    # User reached route via GET instead of POST.
    return render_template("login.html")


@app.route("/logout")
def logout():

    # Clear all session data.
    session.clear()
    # Provide a feedback to the logged-out user.
    flash("You've been logged out.", "success")
    # Redirect the logged-out user to home page.
    return redirect(url_for("index"))


@app.route("/analysis")
@login_required

def analysis_page():
    return render_template("analysis.html")


@app.route("/history")
@login_required

def history_page():

    # Calculate the cutoff date for entries within the last 30 days.
    cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat(timespec="seconds")

    # Query the database for the user's analysis history within the last 30 days, ordered by creation date descending.
    entries = get_db().execute(
        "SELECT * FROM history WHERE user_id = ? AND created_at >= ? ORDER BY created_at DESC",
        (session["user_id"], cutoff),
    ).fetchall()

    return render_template("history.html", entries=entries, bookmarks=get_bookmarks(session["user_id"]))


@app.route("/user")
@login_required

def user_page():

    uid = session["user_id"]

    # Query the database for the user's information.
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()

    return render_template("user.html", user=user, stats=get_user_stats(uid))


# ==================================================
# JSON API Routes: used by the front-end JavaScript.
# ==================================================

@app.route("/api/analyze", methods=["POST"])
@login_required
@rate_limit(max_requests=30, window_seconds=60)

def api_analyze():
    """Endpoint for front-end JavaScript: auth via session cookie."""

    # Get the JSON payload from the request, defaulting to an empty dictionary if parsing fails.
    payload = request.get_json(silent=True) or {}

    # Run the full analysis on the provided sequence, returning both the result and any error encountered.
    result, error = run_full_analysis(payload.get("sequence", ""))

    # If there was an error during analysis, return the error as a JSON response with the appropriate status code.
    if error:
        body, status = error
        return jsonify(body), status

    # Log the analysis result in the user's history for future reference.
    log_history(session["user_id"], result)

    return jsonify(result)


@app.route("/api/v1/analyze", methods=["POST"])
@api_key_required
@rate_limit(max_requests=60, window_seconds=60)

def api_v1_analyze():
    """Programmatic endpoint for advanced users: auth via X-API-Key header."""

    # Get the JSON payload from the request, defaulting to an empty dictionary if parsing fails.
    payload = request.get_json(silent=True) or {}

    # Run the full analysis on the provided sequence, returning both the result and any error encountered.
    result, error = run_full_analysis(payload.get("sequence", ""))

    # If there was an error during analysis, return the error as a JSON response with the appropriate status code.
    if error:
        body, status = error
        return jsonify(body), status

    # Log the analysis result in the user's history for future reference.
    log_history(g.api_user["id"], result)

    return jsonify(result)


@app.route("/api/plots", methods=["POST"])
@login_required
@rate_limit(max_requests=15, window_seconds=60)

def api_plots():

    payload = request.get_json(silent=True) or {}

    result, error = run_full_analysis(payload.get("sequence", ""))
    if error:
        body, status = error
        return jsonify(body), status

    # Extract the protein sequence from the analysis result to generate plots.
    protein = result["protein_analysis"]["sequence"]
    # If no protein sequence is available, return an error response indicating that plots cannot be generated.
    if not protein:
        return jsonify({"error": "No protein sequence available to plot."}), 400

    # Generate and return the plots for hydropathy, charge vs pH, and disorder based on the protein analysis results.
    return jsonify({
        "hydropathy": render_hydropathy_figure(result["protein_analysis"]["hydropathy_profile"]),
        "charge_ph": render_charge_ph_figure(protein),
        "disorder": render_disorder_figure(protein),
    })


@app.route("/api/report", methods=["POST"])
@login_required
@rate_limit(max_requests=15, window_seconds=60)

def api_report():
    """One route for every Export button: txt, json, pdf, fasta, or zip."""

    payload = request.get_json(silent=True) or {}

    result, error = run_full_analysis(payload.get("sequence", ""))
    if error:
        body, status = error
        return jsonify(body), status

    # Build the report file based on the analysis result and the requested format (defaulting to "txt" if not specified).
    body, mimetype, filename = build_report_file(result, payload.get("format", "txt"))

    # Create a Flask response object with the report content.
    response = make_response(body)
    # Set the Content-Type header to indicate the MIME type of the response (e.g., JSON or plain text).
    response.headers["Content-Type"] = mimetype
    # Suggest a filename for the downloaded report, prompting the browser to save it with the specified name.
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"

    return response


@app.route("/api/bookmarks", methods=["GET", "POST"])
@login_required

def api_bookmarks():

    db = get_db()

    if request.method == "POST":

        payload = request.get_json(silent=True) or {}

        # Clean the name from the request payload, ensuring it is in a valid format for bookmarking.
        name = clean_name(payload.get("name"))
        # Clean the sequence data from the request payload, ensuring it is in a valid format for bookmarking.
        sequence = clean_sequence_data(payload.get("sequence") or "")

        # Ensure both a name and a sequence are provided in the request payload.
        if not name or not sequence:
            return jsonify({"error": "Both a name (up to 60 characters) and a sequence are required."}), 400
        # Ensure the sequence length does not exceed the maximum allowed length for bookmarking.
        if len(sequence) > MAX_SEQUENCE_LENGTH:
            return jsonify({"error": "That sequence is too long to bookmark."}), 400

        # Query the database to find the last position of the user's bookmarks, defaulting to 0 if none exist.
        last = db.execute(
            "SELECT COALESCE(MAX(position), 0) AS p FROM bookmarks WHERE user_id = ?", (session["user_id"],)
        ).fetchone()["p"]

        # Insert the new bookmark into the database with the user's ID, name, sequence, the current UTC timestamp, and position.
        db.execute(
            "INSERT INTO bookmarks (user_id, name, sequence, created_at, position) VALUES (?, ?, ?, ?, ?)",
            (session["user_id"], name, sequence, datetime.utcnow().isoformat(timespec="seconds"), last + 1),
        )
        db.commit()

        # Return a JSON response indicating that the bookmark was successfully saved.
        return jsonify({"message": "Bookmark saved."})

    # For GET requests, return the list of bookmarks for the logged-in user as a JSON response.
    return jsonify(get_bookmarks(session["user_id"]))


@app.route("/api/bookmarks/order", methods=["PUT"])
@login_required

def api_bookmarks_order():
    """Save a drag-and-drop order: the JSON body is {"ids": [3, 1, 2]}, first = top."""

    # Get the list of bookmark IDs from the JSON payload, defaulting to an empty dictionary if parsing fails.
    ids = (request.get_json(silent=True) or {}).get("ids")

    # Validate that the provided "ids" is a list of integers, returning an error response if not.
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        return jsonify({"error": "Send a list of bookmark ids."}), 400

    db = get_db()

    for position, bookmark_id in enumerate(ids):
        # Update the position of each bookmark for the logged-in user in the database based on the provided order.
        db.execute(
            "UPDATE bookmarks SET position = ? WHERE id = ? AND user_id = ?",
            (position, bookmark_id, session["user_id"]),
        )
    db.commit()

    # Return a JSON response indicating that the order of bookmarks was successfully saved.
    return jsonify({"message": "Order saved."})


@app.route("/api/bookmarks/<int:bookmark_id>", methods=["GET", "PATCH", "DELETE"])
@login_required

def api_bookmark(bookmark_id):

    db = get_db()

    # Query the database for the bookmark with the specified ID that belongs to the logged-in user.
    row = db.execute(
        "SELECT id, name, sequence FROM bookmarks WHERE id = ? AND user_id = ?",
        (bookmark_id, session["user_id"]),
    ).fetchone()
    # If the specified bookmark ID does not exist in the database, return an error response indicating that the bookmark was not found.
    if row is None:
        return jsonify({"error": "Bookmark not found."}), 404

    if request.method == "GET":
        # Return a JSON response containing the bookmark's ID, name, and sequence for the logged-in user.
        return jsonify({"id": row["id"], "name": row["name"], "sequence": row["sequence"]})

    if request.method == "DELETE":
        # Delete the bookmark with the specified ID for the logged-in user from the database.
        db.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        db.commit()
        # Return a JSON response indicating that the bookmark was successfully deleted.
        return jsonify({"message": "Bookmark deleted."})

    # PATCH: rename and/or move into a group (group_id null = no group).
    payload = request.get_json(silent=True) or {}

    if "name" in payload:
        name = clean_name(payload["name"])

        # Validate that the provided bookmark name is not empty, returning an error response if it is.
        if not name:
            return jsonify({"error": "A name needs 1 to 60 characters."}), 400
        # Update the name of the bookmark with the specified ID for the logged-in user in the database.
        db.execute("UPDATE bookmarks SET name = ? WHERE id = ?", (name, bookmark_id))

    if "group_id" in payload:
        group_id = payload["group_id"]

        if group_id is not None:
            # Check if the specified group_id exists for the logged-in user in the database.
            group = db.execute(
                "SELECT id FROM bookmark_groups WHERE id = ? AND user_id = ?", (group_id, session["user_id"])
            ).fetchone()
            # If the specified group_id does not exist in the database, return an error response indicating that the group was not found.
            if group is None:
                return jsonify({"error": "Group not found."}), 400
        # Update the group_id of the bookmark with the specified ID for the logged-in user in the database.
        db.execute("UPDATE bookmarks SET group_id = ? WHERE id = ?", (group_id, bookmark_id))

    db.commit()

    # Return a JSON response indicating that the bookmark was successfully updated.
    return jsonify({"message": "Bookmark updated."})


def group_name_taken(db, name, ignore_id=0):

    # Check if a bookmark group name is already taken by the logged-in user, ignoring a specific group ID (useful for renaming).
    return db.execute(
        "SELECT id FROM bookmark_groups WHERE user_id = ? AND lower(name) = lower(?) AND id != ?",
        (session["user_id"], name, ignore_id),
    ).fetchone() is not None


@app.route("/api/bookmark-groups", methods=["GET", "POST"])
@login_required

def api_bookmark_groups():

    db = get_db()

    if request.method == "POST":
        name = clean_name((request.get_json(silent=True) or {}).get("name"))
        # Validate that the provided group name is not empty, returning an error response if it is.
        if not name:
            return jsonify({"error": "A group name needs 1 to 60 characters."}), 400
        # Check if the group name is already taken by the logged-in user, returning an error response if it is.
        if group_name_taken(db, name):
            return jsonify({"error": "You already have a group with that name."}), 400
        # Insert the new bookmark group into the database with the logged-in user's ID, name, and the current UTC timestamp.
        cursor = db.execute(
            "INSERT INTO bookmark_groups (user_id, name, created_at) VALUES (?, ?, ?)",
            (session["user_id"], name, datetime.utcnow().isoformat(timespec="seconds")),
        )
        db.commit()
        # Return a JSON response containing the ID and name of the newly created bookmark group.
        return jsonify({"id": cursor.lastrowid, "name": name})

    # For GET requests, query the database for all bookmark groups belonging to the logged-in user, ordered by name (case-insensitive).
    rows = db.execute(
        "SELECT id, name FROM bookmark_groups WHERE user_id = ? ORDER BY lower(name)", (session["user_id"],)
    ).fetchall()

    # Return a JSON response containing a list of bookmark groups, each represented as a dictionary with its ID and name.
    return jsonify([dict(r) for r in rows])


@app.route("/api/bookmark-groups/<int:group_id>", methods=["PATCH", "DELETE"])
@login_required

def api_bookmark_group(group_id):

    db = get_db()

    # Query the database for the bookmark group with the specified ID that belongs to the logged-in user.
    group = db.execute(
        "SELECT id FROM bookmark_groups WHERE id = ? AND user_id = ?", (group_id, session["user_id"])
    ).fetchone()
    # If the specified group ID does not exist in the database, return an error response indicating that the group was not found.
    if group is None:
        return jsonify({"error": "Group not found."}), 404

    if request.method == "DELETE":
        # Deleting a group never deletes bookmarks from the database -- they just become ungrouped.
        db.execute("UPDATE bookmarks SET group_id = NULL WHERE group_id = ? AND user_id = ?",
                   (group_id, session["user_id"]))
        # Delete the bookmark group with the specified ID for the logged-in user from the database.
        db.execute("DELETE FROM bookmark_groups WHERE id = ?", (group_id,))
        db.commit()
        # Return a JSON response indicating that the bookmark group was successfully deleted.
        return jsonify({"message": "Group deleted."})

    name = clean_name((request.get_json(silent=True) or {}).get("name"))
    # Validate that the provided group name is not empty, returning an error response if it is.
    if not name:
        return jsonify({"error": "A group name needs 1 to 60 characters."}), 400
    # Check if the new group name is already taken by the logged-in user, ignoring the current group ID to allow renaming to the same name.
    if group_name_taken(db, name, ignore_id=group_id):
        return jsonify({"error": "You already have a group with that name."}), 400

    # Update the name of the bookmark group with the specified ID for the logged-in user in the database.
    db.execute("UPDATE bookmark_groups SET name = ? WHERE id = ?", (name, group_id))
    db.commit()

    # Return a JSON response indicating that the bookmark group was successfully renamed.
    return jsonify({"message": "Group renamed."})


@app.route("/api/regenerate-key", methods=["POST"])
@login_required

def api_regenerate_key():

    # Generate a new random API key for the logged-in user.
    new_key = secrets.token_hex(24)

    db = get_db()

    # Regenerate the API key for the logged-in user and update the database.
    db.execute("UPDATE users SET api_key = ? WHERE id = ?", (new_key, session["user_id"]))
    db.commit()

    # Return a JSON response containing the new API key.
    return jsonify({"api_key": new_key})


# =====================================================================
# Entry Point: initialize the database and start the Flask application.
# =====================================================================

init_db()

# Run the Flask app if this script is executed directly (not imported as a module).
if __name__ == "__main__":
    # Debug mode is handy for auto-reload; turn off for a demo.
    app.run(host="0.0.0.0", port=5000, debug=True)
