from telecom_text_to_sql import run_pipeline


MAX_ROWS_TO_DISPLAY = 20


def request_clarification(question, _intent):
    print("\nClarification needed:\n")
    print(question)
    return input("\nYour answer: ")


def main():
    question = input(
        "Ask a telecom database question: "
    )

    result = run_pipeline(
        question,
        clarification_provider=request_clarification,
        execute=True,
    )

    if result.sql:
        print("\nGenerated SQL:\n")
        print(result.sql)

    if result.status == "success":
        print("\nSQL validation passed.")
        print("\nQuery Result:\n")
        print("Columns:", result.columns)

        if not result.rows:
            print("No results found.")
        else:
            for row in result.rows[:MAX_ROWS_TO_DISPLAY]:
                print(row)

            if len(result.rows) > MAX_ROWS_TO_DISPLAY:
                print(
                    f"\nShowing first {MAX_ROWS_TO_DISPLAY} rows "
                    f"out of {len(result.rows)} total rows."
                )

        print(
            f"\nCompleted in {result.total_latency_ms:.1f} ms."
        )
        return

    if result.status == "sql_rejected":
        print("\nSQL validation failed:")

        for error in result.sql_validation_errors:
            print(f"- {error}")

        return

    if result.status == "needs_clarification":
        print("\nThe request still needs clarification.")
        return

    if result.status == "unsupported":
        print("\nUnsupported request:")
        print(result.error)
        return

    print("\nPipeline failed:")
    print(result.error or "Unknown error")


if __name__ == "__main__":
    main()
