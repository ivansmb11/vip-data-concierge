"""
Database configuration mapping departments to PSC endpoints.
All connections stay within vpc-hub via Private Service Connect.
"""

DATABASE_CONFIG = {
    "hr": {
        "host": "10.0.0.50",
        "port": 5432,
        "database": "hr_data",
        "user": "postgres",
        "password": "hr-secret-2024",
    },
    "finance": {
        "host": "10.0.0.51",
        "port": 5432,
        "database": "fin_data",
        "user": "postgres",
        "password": "fin-secret-2024",
    },
}

# Maps user email domains/patterns to departments
# In production, this would come from IAP headers or an identity provider
USER_DEPARTMENT_MAP = {
    "hr@example.com": "hr",
    "finance@example.com": "finance",
    "admin@example.com": "hr",  # admin can access HR by default
}

PROJECT_ID = "hstia-agent"
LOCATION = "us-central1"
MODEL_NAME = "gemini-2.0-flash"
