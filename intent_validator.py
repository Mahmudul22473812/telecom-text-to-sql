from dataclasses import dataclass, field

from intent_parser import QueryIntent


# --------------------------------------------------
# Validation result
# --------------------------------------------------

@dataclass
class ValidationResult:
    is_complete: bool
    unresolved_slots: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    clarification_question: str | None = None


# --------------------------------------------------
# Helper: add issue without duplicates
# --------------------------------------------------

def add_issue(
    unresolved_slots,
    reasons,
    slot,
    reason
):

    if slot not in unresolved_slots:
        unresolved_slots.append(slot)

    if reason not in reasons:
        reasons.append(reason)


# --------------------------------------------------
# Helper: normalize field name
# --------------------------------------------------

def simple_field_name(field_name):

    if not field_name:
        return ""

    if "." in field_name:
        return field_name.split(".", 1)[1]

    return field_name


# --------------------------------------------------
# Helper: detect whether a missing threshold
# is already represented
# --------------------------------------------------

def has_existing_value_slot(
    unresolved_slots,
    field_name
):

    simple_name = simple_field_name(
        field_name
    ).lower()

    for slot in unresolved_slots:

        slot_lower = slot.lower()

        # Example:
        # monthly_charge_threshold
        if (
            simple_name
            and simple_name in slot_lower
        ):
            return True

        # Generic threshold already exists
        if "threshold" in slot_lower:
            return True

    return False


# --------------------------------------------------
# Main validator
# --------------------------------------------------

def validate_intent(
    intent: QueryIntent
) -> ValidationResult:

    unresolved_slots = list(
        intent.unresolved_slots
    )

    reasons = list(
        intent.ambiguity_reasons
    )


    # --------------------------------------------------
    # 1. Validate filters
    # --------------------------------------------------

    for filter_condition in intent.filters:

        field_name = filter_condition.field
        operator = filter_condition.operator
        value = filter_condition.value


        # Completely empty filter
        if (
            field_name is None
            and operator is None
            and value is None
        ):
            continue


        # --------------------------------------------------
        # Missing filter field
        # --------------------------------------------------

        if field_name is None:

            add_issue(
                unresolved_slots,
                reasons,
                "filter_field",
                (
                    "A filter condition exists, "
                    "but its database field is missing."
                )
            )


        # --------------------------------------------------
        # Missing operator
        # --------------------------------------------------

        if operator is None:

            add_issue(
                unresolved_slots,
                reasons,
                "filter_operator",
                (
                    "A filter condition exists, "
                    "but its comparison operator is missing."
                )
            )


        # --------------------------------------------------
        # Operators requiring a value
        # --------------------------------------------------

        value_required_operators = {
            "=",
            "!=",
            "<>",
            ">",
            "<",
            ">=",
            "<=",
            "LIKE",
            "ILIKE",
            "IN",
            "NOT IN",
            "BETWEEN",
        }


        if (
            operator is not None
            and operator.upper()
            in value_required_operators
            and value is None
        ):

            # IMPORTANT:
            # Do not create a second unresolved slot
            # when the parser already identified the
            # same missing threshold/value.
            if not has_existing_value_slot(
                unresolved_slots,
                field_name
            ):

                simple_name = (
                    simple_field_name(
                        field_name
                    )
                )

                if simple_name:

                    slot_name = (
                        f"{simple_name}_value"
                    )

                else:

                    slot_name = (
                        "filter_value"
                    )


                add_issue(
                    unresolved_slots,
                    reasons,
                    slot_name,
                    (
                        f"The filter on "
                        f"{field_name or 'a field'} "
                        "requires a value, "
                        "but no value was provided."
                    )
                )


    # --------------------------------------------------
    # 2. Validate aggregation
    # --------------------------------------------------

    aggregations_requiring_metric = {
        "AVG",
        "SUM",
        "MIN",
        "MAX",
        "PERCENTAGE",
    }


    if intent.aggregation:

        aggregation = (
            intent.aggregation.upper()
        )

        allowed_aggregations = {
            "COUNT",
            "AVG",
            "SUM",
            "MIN",
            "MAX",
            "PERCENTAGE",
        }

        if aggregation not in allowed_aggregations:

            add_issue(
                unresolved_slots,
                reasons,
                "aggregation",
                (
                    f"Unsupported aggregation "
                    f"'{intent.aggregation}'."
                )
            )

        if (
            aggregation
            in aggregations_requiring_metric
            and intent.metric is None
        ):

            add_issue(
                unresolved_slots,
                reasons,
                "metric",
                (
                    f"{aggregation} requires "
                    "a metric, but no metric "
                    "was identified."
                )
            )


    # --------------------------------------------------
    # 2a. Validate percentage calculation
    # --------------------------------------------------

    if (
        intent.aggregation
        and intent.aggregation.upper() == "PERCENTAGE"
        and (
            intent.percentage_condition is None
            or intent.percentage_condition.field is None
            or intent.percentage_condition.operator is None
            or intent.percentage_condition.value is None
        )
    ):

        add_issue(
            unresolved_slots,
            reasons,
            "percentage_condition",
            (
                "PERCENTAGE requires a condition "
                "that defines the numerator."
            )
        )


    # --------------------------------------------------
    # 3. Validate ranking
    # --------------------------------------------------

    if (
        intent.order_direction is not None
        and intent.order_by is None
        and intent.metric is None
    ):

        if (
            "ranking_metric"
            not in unresolved_slots
        ):

            add_issue(
                unresolved_slots,
                reasons,
                "ranking_metric",
                (
                    "The question requests ranking, "
                    "but the ranking metric is missing."
                )
            )


    # --------------------------------------------------
    # 4. Validate limit
    # --------------------------------------------------

    if isinstance(
        intent.limit,
        str
    ):

        cleaned_limit = (
            intent.limit
            .strip()
            .lower()
        )

        allowed_non_numeric_values = {
            "",
            "all",
            "none",
            "null",
        }

        if (
            cleaned_limit
            not in allowed_non_numeric_values
        ):

            try:

                int(cleaned_limit)

            except ValueError:

                add_issue(
                    unresolved_slots,
                    reasons,
                    "limit",
                    (
                        f"The result limit "
                        f"'{intent.limit}' "
                        "is not numeric."
                    )
                )


    # --------------------------------------------------
    # 5. Remove duplicate slots
    # --------------------------------------------------

    unresolved_slots = list(
        dict.fromkeys(
            unresolved_slots
        )
    )

    reasons = list(
        dict.fromkeys(
            reasons
        )
    )


    # --------------------------------------------------
    # 6. Determine completeness
    # --------------------------------------------------

    is_complete = (
        len(unresolved_slots) == 0
    )


    # --------------------------------------------------
    # 7. Generate next clarification question
    # --------------------------------------------------

    clarification_question = None

    if not is_complete:

        clarification_question = (
            build_clarification_question(
                unresolved_slots
            )
        )


    return ValidationResult(
        is_complete=is_complete,
        unresolved_slots=unresolved_slots,
        reasons=reasons,
        clarification_question=
            clarification_question
    )


