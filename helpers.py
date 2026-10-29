"""
helpers.py
----------
Everything app.py needs but shouldn't have to show in the middle of its routes (so app.py can shrink down to a few lines of code),
including: the database, login/API-key checks, rate limiting, the results cache, matplotlib image rendering, and report formatting.

This is the same split CS50's own Finance problem set uses -- `from helpers import apology, login_required, lookup, usd` -- just with
an extra biology.py alongside it for the actual science.
"""

import base64
import hashlib
import io
import json
import os
import sqlite3
import textwrap
import threading
import time
import zipfile
from collections import OrderedDict, defaultdict
from datetime import datetime
from functools import wraps

from flask import g, session, request, redirect, url_for, flash, jsonify

# Matplotlib is only used for the plot/PDF/ZIP export features. Its figure class is used directly so nothing ever tries to open a window --
# exactly what a headless server needs -- and so two people exporting at the same time cannot step on each other.
from matplotlib.figure import Figure
from matplotlib.backends.backend_pdf import PdfPages

from biology import (
    clean_sequence_data, detect_sequence_type, to_dna, transcribe,
    reverse_complement, six_frame_translation, find_orfs, gc_content,
    base_composition, analyze_protein, disorder_profile, net_charge_at_ph,
    estimate_pi, DNA_COMPLEMENT, RNA_COMPLEMENT,
)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dptlite.db")

# Reject anything longer than 50,000 so as to keep Codespaces snappy.
MAX_SEQUENCE_LENGTH = 50000


# ========================================================
# Database: plain sqlite3 -- no ORM, one file (dptlite.db)
# ========================================================

def get_db():
    """Open one sqlite3 connection per request, reused for that request."""

    # As sqlite3.connect() is not thread-safe, connection is stored in Flask's `g` object, which is unique to each request.
    db = getattr(g, "_database", None)

    # If no connection exists yet, create one and store it in `g`.
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        # Return rows as dictionaries instead of tuples, so columns can be accessed by name.
        db.row_factory = sqlite3.Row
        # Enable foreign key constraints.
        db.execute("PRAGMA foreign_keys = ON")
    return db


def close_db(_exception=None):
    """Registered with app.teardown_appcontext(close_db) in app.py."""

    # As sqlite3.connect() is not thread-safe, connection is stored in Flask's `g` object, which is unique to each request.
    db = getattr(g, "_database", None)

    # If a connection exists, close it. This is called automatically at the end of each request.
    if db is not None:
        db.close()


