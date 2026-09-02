"""Shared PostgreSQL configuration for local and hosted environments."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


def connect_database(database_url: str | None = None):
    """Open PostgreSQL using DATABASE_URL or the legacy DB_* settings."""

    timeout = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
    resolved_url = (
        database_url
        if database_url is not None
        else os.getenv("DATABASE_URL", "")
    ).strip()
    if resolved_url:
        return psycopg.connect(
            resolved_url,
            connect_timeout=timeout,
            application_name="telecom_text_to_sql",
        )

    settings = {
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "host": os.getenv("DB_HOST"),
        "port": os.getenv("DB_PORT"),
    }
    missing = [name for name, value in settings.items() if not value]
    if missing:
        raise RuntimeError(
            "Database configuration is incomplete. Set DATABASE_URL or: "
            + ", ".join(missing)
            + "."
        )

    return psycopg.connect(
        **settings,
        connect_timeout=timeout,
        application_name="telecom_text_to_sql",
    )
