from clarification import check_ambiguity
from intent_resolver import resolve_intent
from intent_validator import validate_intent
from query_executor import execute_query
from sql_generator import generate_sql_from_intent


# --------------------------------------------------
# Get user question
# --------------------------------------------------

question = input(
    "Ask a telecom database question: "
)


# --------------------------------------------------
# Run dynamic clarification pipeline
# --------------------------------------------------

try:

    ambiguity_result = check_ambiguity(
        question
    )

except Exception as error:

    print(
        "\nClarification pipeline failed:"
    )

    print(error)

    exit()


# --------------------------------------------------
# If clarification is required
# --------------------------------------------------

if ambiguity_result["ambiguous"]:

    current_intent = ambiguity_result["intent"]

    while True:

        clarification_question = (
            ambiguity_result[
                "clarification_question"
            ]
        )

        print(
            "\nClarification needed:\n"
        )

        print(
            clarification_question
        )

        clarification_answer = input(
            "\nYour answer: "
        )


        # --------------------------------------------------
        # Resolve clarification
        # --------------------------------------------------

        print(
            "\nResolving your clarification..."
        )

        try:

            current_intent = resolve_intent(
                original_question=question,
                intent=current_intent,
                clarification_answer=clarification_answer
            )

        except Exception as error:

            print(
                "\nIntent resolution failed:"
            )

            print(error)

            exit()


        print(
            "Clarification resolved."
        )


        # --------------------------------------------------
        # Validate the updated intent
        # --------------------------------------------------

        validation = validate_intent(
            current_intent
        )


        # --------------------------------------------------
        # If complete, stop asking questions
        # --------------------------------------------------

        if validation.is_complete:

            print(
                "\nIntent is now complete."
            )

            break


        # --------------------------------------------------
        # Otherwise continue clarification loop
        # --------------------------------------------------

        ambiguity_result = {
            "ambiguous": True,
            "clarification_question":
                validation.clarification_question,
            "unresolved_slots":
                validation.unresolved_slots,
            "reasons":
                validation.reasons,
            "intent":
                current_intent
        }


# --------------------------------------------------
# If no clarification is required
# --------------------------------------------------

else:

    current_intent = ambiguity_result[
        "intent"
    ]


# --------------------------------------------------
# Generate SQL deterministically from intent
# --------------------------------------------------

print(
    "\nGenerating SQL from validated intent..."
)

try:

    sql_query = generate_sql_from_intent(
        current_intent
    )

except Exception as error:

    print(
        "\nSQL generation failed:"
    )

    print(error)

    exit()


print(
    "\nGenerated SQL:\n"
)

print(
    sql_query
)


# --------------------------------------------------
# Execute SQL
# --------------------------------------------------

try:

    columns, rows = execute_query(
        sql_query
    )

    print(
        "\nQuery Result:\n"
    )

    print(
        "Columns:",
        columns
    )

    MAX_ROWS_TO_DISPLAY = 20


    # --------------------------------------------------
    # No rows returned
    # --------------------------------------------------

    if len(rows) == 0:

        print(
            "No results found."
        )


    # --------------------------------------------------
    # Small result set
    # --------------------------------------------------

    elif len(rows) <= MAX_ROWS_TO_DISPLAY:

        for row in rows:

            print(row)


    # --------------------------------------------------
    # Large result set
    # --------------------------------------------------

    else:

        for row in rows[
            :MAX_ROWS_TO_DISPLAY
        ]:

            print(row)

        print(
            f"\nShowing first "
            f"{MAX_ROWS_TO_DISPLAY} rows "
            f"out of {len(rows)} total rows."
        )


except Exception as error:

    print(
        "\nQuery execution failed:"
    )

    print(error)