def init_db():
    """Create tables on first run. Safe to call every time the app starts."""

    # Instead of CS50 library's SQL wrapper, Python's built-in sqlite3 module is used to access the database.
    db = sqlite3.connect(DB_PATH)

    # Four tables:
    #   users           - account info, password hash, and a per-user API key
    #   history         - one row per successful analysis, used by History + Profile
    #   bookmarks       - named sequences a user has chosen to save
    #   bookmark_groups - groups to organize bookmarks
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            hash TEXT NOT NULL,
            api_key TEXT UNIQUE,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            input_type TEXT,
            length INTEGER,
            protein_length INTEGER,
            sequence_snippet TEXT,
            full_sequence TEXT,
            created_at TEXT NOT NULL,
            orf_count INTEGER DEFAULT 0,
            from_cache INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            sequence TEXT NOT NULL,
            created_at TEXT NOT NULL,
            group_id INTEGER,
            position INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS bookmark_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        """
    )

    # A database created by an earlier version of DPTlite doesn't have the two newest history columns, and CREATE TABLE IF NOT EXISTS won't
    # add them. So we add any missing column in place -- your existing accounts, history, and bookmarks are kept.
    existing = [row[1] for row in db.execute("PRAGMA table_info(history)")]

    for column in ("orf_count", "from_cache"):
        # If the column doesn't exist in the history table, add it with a default value of 0.
        if column not in existing:
            db.execute(f"ALTER TABLE history ADD COLUMN {column} INTEGER DEFAULT 0")

    # Same idea for bookmarks: add the group and "my order" columns to a database that was created before bookmark groups existed.
    bookmark_columns = [row[1] for row in db.execute("PRAGMA table_info(bookmarks)")]

    # If the "group_id" column doesn't exist, add it to the bookmarks table.
    if "group_id" not in bookmark_columns:
        db.execute("ALTER TABLE bookmarks ADD COLUMN group_id INTEGER")

    # If the "position" column doesn't exist, add it and initialize it to the current row ID so that existing bookmarks retain their order.
    if "position" not in bookmark_columns:
        db.execute("ALTER TABLE bookmarks ADD COLUMN position INTEGER DEFAULT 0")
        db.execute("UPDATE bookmarks SET position = id")

    db.commit()
    db.close()


def log_history(user_id, result):
    """Record one successful analysis so History + Profile can read it back."""

    db = get_db()

    # Extract protein analysis. If the result dictionary doesn't have a "protein_analysis" key, use an empty dictionary instead.
    pa = result.get("protein_analysis") or {}

    # Insert a new row into the history table with the relevant data.
    db.execute(
        "INSERT INTO history "
        "(user_id, input_type, length, protein_length, sequence_snippet, full_sequence, created_at, orf_count, from_cache) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user_id,
            result["input_type"],                              # Type of input sequence (DNA / RNA / Protein)
            result["length"],                                  # Length of the input sequence
            pa.get("length", 0),                               # Protein length (default to 0 if not available)
            result["cleaned_sequence"][:60],                   # Snippet of the sequence (first 60 characters)
            result["cleaned_sequence"][:MAX_SEQUENCE_LENGTH],  # Full sequence (capped to 50,000 characters)
            datetime.utcnow().isoformat(timespec="seconds"),   # UTC timestamp in ISO format
            result.get("orf_count", 0),                        # Number of open reading frames (ORFs) found (default to 0 if not available)
            1 if result.get("from_cache") else 0,              # Flag indicating if the result was retrieved from cache (1) or not (0)
        ),
    )

    db.commit()


def get_user_stats(user_id):
    """Every number shown on the Profile page, from one query over `history`."""

    # Query the database to get various statistics about the user's analysis history.
    row = get_db().execute(
        "SELECT COUNT(*) AS total, "
        "COALESCE(SUM(input_type = 'DNA'), 0) AS dna, "
        "COALESCE(SUM(input_type = 'RNA'), 0) AS rna, "
        "COALESCE(SUM(input_type = 'PROTEIN'), 0) AS protein, "
        "AVG(CASE WHEN input_type IN ('DNA', 'RNA') THEN length END) AS avg_nt_length, "
        "AVG(CASE WHEN protein_length > 0 THEN protein_length END) AS avg_protein_length, "
        "COALESCE(SUM(orf_count), 0) AS total_orfs, "
        "COALESCE(SUM(from_cache), 0) AS cache_hits, "
        "COALESCE(MAX(protein_length), 0) AS longest_protein "
        "FROM history WHERE user_id = ?",
        (user_id,),
    ).fetchone()

    counts = {"DNA": row["dna"], "RNA": row["rna"], "PROTEIN": row["protein"]}
    total = row["total"]

    # Return a dictionary containing various statistics about the user's analysis history.
    return {
        "total_analyses": total,
        "most_common_type": max(counts, key=counts.get) if total else "—",
        "longest_protein": row["longest_protein"],
        "dna_count": row["dna"],
        "rna_count": row["rna"],
        "protein_count": row["protein"],
        "avg_nt_length": round(row["avg_nt_length"] or 0),
        "avg_protein_length": round(row["avg_protein_length"] or 0),
        "total_orfs": row["total_orfs"],
        "cache_hits": row["cache_hits"],
        "cache_misses": total - row["cache_hits"],
        "cache_hit_rate": round(100 * row["cache_hits"] / total) if total else 0,
    }


# ===================================================================
# Bookmarks: named sequences, optionally collected into named groups.
# ===================================================================

MAX_NAME_LENGTH = 60


def clean_name(value):
    """A bookmark/group name with the spaces trimmed, or None if it's empty or too long."""

    # Strip leading and trailing whitespace from the input value and convert it to a string (an empty string if the value is None or empty).
    name = str(value or "").strip()
    # If the name is non-empty and within the maximum length, return it; otherwise, return None.
    return name if 0 < len(name) <= MAX_NAME_LENGTH else None


