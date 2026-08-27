from collections import deque

from intent_parser import QueryIntent


# --------------------------------------------------
# Table aliases
# --------------------------------------------------

ALIASES = {
    "demographics": "d",
    "services": "s",
    "status": "st",
    "location": "l",
    "population": "p",
}


# --------------------------------------------------
# Known database relationships
# --------------------------------------------------

RELATIONSHIPS = {
    "demographics": {
        "services": "d.customer_id = s.customer_id",
        "status": "d.customer_id = st.customer_id",
        "location": "d.customer_id = l.customer_id",
    },

    "services": {
        "demographics": "s.customer_id = d.customer_id",
    },

    "status": {
        "demographics": "st.customer_id = d.customer_id",
    },

    "location": {
        "demographics": "l.customer_id = d.customer_id",
        "population": "l.zip_code = p.zip_code",
    },

    "population": {
        "location": "p.zip_code = l.zip_code",
    },
}


# --------------------------------------------------
# Parse table.column
# --------------------------------------------------

def parse_column(column):

    if column is None:
        return None, None

    if "." not in column:
        return None, column

    table, column_name = column.split(".", 1)

    return table, column_name


# --------------------------------------------------
# Convert table.column to alias.column
# --------------------------------------------------

def sql_column(column):

    table, column_name = parse_column(column)

    if table is None:
        return column_name

    if table not in ALIASES:
        raise ValueError(
            f"Unknown table in column: {column}"
        )

    return (
        f"{ALIASES[table]}.{column_name}"
    )


# --------------------------------------------------
# Determine required tables
# --------------------------------------------------

def get_required_tables(intent):

    tables = set()

    def add_column(column):

        if not column:
            return

        table, _ = parse_column(column)

        if table:
            tables.add(table)

    for field in intent.selected_fields:
        add_column(field)

    add_column(intent.metric)
    add_column(intent.order_by)

    for field in intent.group_by:
        add_column(field)

    for condition in intent.filters:
        add_column(condition.field)

    if intent.percentage_condition:
        add_column(
            intent.percentage_condition.field
        )

    return tables


# --------------------------------------------------
# Find relationship path
# --------------------------------------------------

def find_path(start, target):

    queue = deque(
        [
            (start, [start])
        ]
    )

    visited = {start}

    while queue:

        current, path = queue.popleft()

        if current == target:
            return path

        for neighbor in RELATIONSHIPS.get(
            current,
            {}
        ):

            if neighbor not in visited:

                visited.add(neighbor)

                queue.append(
                    (
                        neighbor,
                        path + [neighbor]
                    )
                )

    raise ValueError(
        f"No relationship path between "
        f"{start} and {target}"
    )


# --------------------------------------------------
# Build FROM and JOIN clauses
# --------------------------------------------------

def build_from_clause(required_tables):

    if not required_tables:
        raise ValueError(
            "No database table could be determined "
            "from the structured intent."
        )

    required_tables = list(required_tables)

    base_table = required_tables[0]

    from_clause = (
        f"FROM {base_table} "
        f"{ALIASES[base_table]}"
    )

    joined_tables = {
        base_table
    }

    joins = []

    for target_table in required_tables[1:]:

        path = find_path(
            base_table,
            target_table
        )

        for index in range(
            len(path) - 1
        ):

            current = path[index]
            next_table = path[index + 1]

            if next_table in joined_tables:
                continue

            condition = RELATIONSHIPS[
                current
            ][next_table]

            joins.append(
                f"JOIN {next_table} "
                f"{ALIASES[next_table]} "
                f"ON {condition}"
            )

            joined_tables.add(
                next_table
            )

    if joins:

        from_clause += (
            "\n"
            + "\n".join(joins)
        )

    return from_clause


# --------------------------------------------------
# Format SQL values
# --------------------------------------------------

def format_value(value):

    if value is None:
        return "NULL"

    if isinstance(value, bool):

        return (
            "TRUE"
            if value
            else "FALSE"
        )

    if isinstance(
        value,
        (int, float)
    ):
        return str(value)

    escaped = str(value).replace(
        "'",
        "''"
    )

    return f"'{escaped}'"


# --------------------------------------------------
# Build SELECT clause
# --------------------------------------------------

