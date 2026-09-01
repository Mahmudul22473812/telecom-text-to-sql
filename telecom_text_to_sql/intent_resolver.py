import re

from .intent_normalizer import CUSTOMER_NOUN, _find_metric
from .intent_parser import QueryIntent
from .schema_retriever import retrieve_relevant_columns


# --------------------------------------------------
# Helper: choose best schema column
# --------------------------------------------------

def choose_best_column(relevant_columns):
    """
    Select the highest-ranked semantically relevant column.

    Preference:
    1. direct
    2. supporting
    3. technical
    """

    if not relevant_columns:
        return None

    direct_columns = [
        item
        for item in relevant_columns
        if item.get("relevance") == "direct"
    ]

    if direct_columns:
        return direct_columns[0]["column"]

    supporting_columns = [
        item
        for item in relevant_columns
        if item.get("relevance") == "supporting"
    ]

    if supporting_columns:
        return supporting_columns[0]["column"]

    return relevant_columns[0]["column"]


# --------------------------------------------------
# Helper: extract numeric value
# --------------------------------------------------

def extract_number(text):
    """
    Examples:

    "48 months"  -> 48
    "above 100"  -> 100
    "$75.50"     -> 75.50
    """

    match = re.search(
        r"-?\d+(?:\.\d+)?",
        text
    )

    if not match:
        return None

    value = match.group()

    if "." in value:
        return float(value)

    return int(value)


# --------------------------------------------------
# Helper: remove one unresolved slot
# --------------------------------------------------

def remove_slot(intent, slot_name):

    intent.unresolved_slots = [
        slot
        for slot in intent.unresolved_slots
        if slot != slot_name
    ]


# --------------------------------------------------
# Helper: remove threshold-related slots
# --------------------------------------------------

def remove_threshold_slots(intent):

    intent.unresolved_slots = [
        slot
        for slot in intent.unresolved_slots
        if (
            "threshold" not in slot.lower()
            and not slot.lower().endswith("_value")
        )
    ]


# --------------------------------------------------
# Main intent resolver
# --------------------------------------------------