def get_bookmarks(user_id):
    """
    Every bookmark of one user, newest first, WITHOUT the full sequence (that can be 50,000 letters long; the page asks for one sequence at a
    time when you click Reload). Each item carries what the lists need: name, group, type, length, snippet.
    """

    # Query the database to retrieve all bookmarks for the specified user, along with their associated group names (if any).
    rows = get_db().execute(
        "SELECT b.id, b.name, b.sequence, b.created_at, b.group_id, b.position, g.name AS group_name "
        "FROM bookmarks b LEFT JOIN bookmark_groups g ON g.id = b.group_id "
        "WHERE b.user_id = ? ORDER BY b.created_at DESC, b.id DESC",  # Order by creation date (newest first) and bookmark ID (descending).
        (user_id,),
    ).fetchall()

    # Return a list of dictionaries, each representing a bookmark with relevant information.
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "group_id": row["group_id"],
            "group_name": row["group_name"],
            "position": row["position"],
            "created_at": row["created_at"],
            "input_type": detect_sequence_type(row["sequence"])[0],
            "length": len(row["sequence"]),
            "snippet": row["sequence"][:40],
        }
        for row in rows
    ]


# ============================================================
# Authentication: sessions for the site, API keys for scripts.
# ============================================================

def login_required(view):
    """Redirect to /login if there's no logged-in user in the session."""

    # The @wraps decorator preserves the original function's name and docstring, which is useful for debugging and introspection.
    @wraps(view)

    # The wrapped function checks if the user is logged in by looking for "user_id" in the session.
    def wrapped(*args, **kwargs):
        # If the user is not logged in, flash an error message and redirect to the login page.
        if session.get("user_id") is None:
            flash("Please log in to use that feature.", "error")
            return redirect(url_for("login"))
        # If the user is logged in, call the original view function with its arguments and keyword arguments.
        return view(*args, **kwargs)

    return wrapped


def api_key_required(view):
    """Authenticate for the programmatic /api/v1/* routes: a header, not a cookie."""

    # The @wraps decorator preserves the original function's name and docstring, which is useful for debugging and introspection.
    @wraps(view)

    # The wrapped function checks for an API key in the request headers or query parameters, and validates it against the database.
    def wrapped(*args, **kwargs):
        # Check for the API key in the "X-API-Key" header or the "api_key" query parameter.
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        # If no API key is provided, return a 401 Unauthorized response with an error message.
        if not key:
            return jsonify({"error": "Missing API key. Send it as the X-API-Key header."}), 401
        # If an API key is provided, look it up in the database to find the corresponding user.
        user = get_db().execute("SELECT * FROM users WHERE api_key = ?", (key,)).fetchone()
        # If the API key is invalid (no user found), return a 401 Unauthorized response with an error message.
        if user is None:
            return jsonify({"error": "Invalid API key."}), 401
        # If the API key is valid, store the user information in Flask's `g` object for use in the view function.
        g.api_user = user
        # Call the original view function with its arguments and keyword arguments.
        return view(*args, **kwargs)

    return wrapped


# =============================================================
# Rate Limiting + Caching: both pure Python, no extra services.
# =============================================================

# A tiny in-memory sliding-window limiter. It resets if the app restarts, which is fine for a CS50 final project -- the goal is just to
# blunt accidental spam (e.g. a broken loop hammering the analyze button), not to withstand a real attack.

# Lock to protect access to the rate log, ensuring thread safety when multiple requests are processed concurrently.
_rate_lock = threading.Lock()
_rate_log = defaultdict(list)


