import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from .sql_validator import validate_sql


# Load environment variables
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


def execute_query(sql_query):
    """
    Execute a validated SELECT query against PostgreSQL.
    """

    validation = validate_sql(sql_query)

    if not validation.is_valid:
        error_message = "; ".join(validation.errors)
        raise ValueError(f"Unsafe SQL query detected: {error_message}")

    connection = psycopg.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
    )

    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(sql_query)

                rows = cursor.fetchall()

                column_names = [
                    description.name
                    for description in cursor.description
                ]

        return column_names, rows

    finally:
        connection.close()
