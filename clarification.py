from intent_parser import parse_intent
from intent_validator import validate_intent


# --------------------------------------------------
# Dynamic clarification check
# --------------------------------------------------

def check_ambiguity(question):
    """
    Determine whether a user question requires clarification.

    The decision is NOT made by directly asking an LLM whether
    the question is ambiguous.

    Instead:

    1. Parse the user's question into a structured database intent.
    2. Validate whether all required information is available.
    3. Request clarification only when the intent is incomplete.
    """

    # --------------------------------------------------
    # Step 1: Parse structured intent
    # --------------------------------------------------

    intent = parse_intent(question)


    # --------------------------------------------------
    # Step 2: Validate intent completeness
    # --------------------------------------------------

    validation = validate_intent(intent)


    # --------------------------------------------------
    # Step 3: Convert validation result into the format
    # expected by the rest of the application
    # --------------------------------------------------

    result = {
        "ambiguous": not validation.is_complete,
        "clarification_question":
            validation.clarification_question,
        "unresolved_slots":
            validation.unresolved_slots,
        "reasons":
            validation.reasons,
        "intent":
            intent
    }

    return result


# --------------------------------------------------
# Manual testing
# --------------------------------------------------

if __name__ == "__main__":

    question = input(
        "Enter a question: "
    )

    result = check_ambiguity(question)

    print("\nClarification Check:\n")

    print(
        f"Requires Clarification: "
        f"{result['ambiguous']}"
    )

    print(
        f"Unresolved Slots: "
        f"{result['unresolved_slots']}"
    )

    print(
        f"Reasons: "
        f"{result['reasons']}"
    )

    print(
        f"Clarification Question: "
        f"{result['clarification_question']}"
    )

    print("\nStructured Intent:\n")

    print(
        result["intent"].model_dump_json(
            indent=2
        )
    )