def _is_rate_limited(key, max_requests, window_seconds):
    """Decide whether a client should be blocked. Return True if the given key has exceeded the rate limit."""

    # Get the current time in seconds.
    now = time.time()

    with _rate_lock:
        # Get the list of timestamps for the given key (client identifier).
        timestamps = _rate_log[key]
        # Remove old timestamps that are outside the sliding window.
        cutoff = now - window_seconds
        while timestamps and timestamps[0] < cutoff:
            timestamps.pop(0)
        # If the number of timestamps in the list >= the maximum allowed requests, return True to indicate that the client is rate-limited.
        if len(timestamps) >= max_requests:
            return True
        # If the client is not rate-limited, append the current timestamp to the list for future checks.
        timestamps.append(now)
        return False


def rate_limit(max_requests=30, window_seconds=60, json_response=True):
    """Decorator: cap calls per client to `max_requests` per `window_seconds`."""

    def decorator(view):

        # The @wraps decorator preserves the original function's name and docstring, which is useful for debugging and introspection.
        @wraps(view)

        def wrapped(*args, **kwargs):
            # Identify the client by either the "X-API-Key" header or the remote IP address.
            client = request.headers.get("X-API-Key") or request.remote_addr
            # Create a unique key for the client and view combination to track rate limiting.
            key = f"{view.__name__}:{client}"

            # Check if the client has exceeded the rate limit using the _is_rate_limited function.
            if _is_rate_limited(key, max_requests, window_seconds):
                message = "Too many requests -- please wait a moment and try again."
                # If the request expects a JSON response (e.g., an API call), return a JSON error message with a 429 status code.
                if json_response:
                    return jsonify({"error": message}), 429
                # If the request is a regular web request, flash an error message and redirect back to the same page.
                flash(message, "error")
                return redirect(request.path)

            # If the client is not rate-limited, call the original view function with its arguments and keyword arguments.
            return view(*args, **kwargs)

        return wrapped

    return decorator


# A small results cache: if someone (re-)submits the exact same cleaned sequence, skip recomputation and return the stored result instantly.
_cache_lock = threading.Lock()
_analysis_cache = OrderedDict()
CACHE_MAX_ENTRIES = 300


def _cache_get(key):

    # Acquire the lock. Only one thread can access the cache at a time.
    with _cache_lock:

        # If the key exists in the cache, move it to the end of the OrderedDict to mark it as recently used and return the cached value.
        if key in _analysis_cache:
            _analysis_cache.move_to_end(key)  # The essence of an LRU (Least Recently Used) cache.
            return _analysis_cache[key]

    # If the key is not found in the cache, return None to indicate a cache miss.
    return None


def _cache_set(key, value):

    # Acquire the lock. Only one thread can access the cache at a time.
    with _cache_lock:

        # Store the value in the cache and mark it as recently used by moving it to the end of the OrderedDict.
        _analysis_cache[key] = value
        _analysis_cache.move_to_end(key)

        # If the cache exceeds the maximum number of entries, remove the oldest entry (the first item in the OrderedDict).
        if len(_analysis_cache) > CACHE_MAX_ENTRIES:
            _analysis_cache.popitem(last=False)  # The essence of an LRU (Least Recently Used) cache.


# ===================================================================================
# Shared Analysis Pipeline: run functions from biology.py, store result in the cache.
# ===================================================================================

# This wraps biology.py's functions into one reusable call so both the logged-in web UI and the API-key endpoint share identical behavior,
# validation, caching, and length limits.

