import os

from .database import connect_database
from .sql_validator import validate_sql


def execute_query(sql_query):
    """
    Execute a validated SELECT query against PostgreSQL.
    """

    validation = validate_sql(sql_query)

    if not validation.is_valid:
        error_message = "; ".join(validation.errors)
        raise ValueError(f"Unsafe SQL query detected: {error_message}")

    connection = connect_database()

    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                timeout_ms = int(
                    os.getenv("DB_STATEMENT_TIMEOUT_MS", "15000")
                )
                cursor.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(timeout_ms),),
                )
                cursor.execute(sql_query)

                rows = cursor.fetchall()

                column_names = [
                    description.name
                    for description in cursor.description
                ]

        return column_names, rows

    finally:
        connection.close()
