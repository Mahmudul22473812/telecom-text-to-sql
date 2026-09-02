"""PostgreSQL schema used by the telecom workbook importer."""

from __future__ import annotations


CREATE_TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS demographics (
        customer_id VARCHAR PRIMARY KEY,
        count INTEGER,
        gender VARCHAR,
        age INTEGER,
        under_30 VARCHAR,
        senior_citizen VARCHAR,
        married VARCHAR,
        dependents VARCHAR,
        number_of_dependents INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS population (
        id INTEGER PRIMARY KEY,
        zip_code INTEGER,
        population INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS location (
        location_id VARCHAR PRIMARY KEY,
        customer_id VARCHAR,
        count INTEGER,
        country VARCHAR,
        state VARCHAR,
        city VARCHAR,
        zip_code INTEGER,
        lat_long VARCHAR,
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS services (
        service_id VARCHAR PRIMARY KEY,
        customer_id VARCHAR,
        count INTEGER,
        quarter VARCHAR,
        referred_a_friend VARCHAR,
        number_of_referrals INTEGER,
        tenure_in_months INTEGER,
        offer VARCHAR,
        phone_service VARCHAR,
        avg_monthly_long_distance_charges DOUBLE PRECISION,
        multiple_lines VARCHAR,
        internet_service VARCHAR,
        internet_type VARCHAR,
        avg_monthly_gb_download INTEGER,
        online_security VARCHAR,
        online_backup VARCHAR,
        device_protection_plan VARCHAR,
        premium_tech_support VARCHAR,
        streaming_tv VARCHAR,
        streaming_movies VARCHAR,
        streaming_music VARCHAR,
        unlimited_data VARCHAR,
        contract VARCHAR,
        paperless_billing VARCHAR,
        payment_method VARCHAR,
        monthly_charge DOUBLE PRECISION,
        total_charges DOUBLE PRECISION,
        total_refunds DOUBLE PRECISION,
        total_extra_data_charges INTEGER,
        total_long_distance_charges DOUBLE PRECISION,
        total_revenue DOUBLE PRECISION
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS status (
        status_id VARCHAR PRIMARY KEY,
        customer_id VARCHAR,
        count INTEGER,
        quarter VARCHAR,
        satisfaction_score INTEGER,
        customer_status VARCHAR,
        churn_label VARCHAR,
        churn_value INTEGER,
        churn_score INTEGER,
        cltv INTEGER,
        churn_category VARCHAR,
        churn_reason VARCHAR
    )
    """,
    "CREATE INDEX IF NOT EXISTS location_customer_id_idx "
    "ON location (customer_id)",
    "CREATE INDEX IF NOT EXISTS location_zip_code_idx ON location (zip_code)",
    "CREATE INDEX IF NOT EXISTS population_zip_code_idx "
    "ON population (zip_code)",
    "CREATE INDEX IF NOT EXISTS services_customer_id_idx "
    "ON services (customer_id)",
    "CREATE INDEX IF NOT EXISTS status_customer_id_idx ON status (customer_id)",
)


def ensure_database_schema(connection) -> None:
    """Create missing application tables and join indexes."""

    with connection.cursor() as cursor:
        for statement in CREATE_TABLE_STATEMENTS:
            cursor.execute(statement)
    connection.commit()