def run_full_analysis(raw_text):
    """
    Returns (result_dict, None) on success, or (None, (error_json, status)) on failure, so routes can just do: result, error = run_full_analysis(...)
    """

    # Start a timer to measure the time taken for the analysis. This is used for displaying the "Completed in ... ms" message.
    started = time.perf_counter()

    # Clean the input sequence and detect its type (DNA, RNA, PROTEIN, or UNKNOWN).
    seq = clean_sequence_data(raw_text)
    seq_type, invalid_chars = detect_sequence_type(seq)

    # If the sequence is empty, return an error message and a 400 status code.
    if seq_type == "EMPTY":
        return None, ({"error": "Please enter a sequence."}, 400)

    # If the sequence exceeds the maximum allowed length, return an error message and a 400 status code.
    if len(seq) > MAX_SEQUENCE_LENGTH:
        return None, (
            {"error": f"Sequence is {len(seq):,} letters long; the limit is "
                      f"{MAX_SEQUENCE_LENGTH:,} to keep the app responsive."},
            400,
        )

    # If the sequence contains unrecognized characters, return an error message and a 400 status code.
    if seq_type == "UNKNOWN":
        return None, (
            {"error": f"Unrecognized character(s): {', '.join(sorted(invalid_chars))}. "
                      f"Use A/C/G/T (DNA), A/C/G/U (RNA), or standard amino acid letters."},
            400,
        )

    # Generate a SHA-256 hash of the cleaned sequence to use as a cache key.
    cache_key = hashlib.sha256(seq.encode()).hexdigest()

    # Attempt to retrieve a cached result for the given sequence using the generated cache key.
    cached = _cache_get(cache_key)

    # If a cached result exists for the given sequence, return it immediately (with elapsed time) to avoid recomputation.
    if cached is not None:
        result = dict(cached)
        result["from_cache"] = True
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return result, None

    # If no cached result exists, perform the full analysis below.
    result = {"input_type": seq_type, "length": len(seq), "cleaned_sequence": seq}

    # If the sequence is DNA or RNA, perform various analyses including GC content, base composition, transcription, complement, reverse complement.
    if seq_type in ("DNA", "RNA"):
        is_rna = seq_type == "RNA"
        dna = to_dna(seq)
        result["gc_content_percent"] = gc_content(dna)
        result["base_composition"] = base_composition(seq)
        result["transcribed_rna"] = transcribe(dna) if not is_rna else seq
        result["complement"] = "".join(
            (RNA_COMPLEMENT if is_rna else DNA_COMPLEMENT).get(b, "N") for b in seq
        )
        result["reverse_complement"] = reverse_complement(seq, is_rna)

        # Perform six-frame translation and find open reading frames (ORFs) in the translated sequences.
        frames = six_frame_translation(seq, is_rna)
        result["six_frame_translation"] = frames
        orfs = find_orfs(frames)
        result["orfs"] = orfs[:10]                   # Keep top 10 ORFs and show them in the result.
        result["orf_count"] = len(orfs)              # Return the count of all ORFs found, not just the 10 shown.

        # If there are any ORFs found, use the protein from the first ORF; otherwise, use the longest protein from the six-frame translation.
        best_protein = orfs[0]["protein"] if orfs else max(
            (f["protein"] for f in frames), key=len, default=""
        )
        result["protein_analysis"] = analyze_protein(best_protein)

    # If the sequence is a protein, perform protein analysis directly.
    else:
        result["orf_count"] = 0                            # ORFs only exist in nucleic acid input.
        result["protein_analysis"] = analyze_protein(seq)

    # Mark the result as not coming from the cache and store it (with elapsed time) in the cache for future requests.
    result["from_cache"] = False
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    _cache_set(cache_key, result)

    return result, None


# ===========================================================
# Protein Visualization: matplotlib, rendered to base64 PNGs.
# ===========================================================

# These reuse biology.py's profile functions; they just add a plotting layer on top for a downloadable/static view, alongside the interactive
# Chart.js versions already in the UI.

PI_COLOR = "#7c5cc4"  # Purple, so the pI marker stands out from the red curve.

# Each _draw_* function below paints one plot onto an "ax" (a matplotlib axes). That lets the same plot appear as a single PNG on the Export
# tab, as a file inside the ZIP bundle, and as one of three stacked plots on the PDF.

