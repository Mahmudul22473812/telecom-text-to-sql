# Supported question contract

The application is a read-only descriptive Text-to-SQL system for the exposed
telecom schema. Support means that representative paraphrases are compared
with reference SQL by executing both against PostgreSQL.

## Supported operations

- customer counts, with zero, one, or multiple explicit filters;
- grouped customer counts using `by`, `per`, `each`, `every`, `in each`, or
  `-wise` phrasing;
- `AVG`, `SUM`, `MIN`, and `MAX` for an explicitly named numeric metric;
- grouped aggregations and highest/lowest grouped rankings;
- customer rankings with explicit direction and limits;
- customer lists with explicit numeric comparisons;
- conditional percentages for one explicit numerator condition;
- joins across customer demographics, location, services, and status;
- ZIP-code population ranking;
- clarification for undefined rankings, thresholds, and business terms.

## Supported concepts

- dimensions: internet type, contract type, payment method, customer status,
  city, ZIP code, and gender;
- numeric fields: age, tenure, monthly charge, total charges, total revenue,
  monthly GB download, satisfaction score, churn score, CLTV, and population;
- categorical filters: churned/not churned, Stayed, Joined, internet service,
  internet type, contract type, gender, married, and dependents.

Numeric comparisons include prefix and postfix forms such as `above 80`,
`at least 48`, `65 or older`, `30 or younger`, `$50 or less`, and `65+`.
Tenure expressed in years is converted to the database's month unit.

## Explicitly unsupported

- predictions or forecasts;
- future causal explanations;
- INSERT, UPDATE, DELETE, DDL, or administrative requests;
- credentials, secrets, environment files, or server-file access;
- fields and operations not present in the exposed semantic schema;
- HAVING clauses, arbitrary OR logic, subqueries, window functions, and
  multi-metric analytical reports unless added to the contract and tests.

Unsupported requests must be rejected or clarified; they must never be
silently converted into a different query.

## Verification

Run the complete three-pass gate:

```powershell
py -3 evaluation\evaluate_end_to_end.py --runs 3
```

Production modules are organized in `telecom_text_to_sql/`. The source matrix
is `evaluation/comprehensive_cases.json`. New supported
language must be added there with reference SQL before it is advertised.
