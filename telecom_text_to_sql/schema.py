DATABASE_SCHEMA = """
PostgreSQL database for a telecommunications company.

TABLE: demographics
- customer_id VARCHAR PRIMARY KEY
- count INTEGER
- gender VARCHAR
- age INTEGER
- under_30 VARCHAR
- senior_citizen VARCHAR
- married VARCHAR
- dependents VARCHAR
- number_of_dependents INTEGER

TABLE: location
- location_id VARCHAR PRIMARY KEY
- customer_id VARCHAR
- count INTEGER
- country VARCHAR
- state VARCHAR
- city VARCHAR
- zip_code INTEGER
- lat_long VARCHAR
- latitude DOUBLE PRECISION
- longitude DOUBLE PRECISION

TABLE: population
- id INTEGER PRIMARY KEY
- zip_code INTEGER
- population INTEGER

TABLE: services
- service_id VARCHAR PRIMARY KEY
- customer_id VARCHAR
- count INTEGER
- quarter VARCHAR
- referred_a_friend VARCHAR
- number_of_referrals INTEGER
- tenure_in_months INTEGER
- offer VARCHAR
- phone_service VARCHAR
- avg_monthly_long_distance_charges DOUBLE PRECISION
- multiple_lines VARCHAR
- internet_service VARCHAR
- internet_type VARCHAR
- avg_monthly_gb_download INTEGER
- online_security VARCHAR
- online_backup VARCHAR
- device_protection_plan VARCHAR
- premium_tech_support VARCHAR
- streaming_tv VARCHAR
- streaming_movies VARCHAR
- streaming_music VARCHAR
- unlimited_data VARCHAR
- contract VARCHAR
- paperless_billing VARCHAR
- payment_method VARCHAR
- monthly_charge DOUBLE PRECISION
- total_charges DOUBLE PRECISION
- total_refunds DOUBLE PRECISION
- total_extra_data_charges INTEGER
- total_long_distance_charges DOUBLE PRECISION
- total_revenue DOUBLE PRECISION

TABLE: status
- status_id VARCHAR PRIMARY KEY
- customer_id VARCHAR
- count INTEGER
- quarter VARCHAR
- satisfaction_score INTEGER
- customer_status VARCHAR
- churn_label VARCHAR
- churn_value INTEGER
- churn_score INTEGER
- cltv INTEGER
- churn_category VARCHAR
- churn_reason VARCHAR

RELATIONSHIPS:
- demographics.customer_id = location.customer_id
- demographics.customer_id = services.customer_id
- demographics.customer_id = status.customer_id
- location.zip_code = population.zip_code
"""