def _draw_hydropathy(ax, profile):

    ax.plot(range(1, len(profile) + 1), profile, color="#2f8f68", linewidth=1.4)
    ax.axhline(0, color="#999999", linewidth=0.7, linestyle="--")
    ax.set_xlabel("Residue position")
    ax.set_ylabel("Hydropathy (Kyte-Doolittle)")
    ax.set_title("Hydrophobicity plot")


def _draw_charge_ph(ax, protein):

    # Create a list of pH values from 0.0 to 14.0 in increments of 0.1.
    ph_values = [p / 10 for p in range(0, 141)]
    # Calculate the net charge of the protein at each pH value.
    charges = [net_charge_at_ph(protein, ph) for ph in ph_values]

    ax.plot(ph_values, charges, color="#e0654c", linewidth=1.4)
    ax.axhline(0, color="#999999", linewidth=0.7, linestyle="--")

    # Mark the predicted isoelectric point: the pH where net charge = 0.
    pi = estimate_pi(protein)

    if pi is not None:
        ax.axvline(pi, color=PI_COLOR, linestyle=":", linewidth=1.3)
        ax.plot([pi], [0], "o", color=PI_COLOR, markersize=6, zorder=3)

        # Put the label on the left so it isn't cut off.
        near_right_edge = pi > 10

        # Annotate the plot with the predicted isoelectric point (pI) value, positioned appropriately based on its location on the x-axis.
        ax.annotate(
            f"pI = {pi}",
            xy=(pi, 1), xycoords=("data", "axes fraction"),
            xytext=(-5 if near_right_edge else 5, -5), textcoords="offset points",
            ha="right" if near_right_edge else "left", va="top",
            color=PI_COLOR, fontsize=9, fontweight="bold",
        )

    ax.set_xlabel("pH")
    ax.set_ylabel("Net charge")
    ax.set_title("Charge vs. pH curve")


def _draw_disorder(ax, protein):

    # Calculate the disorder tendency scores for each residue in the protein sequence.
    scores = disorder_profile(protein)
    # Create a list of x-coordinates corresponding to the residue positions in the protein sequence.
    xs = list(range(1, len(scores) + 1))

    ax.plot(xs, scores, color="#4c9fe0", linewidth=1.2)
    ax.axhline(0, color="#999999", linewidth=0.7, linestyle="--")
    ax.fill_between(xs, scores, 0, where=[s < 0 for s in scores], color="#4c9fe0", alpha=0.25)
    ax.set_xlabel("Residue position")
    ax.set_ylabel("Order (+) / disorder (-)")
    ax.set_title("Disorder tendency")


def _single_plot(draw, data):
    """One plot on its own figure, ready to save as a PNG."""

    # Create a new matplotlib figure with a specified size (6 inches wide by 3 inches tall).
    fig = Figure(figsize=(6, 3))
    draw(fig.subplots(), data)
    fig.tight_layout()

    return fig


def _figure_to_png_bytes(fig):

    # Save the figure to a BytesIO buffer in PNG format with a specified DPI and tight bounding box, then return the byte content.
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")

    return buf.getvalue()


def _figure_to_data_uri(fig):

    # Convert a matplotlib figure to a base64-encoded PNG data URI for embedding in HTML.
    return "data:image/png;base64," + base64.b64encode(_figure_to_png_bytes(fig)).decode("ascii")


# The three functions below (render_*_figure) are called by app.py's /api/plots route.

def render_hydropathy_figure(profile):
    return _figure_to_data_uri(_single_plot(_draw_hydropathy, profile))


def render_charge_ph_figure(protein):
    return _figure_to_data_uri(_single_plot(_draw_charge_ph, protein))


def render_disorder_figure(protein):
    return _figure_to_data_uri(_single_plot(_draw_disorder, protein))


# ==================================================================================
# Downloadable Reports: export result as a .txt / .json / .pdf / .fasta / .zip file.
# ==================================================================================

