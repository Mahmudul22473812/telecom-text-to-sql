"""Create or update the database role used by the public application."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from psycopg import sql


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from telecom_text_to_sql.database import connect_database


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Set {name} before running this script.")
    return value


def main() -> None:
    admin_url = required_environment("DATABASE_ADMIN_URL")
    reader_user = os.getenv("APP_DB_USER", "telecom_reader").strip()
    reader_password = required_environment("APP_DB_PASSWORD")
    connection = connect_database(admin_url)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)",
                (reader_user,),
            )
            role_exists = cursor.fetchone()[0]

            statement = (
                sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}")
                if role_exists
                else sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {}")
            )
            cursor.execute(
                statement.format(
                    sql.Identifier(reader_user),
                    sql.Literal(reader_password),
                )
            )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(connection.info.dbname),
                    sql.Identifier(reader_user),
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                    sql.Identifier(reader_user)
                )
            )
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}"
                ).format(sql.Identifier(reader_user))
            )
            cursor.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    "GRANT SELECT ON TABLES TO {}"
                ).format(sql.Identifier(reader_user))
            )
        connection.commit()
    finally:
        connection.close()

    print(f"Read-only role {reader_user!r} is ready.")
    print("Use that role's pooled connection URL as DATABASE_URL in Streamlit.")


if __name__ == "__main__":
    main()
