"""
Flask web server for the VIP Data Concierge.
Receives requests, extracts user identity from IAP headers,
resolves department, and routes to the correct agent.
"""

import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from agent import run_agent
from config import USER_DEPARTMENT_MAP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/query": {"origins": "*"}}, allow_headers=["Content-Type", "X-User-Email"])


def get_user_department(headers) -> tuple[str, str]:
    """
    Extract user identity from IAP headers and resolve department.
    IAP sets 'X-Goog-Authenticated-User-Email' after authentication.
    Returns (department, user_email) or raises ValueError.
    """
    # IAP header format: "accounts.google.com:user@example.com"
    iap_email_header = headers.get("X-Goog-Authenticated-User-Email", "")

    if iap_email_header:
        user_email = iap_email_header.split(":")[-1]
    else:
        # Fallback for testing: check custom header
        user_email = headers.get("X-User-Email", "")

    if not user_email:
        raise ValueError("No authenticated user identity found in request headers.")

    department = USER_DEPARTMENT_MAP.get(user_email)
    if not department:
        raise ValueError(
            f"User '{user_email}' is not mapped to any department. "
            f"Contact your administrator."
        )

    return department, user_email


@app.route("/query", methods=["POST"])
def query():
    """
    Main endpoint. Expects JSON: {"question": "your question here"}
    User identity comes from IAP headers (or X-User-Email for testing).
    """
    try:
        department, user_email = get_user_department(request.headers)
    except ValueError as e:
        logger.warning(f"Auth error: {e}")
        return jsonify({"error": str(e)}), 401

    body = request.get_json(silent=True)
    if not body or "question" not in body:
        return jsonify({"error": "Request body must include 'question' field."}), 400

    question = body["question"].strip()
    if not question:
        return jsonify({"error": "Question cannot be empty."}), 400

    logger.info(f"Query from {user_email} ({department}): {question}")

    try:
        answer = run_agent(department, question)
        return jsonify({
            "answer": answer,
            "department": department,
            "user": user_email,
        })
    except Exception as e:
        logger.error(f"Agent error for {user_email}: {e}")
        return jsonify({"error": f"Agent error: {e}"}), 500


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint for Cloud Run."""
    return jsonify({"status": "healthy", "service": "vip-data-concierge"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