def format_text_report(result):
    """Return a string suitable for a .txt download, with a header and all the analysis results."""

    # Extract protein analysis from the result dictionary, defaulting to an empty dictionary if not present.
    pa = result.get("protein_analysis", {})

    # Net charge at pH 7.0 isn't stored in the analysis result, so it is calculated here with biology.py's net_charge_at_ph().
    protein = pa.get("sequence", "")
    net_charge = f"{net_charge_at_ph(protein, 7.0):+.2f}" if protein else "-"

    # If transmembrane helices are detected, format their information; otherwise, indicate that none were detected.
    helices = pa.get("transmembrane_helices", [])
    if helices:
        ranges = ", ".join(f"{h['start']}-{h['end']}" for h in helices)
        tm_text = f"{len(helices)} (residues {ranges})"
    else:
        tm_text = "none"

    # If a signal peptide is detected, format its information; otherwise, indicate that none was detected.
    signal = pa.get("signal_peptide")
    if signal:
        signal_text = (f"hydrophobic core at residues {signal['start']}-{signal['end']} "
                       f"(avg hydropathy {signal['avg_hydropathy']})")
    else:
        signal_text = "none detected"

    # Build a list of lines for the text report, starting with a header and metadata about the analysis.
    lines = [
        "DPTlite analysis report",
        "========================",
        f"Generated: {datetime.utcnow().isoformat(timespec='seconds')} UTC",
        "",
        f"Input type: {result['input_type']}",
        f"Length: {result['length']}",
    ]

    # If the result dictionary contains a "gc_content_percent" key, append the GC content information to the report lines.
    if "gc_content_percent" in result:
        lines.append(f"GC content: {result['gc_content_percent']}%")

    # Add protein analysis part to the text report.
    lines += [
        "",
        "-- Protein analysis --",
        f"Protein length: {pa.get('length', 0)} aa",
        f"Molecular weight: {pa.get('molecular_weight_da', '-')} Da",
        f"Theoretical pI: {pa.get('theoretical_pi', '-')}",
        f"Net charge at pH 7.0: {net_charge}",
        f"Secondary structure: helix {pa.get('structure_summary', {}).get('helix_percent', '-')}%, "
        f"sheet {pa.get('structure_summary', {}).get('sheet_percent', '-')}%, "
        f"coil {pa.get('structure_summary', {}).get('coil_percent', '-')}%",
        f"Predicted TM helices: {tm_text}",
        f"Signal peptide: {signal_text}",
        f"Order/disorder call: {pa.get('order_disorder', {}).get('call', '-')}",
        "",
        "Protein sequence:",
        pa.get("sequence", ""),
    ]

    # Join everything into one string and return it for download as a .txt file.
    return "\n".join(lines)


PDF_TEXT_LINES = 24  # Text lines that fit above the plots on the one-page PDF.


def build_pdf(result):
    """One page: the text summary on top, the three plots stacked below it."""

    pa = result["protein_analysis"]

    # Determine whether the protein sequence is present to decide if plots should be included in the PDF.
    has_plots = bool(pa["sequence"])

    # Set the maximum number of text lines to include in the PDF based on whether plots are present, no plots = more room for text.
    max_lines = PDF_TEXT_LINES if has_plots else 60

    lines = []
    # Wrap each line of the text report to a maximum width of 90 characters. Handle empty lines also to keep formatting intact.
    for line in format_text_report(result).splitlines():
        lines += textwrap.wrap(line, 90) or [""]
    # If the number of lines exceeds the maximum allowed, truncate the lines and add a note indicating that the .txt report has everything.
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["... (shortened here -- the .txt report has the full sequence)"]

    page = Figure(figsize=(8.5, 11))
    page.text(0.07, 0.96, "\n".join(lines), family="monospace", fontsize=8, va="top")

    # If the protein sequence is present, create three subplots for hydropathy, charge vs. pH, and disorder tendency, and adjust the layout.
    if has_plots:
        top, middle, bottom = page.subplots(3, 1)
        _draw_hydropathy(top, pa["hydropathy_profile"])
        _draw_charge_ph(middle, pa["sequence"])
        _draw_disorder(bottom, pa["sequence"])
        page.subplots_adjust(top=0.64, bottom=0.06, left=0.11, right=0.95, hspace=0.75)

    # Save the page to a BytesIO buffer as a PDF file using PdfPages, which allows for multiple pages if needed in the future.
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        pdf.savefig(page)

    # Return the byte content of the PDF file.
    return buf.getvalue()


