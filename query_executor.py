import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


# Load environment variables
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)


def is_safe_query(sql_query):
    """
    Allow only read-only SELECT queries.
    """

    cleaned_query = sql_query.strip().lower()

    # Must start with SELECT
    if not cleaned_query.startswith("select"):
        return False

    # Block dangerous SQL keywords
    blocked_keywords = [
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "truncate",
        "create",
        "grant",
        "revoke",
    ]

    for keyword in blocked_keywords:
        if keyword in cleaned_query:
            return False

    return True


def execute_query(sql_query):
    """
    Execute a validated SELECT query against PostgreSQL.
    """

    if not is_safe_query(sql_query):
        raise ValueError("Unsafe SQL query detected.")

    connection = psycopg.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute(sql_query)

            rows = cursor.fetchall()

            column_names = [
                description.name
                for description in cursor.description
            ]

        return column_names, rows

    finally:
        connection.close()