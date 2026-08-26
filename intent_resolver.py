import re

from intent_parser import QueryIntent
from schema_retriever import retrieve_relevant_columns


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


    # --------------------------------------------------
    # Resolve ranking metric
    # --------------------------------------------------

    if "ranking_metric" in updated_intent.unresolved_slots:

        best_column = choose_best_column(
            relevant_columns
        )

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