def resolve_intent(
    original_question,
    intent: QueryIntent,
    clarification_answer
):

    answer = clarification_answer.strip()
    answer_lower = answer.lower()

    # Work on a copy so the original intent
    # is not modified unexpectedly.
    updated_intent = intent.model_copy(
        deep=True
    )

    # IMPORTANT:
    # The previous clarification question may now
    # be stale after the user answers it.
    #
    # Reset it. The validator will generate the next
    # clarification question if something remains unresolved.
    updated_intent.clarification_question = None

    # Resolve an explicitly requested spending field before applying any
    # numeric value supplied in the same answer.
    if "spending_metric" in updated_intent.unresolved_slots:
        spending_fields = (
            ("monthly charge", "services.monthly_charge"),
            ("monthly bill", "services.monthly_charge"),
            ("total charges", "services.total_charges"),
            ("total revenue", "services.total_revenue"),
        )
        spending_field = next(
            (
                field
                for phrase, field in spending_fields
                if phrase in answer_lower
            ),
            None,
        )
        if spending_field:
            spending_filter = next(
                (
                    condition
                    for condition in updated_intent.filters
                    if condition.field is None
                ),
                None,
            )
            if spending_filter is None:
                from .intent_parser import FilterCondition

                spending_filter = FilterCondition(
                    field=spending_field,
                    operator=">",
                    value=None,
                )
                updated_intent.filters.append(spending_filter)
            else:
                spending_filter.field = spending_field
                spending_filter.operator = ">"
            updated_intent.metric = spending_field
            updated_intent.order_by = None
            updated_intent.order_direction = None
            remove_slot(updated_intent, "spending_metric")
            if "spending_threshold" not in updated_intent.unresolved_slots:
                updated_intent.unresolved_slots.append("spending_threshold")

    if "service_experience_metric" in updated_intent.unresolved_slots:
        if "satisfaction" in answer_lower:
            from .intent_parser import FilterCondition

            updated_intent.metric = "status.satisfaction_score"
            updated_intent.filters = [
                FilterCondition(
                    field="status.satisfaction_score",
                    operator="<=",
                    value=None,
                )
            ]
            remove_slot(updated_intent, "service_experience_metric")
            if "satisfaction_score_threshold" not in updated_intent.unresolved_slots:
                updated_intent.unresolved_slots.append(
                    "satisfaction_score_threshold"
                )


    # --------------------------------------------------
    # Retrieve schema using question + clarification
    # --------------------------------------------------

    retrieval_question = f"""
Original question:
{original_question}

User clarification:
{clarification_answer}
"""

    relevant_columns = retrieve_relevant_columns(
        retrieval_question,
        candidate_k=12,
        final_k=6
    )

    # Resolve the supported city-retention interpretation only when the user
    # explicitly chooses a concrete churned/stayed customer count.
    if "retention_metric" in updated_intent.unresolved_slots:
        from .intent_parser import FilterCondition

        if (
            re.search(r"\b(?:fewest|lowest|least)\b", answer_lower)
            and re.search(r"\b(?:churned|left)\b", answer_lower)
        ):
            updated_intent.selected_fields = ["location.city"]
            updated_intent.metric = "location.customer_id"
            updated_intent.aggregation = "COUNT"
            updated_intent.filters = []
            updated_intent.aggregation_filters = [
                FilterCondition(
                    field="status.churn_value",
                    operator="=",
                    value=1,
                )
            ]
            updated_intent.group_by = ["location.city"]
            updated_intent.order_by = "location.customer_id"
            updated_intent.order_direction = "ASC"
            updated_intent.limit = 1
            remove_slot(updated_intent, "retention_metric")
        elif (
            re.search(r"\b(?:most|highest|largest)\b", answer_lower)
            and re.search(r"\b(?:stayed|retained)\b", answer_lower)
        ):
            updated_intent.selected_fields = ["location.city"]
            updated_intent.metric = "location.customer_id"
            updated_intent.aggregation = "COUNT"
            updated_intent.filters = []
            updated_intent.aggregation_filters = [
                FilterCondition(
                    field="status.customer_status",
                    operator="=",
                    value="Stayed",
                )
            ]
            updated_intent.group_by = ["location.city"]
            updated_intent.order_by = "location.customer_id"
            updated_intent.order_direction = "DESC"
            updated_intent.limit = 1
            remove_slot(updated_intent, "retention_metric")


    # --------------------------------------------------
    # Resolve ranking metric
    # --------------------------------------------------

    if "ranking_metric" in updated_intent.unresolved_slots:
        explicit_metric = _find_metric(answer_lower)
        asks_for_customer_count = bool(
            re.search(
                rf"\b(?:count|number)\b.*{CUSTOMER_NOUN}|"
                rf"\bmost\s+{CUSTOMER_NOUN}\b",
                answer_lower,
            )
        )

        if asks_for_customer_count and updated_intent.group_by:
            group_table = updated_intent.group_by[0].split(".", 1)[0]
            best_column = f"{group_table}.customer_id"
            updated_intent.aggregation = "COUNT"
        else:
            best_column = explicit_metric or choose_best_column(
                relevant_columns
            )

            if re.search(r"\b(?:average|avg|mean)\b", answer_lower):
                updated_intent.aggregation = "AVG"
            elif re.search(r"\b(?:sum|combined)\b", answer_lower):
                updated_intent.aggregation = "SUM"

        if best_column is not None:

            updated_intent.metric = best_column

            updated_intent.order_by = best_column


            # ------------------------------------------
            # Determine ranking direction
            # ------------------------------------------

            descending_words = [
                "highest",
                "most",
                "largest",
                "greatest",
                "top",
                "best"
            ]

            ascending_words = [
                "lowest",
                "least",
                "smallest",
                "worst"
            ]


            if any(
                word in answer_lower
                for word in descending_words
            ):

                updated_intent.order_direction = "DESC"


            elif any(
                word in answer_lower
                for word in ascending_words
            ):

                updated_intent.order_direction = "ASC"


            elif updated_intent.order_direction is None:

                updated_intent.order_direction = "DESC"


            # Ranking metric is now resolved
            remove_slot(
                updated_intent,
                "ranking_metric"
            )


    # --------------------------------------------------
    # Resolve numeric threshold / filter values
    # --------------------------------------------------

    number = extract_number(
        clarification_answer
    )


    if number is not None:

        for filter_condition in updated_intent.filters:

            # Only fill filters whose value is missing
            if filter_condition.value is not None:
                continue

            # Need an actual field to resolve
            if not filter_condition.field:
                continue

            filter_condition.value = number

            if re.search(
                r"\b(?:at least|no less than|minimum)\b",
                answer_lower
            ):
                filter_condition.operator = ">="

            elif re.search(
                r"\b(?:above|over|more than|greater than)\b",
                answer_lower
            ):
                filter_condition.operator = ">"

            elif re.search(
                r"\b(?:at most|no more than|maximum)\b",
                answer_lower
            ):
                filter_condition.operator = "<="

            elif re.search(
                r"\b(?:below|under|less than)\b",
                answer_lower
            ):
                filter_condition.operator = "<"

            # We resolve ONE missing numeric filter
            # with this clarification.
            break


        # Remove threshold-related unresolved slots
        # only if we actually had a numeric answer.
        remove_threshold_slots(
            updated_intent
        )


    # --------------------------------------------------
    # Remove duplicate unresolved slots
    # --------------------------------------------------

    updated_intent.unresolved_slots = list(
        dict.fromkeys(
            updated_intent.unresolved_slots
        )
    )


    # --------------------------------------------------
    # Update ambiguity metadata
    # --------------------------------------------------

    if not updated_intent.unresolved_slots:

        # Everything is resolved
        updated_intent.ambiguity_reasons = []
        updated_intent.clarification_question = None

    else:

        # There are still unresolved issues.
        #
        # Do NOT keep the previous clarification question.
        # validate_intent() will generate the correct next
        # question based on the remaining slots.
        updated_intent.clarification_question = None


    return updated_intent
