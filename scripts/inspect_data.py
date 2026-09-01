import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
data_folder = PROJECT_ROOT / "data"

files = [
    "Telco_customer_churn_demographics.xlsx",
    "Telco_customer_churn_location.xlsx",
    "Telco_customer_churn_population.xlsx",
    "Telco_customer_churn_services.xlsx",
    "Telco_customer_churn_status.xlsx",
]

for file_name in files:
    file_path = data_folder / file_name

    df = pd.read_excel(file_path)

    print("\n" + "=" * 80)
    print(f"FILE: {file_name}")
    print("=" * 80)

    print(f"\nShape: {df.shape}")

    print("\nColumns:")
    print(df.columns.tolist())

    print("\nData Types:")
    print(df.dtypes)

    print("\nFirst 5 Rows:")
    print(df.head())

    print("\nMissing Values:")
    print(df.isnull().sum())
