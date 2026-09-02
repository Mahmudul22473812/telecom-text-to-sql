import os
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from telecom_text_to_sql.database import connect_database
from telecom_text_to_sql.database_schema import ensure_database_schema


# --------------------------------------------------
# Load environment variables
# --------------------------------------------------

# --------------------------------------------------
# Dataset file paths
# --------------------------------------------------

datasets = {
    "demographics": PROJECT_ROOT / "data/Telco_customer_churn_demographics.xlsx",
    "population": PROJECT_ROOT / "data/Telco_customer_churn_population.xlsx",
    "location": PROJECT_ROOT / "data/Telco_customer_churn_location.xlsx",
    "services": PROJECT_ROOT / "data/Telco_customer_churn_services.xlsx",
    "status": PROJECT_ROOT / "data/Telco_customer_churn_status.xlsx",
}


# --------------------------------------------------
# Excel column name -> PostgreSQL column name
# --------------------------------------------------

column_mappings = {
    "demographics": {
        "Customer ID": "customer_id",
        "Count": "count",
        "Gender": "gender",
        "Age": "age",
        "Under 30": "under_30",
        "Senior Citizen": "senior_citizen",
        "Married": "married",
        "Dependents": "dependents",
        "Number of Dependents": "number_of_dependents",
    },

    "population": {
        "ID": "id",
        "Zip Code": "zip_code",
        "Population": "population",
    },

    "location": {
        "Location ID": "location_id",
        "Customer ID": "customer_id",
        "Count": "count",
        "Country": "country",
        "State": "state",
        "City": "city",
        "Zip Code": "zip_code",
        "Lat Long": "lat_long",
        "Latitude": "latitude",
        "Longitude": "longitude",
    },

    "services": {
        "Service ID": "service_id",
        "Customer ID": "customer_id",
        "Count": "count",
        "Quarter": "quarter",
        "Referred a Friend": "referred_a_friend",
        "Number of Referrals": "number_of_referrals",
        "Tenure in Months": "tenure_in_months",
        "Offer": "offer",
        "Phone Service": "phone_service",
        "Avg Monthly Long Distance Charges":
            "avg_monthly_long_distance_charges",
        "Multiple Lines": "multiple_lines",
        "Internet Service": "internet_service",
        "Internet Type": "internet_type",
        "Avg Monthly GB Download": "avg_monthly_gb_download",
        "Online Security": "online_security",
        "Online Backup": "online_backup",
        "Device Protection Plan": "device_protection_plan",
        "Premium Tech Support": "premium_tech_support",
        "Streaming TV": "streaming_tv",
        "Streaming Movies": "streaming_movies",
        "Streaming Music": "streaming_music",
        "Unlimited Data": "unlimited_data",
        "Contract": "contract",
        "Paperless Billing": "paperless_billing",
        "Payment Method": "payment_method",
        "Monthly Charge": "monthly_charge",
        "Total Charges": "total_charges",
        "Total Refunds": "total_refunds",
        "Total Extra Data Charges": "total_extra_data_charges",
        "Total Long Distance Charges":
            "total_long_distance_charges",
        "Total Revenue": "total_revenue",
    },

    "status": {
        "Status ID": "status_id",
        "Customer ID": "customer_id",
        "Count": "count",
        "Quarter": "quarter",
        "Satisfaction Score": "satisfaction_score",
        "Customer Status": "customer_status",
        "Churn Label": "churn_label",
        "Churn Value": "churn_value",
        "Churn Score": "churn_score",
        "CLTV": "cltv",
        "Churn Category": "churn_category",
        "Churn Reason": "churn_reason",
    },
}


# --------------------------------------------------
# Import function
# --------------------------------------------------

def import_table(connection, table_name, file_path):
    print(f"\nImporting {table_name}...")

    # Read Excel file
    df = pd.read_excel(file_path)

    # Rename columns to match PostgreSQL
    df = df.rename(columns=column_mappings[table_name])

    # Convert pandas NaN to Python None
    # Psycopg converts None into SQL NULL
    df = df.astype(object).where(pd.notnull(df), None)

    columns = list(df.columns)

    column_string = ", ".join(columns)

    placeholders = ", ".join(["%s"] * len(columns))

    query = f"""
        INSERT INTO {table_name} ({column_string})
        VALUES ({placeholders})
    """

    rows = list(df.itertuples(index=False, name=None))

    with connection.cursor() as cursor:
        cursor.executemany(query, rows)

    connection.commit()

    print(f"{len(df)} rows imported into {table_name}.")


# --------------------------------------------------
# Import all datasets
# --------------------------------------------------

def main():
    # DATABASE_ADMIN_URL is intended only for one-time schema/data setup.
    # The public application should receive a separate read-only DATABASE_URL.
    connection = connect_database(os.getenv("DATABASE_ADMIN_URL") or None)

    try:
        ensure_database_schema(connection)

        # Clear existing data before re-importing
        with connection.cursor() as cursor:
            cursor.execute("""
                TRUNCATE TABLE
                    status,
                    services,
                    location,
                    population,
                    demographics
                RESTART IDENTITY CASCADE;
            """)

        connection.commit()

        print("Existing database data cleared.")

        # Import fresh data
        for table_name, file_path in datasets.items():
            import_table(connection, table_name, file_path)

        print("\nAll datasets imported successfully!")

    except Exception as error:
        connection.rollback()

        print("\nImport failed:")
        print(error)
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()