def build_select(intent):

    selected = []


    # --------------------------------------------------
    # Explicit selected fields
    # --------------------------------------------------

    for field in intent.selected_fields:

        field_sql = sql_column(field)

        if field_sql not in selected:
            selected.append(field_sql)


    # --------------------------------------------------
    # Aggregated metric
    # --------------------------------------------------

    if (
        intent.aggregation
        and intent.aggregation.upper() == "PERCENTAGE"
        and intent.percentage_condition
    ):

        condition = intent.percentage_condition
        condition_field = sql_column(
            condition.field
        )
        condition_operator = (
            condition.operator
            or "="
        ).upper()
        condition_value = format_value(
            condition.value
        )

        expression = (
            "100.0 * SUM(CASE WHEN "
            f"{condition_field} "
            f"{condition_operator} "
            f"{condition_value} "
            "THEN 1 ELSE 0 END) "
            "/ NULLIF(COUNT(*), 0) "
            "AS percentage_of_customers"
        )

        selected.append(
            expression
        )


    # --------------------------------------------------
    # Other aggregated metrics
    # --------------------------------------------------

    elif (
        intent.aggregation
        and intent.metric
    ):

        aggregation = (
            intent.aggregation.upper()
        )

        metric_sql = sql_column(
            intent.metric
        )

        _, metric_name = parse_column(
            intent.metric
        )

        alias = (
            f"{aggregation.lower()}_"
            f"{metric_name}"
        )

        expression = (
            f"{aggregation}"
            f"({metric_sql}) "
            f"AS {alias}"
        )

        if expression not in selected:
            selected.append(expression)


    # --------------------------------------------------
    # Non-aggregated metric
    # --------------------------------------------------

    elif intent.metric:

        metric_sql = sql_column(
            intent.metric
        )

        metric_table, _ = parse_column(
            intent.metric
        )

        if (
            intent.target_entity
            and "customer"
            in intent.target_entity.lower()
            and metric_table
            in {
                "demographics",
                "services",
                "status",
                "location",
            }
        ):

            customer_id = (
                f"{ALIASES[metric_table]}"
                ".customer_id"
            )

            if customer_id not in selected:
                selected.append(customer_id)

        if metric_sql not in selected:
            selected.append(metric_sql)


    # --------------------------------------------------
    # Customer-list fallback
    # --------------------------------------------------

    if not selected:

        if (
            intent.target_entity
            and "customer"
            in intent.target_entity.lower()
        ):

            relevant_fields = []

            for condition in intent.filters:

                if not condition.field:
                    continue

                table, _ = parse_column(
                    condition.field
                )

                if table in {
                    "demographics",
                    "services",
                    "status",
                    "location",
                }:

                    customer_id = (
                        f"{ALIASES[table]}"
                        ".customer_id"
                    )

                    if (
                        customer_id
                        not in relevant_fields
                    ):
                        relevant_fields.append(
                            customer_id
                        )

                    filter_field = (
                        sql_column(
                            condition.field
                        )
                    )

                    if (
                        filter_field
                        not in relevant_fields
                    ):
                        relevant_fields.append(
                            filter_field
                        )

            if relevant_fields:
                selected.extend(
                    relevant_fields
                )

            else:
                selected.append("*")

        else:
            selected.append("*")


    return ", ".join(selected)


# --------------------------------------------------
# Build WHERE clause
# --------------------------------------------------

def build_where(intent):

    conditions = []

    for condition in intent.filters:

        if not condition.field:
            continue

        field_sql = sql_column(
            condition.field
        )

        operator = (
            condition.operator
            or "="
        ).upper()


        # --------------------------------------------------
        # Operators without values
        # --------------------------------------------------

        if operator in {
            "IS NULL",
            "IS NOT NULL",
        }:

            conditions.append(
                f"{field_sql} {operator}"
            )

            continue


        # --------------------------------------------------
        # Normal comparison
        # --------------------------------------------------

        value_sql = format_value(
            condition.value
        )

        conditions.append(
            f"{field_sql} "
            f"{operator} "
            f"{value_sql}"
        )


    if not conditions:
        return ""

    return (
        "WHERE "
        + " AND ".join(
            conditions
        )
    )


# --------------------------------------------------
# Apply sensible default ordering
# --------------------------------------------------

