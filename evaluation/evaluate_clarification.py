import json
import sys
from pathlib import Path


# --------------------------------------------------
# Make project root importable
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from clarification import check_ambiguity


# --------------------------------------------------
# Load benchmark questions
# --------------------------------------------------

questions_file = Path(__file__).parent / "questions.json"

with open(questions_file, "r", encoding="utf-8") as file:
    questions = json.load(file)


# --------------------------------------------------
# Evaluation counters
# --------------------------------------------------

total_questions = len(questions)

successful_tests = 0
failed_tests = 0
correct_predictions = 0

clear_total = 0
clear_correct = 0

ambiguous_total = 0
ambiguous_correct = 0


# --------------------------------------------------
# Run evaluation
# --------------------------------------------------

print("\nStarting Local Llama 3.2 Clarification Evaluation...\n")


for item in questions:

    question_id = item["id"]
    question = item["question"]
    expected_type = item["type"]

    expected_ambiguous = expected_type == "ambiguous"

    print("=" * 70)

    try:

        result = check_ambiguity(question)

        successful_tests += 1

        predicted_ambiguous = result["ambiguous"]

        predicted_label = (
            "ambiguous"
            if predicted_ambiguous
            else "clear"
        )

        is_correct = (
            predicted_ambiguous == expected_ambiguous
        )

        if is_correct:
            correct_predictions += 1


        # --------------------------------------------------
        # Clear question statistics
        # --------------------------------------------------

        if expected_type == "clear":

            clear_total += 1

            if is_correct:
                clear_correct += 1


        # --------------------------------------------------
        # Ambiguous question statistics
        # --------------------------------------------------

        elif expected_type == "ambiguous":

            ambiguous_total += 1

            if is_correct:
                ambiguous_correct += 1


        # --------------------------------------------------
        # Print question result
        # --------------------------------------------------

        print(f"Question ID: {question_id}")
        print(f"Question: {question}")
        print(f"Expected: {expected_type}")
        print(f"Predicted: {predicted_label}")

        print(
            "Result:",
            "CORRECT" if is_correct else "WRONG"
        )

        if predicted_ambiguous:

            print(
                "Clarification:",
                result.get("clarification_question")
            )


    except Exception as error:

        failed_tests += 1

        print(f"Question ID: {question_id}")
        print(f"Question: {question}")
        print("ERROR:")
        print(error)


# --------------------------------------------------
# Calculate metrics
# --------------------------------------------------

if successful_tests > 0:

    overall_accuracy = (
        correct_predictions / successful_tests
    ) * 100

else:

    overall_accuracy = 0


if clear_total > 0:

    clear_accuracy = (
        clear_correct / clear_total
    ) * 100

else:

    clear_accuracy = 0


if ambiguous_total > 0:

    ambiguous_accuracy = (
        ambiguous_correct / ambiguous_total
    ) * 100

else:

    ambiguous_accuracy = 0


# --------------------------------------------------
# Final Results
# --------------------------------------------------

print("\n" + "=" * 70)
print("FINAL RESULTS")
print("=" * 70)

print(f"Benchmark Questions: {total_questions}")
print(f"Successfully Evaluated: {successful_tests}")
print(f"Failures: {failed_tests}")

print(
    f"Correct Predictions: "
    f"{correct_predictions}/{successful_tests}"
)

print(
    f"Overall Accuracy: "
    f"{overall_accuracy:.2f}%"
)

print(
    f"Clear Questions Tested: "
    f"{clear_total}"
)

print(
    f"Clear Question Accuracy: "
    f"{clear_accuracy:.2f}%"
)

print(
    f"Ambiguous Questions Tested: "
    f"{ambiguous_total}"
)

print(
    f"Ambiguous Question Accuracy: "
    f"{ambiguous_accuracy:.2f}%"
)