"""
Database access layer.
Routes queries to the correct spoke database based on department.
All connections go through PSC endpoints in vpc-hub.
"""

import psycopg2
from config import DATABASE_CONFIG


class DatabaseAccessError(Exception):
    """Raised when database access fails."""
    pass


class UnauthorizedDepartmentError(Exception):
    """Raised when user tries to access a department they don't belong to."""
    pass


def get_connection(department: str):
    """
    Get a database connection for the given department.
    Routes to the correct PSC endpoint (10.0.0.50 for HR, 10.0.0.51 for Finance).
    """
    dept_key = department.lower()

    if dept_key not in DATABASE_CONFIG:
        raise UnauthorizedDepartmentError(
            f"No database configured for department: {department}. "
            f"Available: {list(DATABASE_CONFIG.keys())}"
        )

    db_config = DATABASE_CONFIG[dept_key]

    try:
        conn = psycopg2.connect(
            host=db_config["host"],
            port=db_config["port"],
            dbname=db_config["database"],
            user=db_config["user"],
            password=db_config["password"],
            connect_timeout=5,
        )
        return conn
    except psycopg2.Error as e:
        raise DatabaseAccessError(
            f"Failed to connect to {dept_key} database at {db_config['host']}: {e}"
        )


def execute_read_query(department: str, query: str) -> list[dict]:
    """
    Execute a read-only query against the department's database.
    Returns rows as a list of dictionaries.
    """
    conn = get_connection(department)
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            return [dict(zip(columns, row)) for row in rows]
    except psycopg2.Error as e:
        raise DatabaseAccessError(f"Query failed on {department} database: {e}")
    finally:
        conn.close()