def apply_default_ordering(intent):

    if intent.order_by:
        return


    # --------------------------------------------------
    # Customer threshold queries
    # --------------------------------------------------

    if (
        not intent.aggregation
        and intent.target_entity
        and "customer"
        in intent.target_entity.lower()
    ):

        for condition in intent.filters:

            if not condition.field:
                continue

            operator = (
                condition.operator
                or ""
            ).upper()

            intent.order_by = (
                condition.field
            )

            if operator in {
                ">",
                ">=",
            }:

                intent.order_direction = (
                    "DESC"
                )

            elif operator in {
                "<",
                "<=",
            }:

                intent.order_direction = (
                    "ASC"
                )

            else:

                intent.order_by = None
                intent.order_direction = None

            break


# --------------------------------------------------
# Main deterministic SQL generator
# --------------------------------------------------

def generate_sql_from_intent(
    intent: QueryIntent
):

    # Work on a copy so we do not unexpectedly
    # mutate the original intent.
    working_intent = intent.model_copy(
        deep=True
    )

    if working_intent.aggregation:
        allowed_aggregations = {
            "COUNT",
            "AVG",
            "SUM",
            "MIN",
            "MAX",
            "PERCENTAGE",
        }
        normalized_aggregation = (
            working_intent.aggregation.upper()
        )

        if normalized_aggregation not in allowed_aggregations:
            raise ValueError(
                "Unsupported SQL aggregation: "
                f"{working_intent.aggregation}"
            )

        working_intent.aggregation = normalized_aggregation


    # --------------------------------------------------
    # Add default ordering when useful
    # --------------------------------------------------

    apply_default_ordering(
        working_intent
    )


    # --------------------------------------------------
    # Required tables
    # --------------------------------------------------

    required_tables = (
        get_required_tables(
            working_intent
        )
    )


    # --------------------------------------------------
    # SELECT
    # --------------------------------------------------

    select_clause = (
        "SELECT "
        + build_select(
            working_intent
        )
    )


    # --------------------------------------------------
    # FROM / JOIN
    # --------------------------------------------------

    from_clause = (
        build_from_clause(
            required_tables
        )
    )


    sql_parts = [
        select_clause,
        from_clause,
    ]


    # --------------------------------------------------
    # WHERE
    # --------------------------------------------------

    where_clause = build_where(
        working_intent
    )

    if where_clause:
        sql_parts.append(
            where_clause
        )


    # --------------------------------------------------
    # GROUP BY
    # --------------------------------------------------

    if working_intent.group_by:

        group_fields = [
            sql_column(field)
            for field
            in working_intent.group_by
        ]

        sql_parts.append(
            "GROUP BY "
            + ", ".join(
                group_fields
            )
        )


    # --------------------------------------------------
    # ORDER BY
    # --------------------------------------------------

    if working_intent.order_by:

        order_direction = (
            working_intent.order_direction
            or "ASC"
        ).upper()


        if (
            working_intent.aggregation
            and working_intent.metric
            and working_intent.order_by
            == working_intent.metric
        ):

            order_expression = (
                f"{working_intent.aggregation.upper()}"
                f"({sql_column(working_intent.metric)})"
            )

        else:

            order_expression = (
                sql_column(
                    working_intent.order_by
                )
            )


        sql_parts.append(
            f"ORDER BY "
            f"{order_expression} "
            f"{order_direction}"
        )


    # --------------------------------------------------
    # LIMIT
    # --------------------------------------------------

    limit = working_intent.limit


    if isinstance(
        limit,
        str
    ):

        cleaned_limit = (
            limit.strip()
        )

        if cleaned_limit.isdigit():
            limit = int(
                cleaned_limit
            )

        else:
            limit = None


    # --------------------------------------------------
    # Default limit for customer lists
    # --------------------------------------------------

    if (
        limit is None
        and not working_intent.aggregation
        and working_intent.target_entity
        and "customer"
        in working_intent.target_entity.lower()
    ):

        limit = 20


    if limit is not None:

        sql_parts.append(
            f"LIMIT {limit}"
        )


    # --------------------------------------------------
    # Final SQL
    # --------------------------------------------------

    return (
        "\n".join(sql_parts)
        + ";"
    )