# --------------------------------------------------
# Dynamic clarification question builder
# --------------------------------------------------

def build_clarification_question(
    unresolved_slots
):

    if not unresolved_slots:
        return None


    # Always ask about ONE unresolved slot
    # at a time.
    slot = unresolved_slots[0]

    slot_lower = slot.lower()


    # --------------------------------------------------
    # Ranking metric
    # --------------------------------------------------

    if slot_lower == "ranking_metric":

        return (
            "What metric should be used "
            "for the ranking?"
        )


    # --------------------------------------------------
    # Threshold
    # --------------------------------------------------

    if "threshold" in slot_lower:

        readable = (
            slot_lower
            .replace("_threshold", "")
            .replace("_", " ")
        )

        return (
            f"What value should be considered "
            f"the threshold for {readable}?"
        )


    # --------------------------------------------------
    # Missing value
    # --------------------------------------------------

    if slot_lower.endswith(
        "_value"
    ):

        readable = (
            slot_lower
            .replace("_value", "")
            .replace("_", " ")
        )

        return (
            f"What value should be used "
            f"for {readable}?"
        )


    # --------------------------------------------------
    # Generic fallback
    # --------------------------------------------------

    readable = (
        slot_lower
        .replace("_", " ")
    )

    return (
        f"Could you clarify the "
        f"{readable}?"
    )


# --------------------------------------------------
# Manual testing
# --------------------------------------------------

if __name__ == "__main__":

    from intent_parser import (
        parse_intent
    )

    question = input(
        "Enter a question: "
    )

    intent = parse_intent(
        question
    )

    validation = validate_intent(
        intent
    )

    print(
        "\nValidation Result:\n"
    )

    print(
        f"Complete: "
        f"{validation.is_complete}"
    )

    print(
        f"Unresolved Slots: "
        f"{validation.unresolved_slots}"
    )

    print(
        f"Reasons: "
        f"{validation.reasons}"
    )

    print(
        f"Clarification Question: "
        f"{validation.clarification_question}"
    )