def build_fasta(result):
    """The input sequence (if nucleic acid) and the protein that was analyzed."""

    pa = result["protein_analysis"]
    is_nucleic = result["input_type"] in ("DNA", "RNA")
    records = []

    # If the input sequence is nucleic acid, add it to the FASTA records with a header indicating its type and length.
    if is_nucleic:
        records.append((f"DPTlite_input {result['input_type']}, {result['length']} nt",
                        result["cleaned_sequence"]))

    if pa["sequence"]:
        # If the input sequence is not nucleic acid, indicate that sequence was derived from an input protein.
        if not is_nucleic:
            source = "input protein"
        # If ORFs were found, indicate that the protein was translated from the longest ORF.
        elif result.get("orf_count", 0) > 0:
            source = "translated from the longest ORF"
        # If no ORFs were found, indicate that the protein was translated from the longest reading frame.
        else:
            source = "translated from the longest reading frame (no ORF found)"

        # Add the analyzed protein sequence to the FASTA records with a header indicating its source and length.
        records.append((f"DPTlite_protein {source}, {pa['length']} aa", pa["sequence"]))

    # FASTA convention: sequence lines wrapped at 60 characters.
    return "".join(f">{header}\n" + "\n".join(textwrap.wrap(seq, 60)) + "\n" for header, seq in records)


def build_zip(result):
    """Text report + FASTA + the three plots as PNG files, in one download."""

    pa = result["protein_analysis"]

    # Save everything into a BytesIO buffer as a ZIP file, which can be returned to the user for download.
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as bundle:
        # Add the text report, JSON report, PDF report, and FASTA file to the ZIP bundle.
        bundle.writestr("dptlite_report.txt", format_text_report(result))
        bundle.writestr("dptlite_report.json", json.dumps(result, indent=2))
        bundle.writestr("dptlite_report.pdf", build_pdf(result))
        bundle.writestr("dptlite_sequences.fasta", build_fasta(result))

        # If the protein sequence is present, generate and include the three plots as PNG files in the ZIP bundle.
        if pa["sequence"]:
            plots = {
                "hydropathy_plot.png": _single_plot(_draw_hydropathy, pa["hydropathy_profile"]),
                "charge_vs_ph_plot.png": _single_plot(_draw_charge_ph, pa["sequence"]),
                "disorder_plot.png": _single_plot(_draw_disorder, pa["sequence"]),
            }
            # Save each plot as a PNG file in the ZIP bundle.
            for filename, fig in plots.items():
                bundle.writestr(filename, _figure_to_png_bytes(fig))

    # Return the byte content of the ZIP file.
    return buf.getvalue()


def build_report_file(result, fmt):
    """Returns (body, mimetype, filename) for whichever Export button was pressed."""

    # If fmt is "json", return a JSON file containing the analysis result.
    if fmt == "json":
        return json.dumps(result, indent=2), "application/json", "dptlite_report.json"

    # If fmt is "pdf", return a PDF file containing the text report.
    if fmt == "pdf":
        return build_pdf(result), "application/pdf", "dptlite_report.pdf"

    # If fmt is "fasta", return a FASTA file containing the input sequence (if nucleic acid) and the analyzed protein sequence.
    if fmt == "fasta":
        return build_fasta(result), "text/plain", "dptlite_sequences.fasta"

    # If fmt is "zip", return a ZIP file containing the text report, JSON report, PDF report, FASTA file, and plots (if applicable).
    if fmt == "zip":
        return build_zip(result), "application/zip", "dptlite_bundle.zip"
    
    # If fmt is "txt" or anything else, default to the text report.
    return format_text_report(result), "text/plain", "dptlite_report.txt"
