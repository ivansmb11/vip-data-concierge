"""
Database configuration mapping departments to PSC endpoints.
All connections stay within vpc-hub via Private Service Connect.
"""

import os

DATABASE_CONFIG = {
    "hr": {
        "host": os.environ.get("HR_DB_HOST", "10.0.0.50"),
        "port": int(os.environ.get("HR_DB_PORT", "5432")),
        "database": os.environ.get("HR_DB_NAME", "hr_data"),
        "user": os.environ.get("HR_DB_USER", "postgres"),
        "password": os.environ.get("HR_DB_PASSWORD", ""),
    },
    "finance": {
        "host": os.environ.get("FIN_DB_HOST", "10.0.0.51"),
        "port": int(os.environ.get("FIN_DB_PORT", "5432")),
        "database": os.environ.get("FIN_DB_NAME", "fin_data"),
        "user": os.environ.get("FIN_DB_USER", "postgres"),
        "password": os.environ.get("FIN_DB_PASSWORD", ""),
    },
}

# Maps user email domains/patterns to departments
# In production, this would come from IAP headers or an identity provider
USER_DEPARTMENT_MAP = {
    "hr@example.com": "hr",
    "finance@example.com": "finance",
    "admin@example.com": "hr",
}

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "hstia-agent")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-2.5-flash")
