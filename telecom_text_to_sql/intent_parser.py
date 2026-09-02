import json
import re

from pydantic import BaseModel, Field, field_validator, model_validator

from .model_provider import chat_json
from .schema_metadata import SCHEMA_METADATA
from .schema_retriever import retrieve_relevant_columns





# --------------------------------------------------
# Structured models
# --------------------------------------------------

class FilterCondition(BaseModel):
    field: str | None = None
    operator: str | None = None
    value: str | int | float | bool | None = None

    @model_validator(mode="after")
    def coerce_schema_typed_value(self):
        """Keep numeric database fields numeric if a model emits text."""

        metadata = SCHEMA_METADATA.get(self.field or "", {})
        if (
            metadata.get("data_type") not in {"integer", "number"}
            or not isinstance(self.value, str)
        ):
            return self

        match = re.fullmatch(
            r"\s*\$?(-?\d+(?:\.\d+)?)\s*"
            r"(?:dollars?|years?(?:\s+old)?|months?|gb|points?)?\s*",
            self.value,
            flags=re.IGNORECASE,
        )
        if not match:
            return self

        raw_value = match.group(1)
        if metadata["data_type"] == "integer" and "." not in raw_value:
            self.value = int(raw_value)
        else:
            number = float(raw_value)
            self.value = int(number) if number.is_integer() else number

        return self


class QueryIntent(BaseModel):
    target_entity: str | None = None

    selected_fields: list[str] = Field(default_factory=list)

    metric: str | None = None

    aggregation: str | None = None

    percentage_condition: FilterCondition | None = None

    # Conditions evaluated inside a grouped aggregate rather than in WHERE.
    # This preserves categories whose matching-record count is zero.
    aggregation_filters: list[FilterCondition] = Field(default_factory=list)

    filters: list[FilterCondition] = Field(default_factory=list)

    group_by: list[str] = Field(default_factory=list)

    order_by: str | None = None

    order_direction: str | None = None

    limit: int | str | None = None

    unresolved_slots: list[str] = Field(default_factory=list)

    ambiguity_reasons: list[str] = Field(default_factory=list)

    clarification_question: str | None = None

    @field_validator("percentage_condition", mode="before")
    @classmethod
    def normalize_percentage_condition(cls, value):
        # Small local models sometimes return only the condition's field.
        # Preserve it as a typed partial condition so deterministic
        # normalization can complete or reject it safely.
        if isinstance(value, str):
            return {
                "field": value,
                "operator": None,
                "value": None,
            }

        return value


# --------------------------------------------------
# Parse natural language into structured intent
# --------------------------------------------------

def parse_intent(question):

    # Explicit supported requests are compiled deterministically. This keeps
    # grouping words, filters, comparisons, rankings, and limits from being
    # silently lost by a small local model. Ambiguous language still falls
    # through to the schema-grounded LLM parser below.
    from .semantic_parser import parse_explicit_intent

    explicit_intent = parse_explicit_intent(question)

    if explicit_intent is not None:
        return QueryIntent.model_validate(explicit_intent)

    # --------------------------------------------------
    # Step 1: Retrieve the most relevant schema columns
    # --------------------------------------------------

    relevant_columns = retrieve_relevant_columns(
        question,
        candidate_k=12,
        final_k=6
    )

    relevant_schema_text = ""

    for item in relevant_columns:
        relevant_schema_text += (
            f"\nColumn: {item['column']}\n"
            f"Description: {item['description']}\n"
            f"Relevance: {item['relevance']}\n"
            f"Reason: {item['reason']}\n"
        )

    # --------------------------------------------------
    # Step 2: Build the intent extraction prompt
    # --------------------------------------------------

    prompt = f"""
You are a structured intent parser for a telecom Text-to-SQL system.

Your job is NOT to generate SQL.

Your job is to convert the user's natural-language question into
a complete structured database-query intent.

The schema retrieval stage has already selected the most relevant
database columns for the question.

RELEVANT DATABASE COLUMNS:

{relevant_schema_text}


==================================================
CORE RULES
==================================================

1. Use ONLY columns listed in RELEVANT DATABASE COLUMNS.

2. Never invent a table or column.

3. Map each concept in the user's question to the most semantically
   appropriate retrieved column.

4. Prefer columns marked "direct" over "supporting" or "technical".

5. Technical columns should not become the main metric, filter,
   grouping field, or ranking criterion unless explicitly required.

6. Never invent missing:
   - thresholds
   - filter values
   - ranking metrics
   - time ranges
   - categories
   - limits
   - business definitions

7. A concept is NOT ambiguous merely because several related database
   columns exist. Use the column whose description best matches what
   the user actually said.

8. If the user explicitly specifies a metric, use that metric.

9. If the user explicitly specifies an aggregation such as average,
   count, percentage, total, minimum, or maximum, preserve it.

   "How many customers" explicitly means COUNT customers.

   "Which X has the most customers" explicitly means group by X,
   COUNT customers, order by that count descending, and limit to 1.
   The ranking metric is customer count and is NOT ambiguous.

10. If the user explicitly specifies a grouping category, preserve it.

11. If a filter concept is understood but its required comparison
    value is missing, create the filter with value null.

12. Do not convert vague thresholds into arbitrary values.

13. Do not generate an SQL implementation plan. Represent the
    semantic intent of the user's request.


==================================================
MULTIPLE AMBIGUITY RULE
==================================================

A single question may contain ZERO, ONE, OR MULTIPLE independent
pieces of missing information.

You MUST inspect the ENTIRE question before producing the result.

Do NOT stop after discovering the first ambiguity.

For every independently missing piece of information required to
form one deterministic database query:

1. Preserve the part of the intent that is already known.

2. Add a separate descriptive name to unresolved_slots.

3. Add a corresponding explanation to ambiguity_reasons.

For example, a question may simultaneously contain:

- an undefined ranking criterion
- an undefined numeric threshold

Both MUST appear in unresolved_slots.

Never replace one unresolved issue with another unrelated database
concept.


==================================================
RANKING RULES
==================================================

If the user asks for something such as:

- best
- worst
- top
- most valuable
- least valuable

and the metric used to determine that ranking is not specified,
the ranking itself is understood but the ranking metric is missing.

In that situation:

- metric should remain null if no metric is known
- order_by should remain null
- preserve the implied order direction when possible
- add "ranking_metric" to unresolved_slots

Do NOT automatically choose CLTV, revenue, monthly charge, tenure,
or another field merely because it exists in the schema.


==================================================
THRESHOLD RULES
==================================================

If the user uses a qualitative comparison that requires a numeric
boundary, such as:

- high
- low
- large
- small
- long time
- short time

identify the appropriate schema field but DO NOT invent the threshold.

Create a filter with:

- the appropriate field
- the implied comparison operator when clear
- value = null

Then add a descriptive threshold slot to unresolved_slots.

The unresolved slot should describe the missing value.

Examples:

"high monthly charges"
→ monthly_charge_threshold

"long time" referring to tenure
→ tenure_threshold

"high churn score"
→ churn_score_threshold

The slot should be based on the actual concept in the user's
question, NOT on an unrelated retrieved column.


==================================================
FILTER RULES
==================================================

If both the field and value are clearly specified, the filter is
resolved.

Example:

"customers who churned"

If the retrieved schema contains a binary historical churn indicator
whose description states that 1 represents churned customers, use:

field = that churn indicator
operator = "="
value = 1

Do NOT ask what "churned" means when the schema already defines it.


==================================================
CLARIFICATION RULES
==================================================

If unresolved_slots is empty:

clarification_question must be null.

If unresolved_slots is NOT empty:

clarification_question should ask about ONE unresolved slot at a time.

Ask about the FIRST unresolved slot.

Do NOT attempt to resolve all missing information in one
clarification question.

The remaining unresolved slots MUST still stay in unresolved_slots
so they can be handled in later clarification turns.

The clarification question must refer directly to the user's
missing concept.

Bad:
"Could you clarify the CLTV?"

when the missing information is the threshold for high monthly
charges.

Good:
"What monthly charge should be considered high?"


==================================================
STRUCTURED FIELD MEANINGS
==================================================

target_entity:
The main business entity requested, such as customers,
internet types, cities, contracts, or services.

selected_fields:
Database columns that should be returned.

metric:
The primary measurable field involved in a calculation,
ranking, or comparison.

aggregation:
COUNT, AVG, SUM, MIN, MAX, PERCENTAGE, or null.

percentage_condition:
For a PERCENTAGE aggregation, the condition identifying records in
the numerator. Otherwise null.

aggregation_filters:
Conditions evaluated inside a grouped aggregation. Use these instead
of ordinary filters when counting matching records within every group,
so groups with zero matches remain represented. Otherwise use [].

filters:
Conditions restricting records.

Each filter contains:
- field
- operator
- value

group_by:
Columns used for grouping.

order_by:
Field or metric used for ordering.

order_direction:
ASC, DESC, or null.

limit:
Number of requested results.
If not specified, return null.

unresolved_slots:
ALL independently missing pieces of information required to
create one deterministic query.

ambiguity_reasons:
Explanation for EACH unresolved issue.

clarification_question:
Question for the FIRST unresolved issue only.


==================================================
EXAMPLE 1
==================================================

User question:

"Who are our best customers?"

Output:

{{
    "target_entity": "customers",
    "selected_fields": [],
    "metric": null,
    "aggregation": null,
    "filters": [],
    "group_by": [],
    "order_by": null,
    "order_direction": "DESC",
    "limit": null,
    "unresolved_slots": [
        "ranking_metric"
    ],
    "ambiguity_reasons": [
        "The question does not define what metric represents 'best'."
    ],
    "clarification_question":
        "What metric should be used to rank the best customers?"
}}


==================================================
EXAMPLE 2
==================================================

User question:

"Which internet type has the highest average monthly charge?"

Output:

{{
    "target_entity": "internet types",
    "selected_fields": [
        "services.internet_type"
    ],
    "metric": "services.monthly_charge",
    "aggregation": "AVG",
    "filters": [],
    "group_by": [
        "services.internet_type"
    ],
    "order_by": "services.monthly_charge",
    "order_direction": "DESC",
    "limit": 1,
    "unresolved_slots": [],
    "ambiguity_reasons": [],
    "clarification_question": null
}}


==================================================
EXAMPLE 3
==================================================

User question:

"Which customers have been with us for a long time?"

Output:

{{
    "target_entity": "customers",
    "selected_fields": [],
    "metric": "services.tenure_in_months",
    "aggregation": null,
    "filters": [
        {{
            "field": "services.tenure_in_months",
            "operator": ">",
            "value": null
        }}
    ],
    "group_by": [],
    "order_by": null,
    "order_direction": null,
    "limit": null,
    "unresolved_slots": [
        "tenure_threshold"
    ],
    "ambiguity_reasons": [
        "The phrase 'long time' does not specify the required tenure threshold."
    ],
    "clarification_question":
        "How many months should be considered a long time?"
}}


==================================================
EXAMPLE 4
==================================================

User question:

"What is the average monthly charge of customers who churned?"

Output:

{{
    "target_entity": "customers",
    "selected_fields": [],
    "metric": "services.monthly_charge",
    "aggregation": "AVG",
    "filters": [
        {{
            "field": "status.churn_value",
            "operator": "=",
            "value": 1
        }}
    ],
    "group_by": [],
    "order_by": null,
    "order_direction": null,
    "limit": null,
    "unresolved_slots": [],
    "ambiguity_reasons": [],
    "clarification_question": null
}}


==================================================
EXAMPLE 5 - MULTIPLE UNRESOLVED SLOTS
==================================================

User question:

"Show me the best customers with high monthly charges."

Suppose the retrieved schema contains a monthly-charge field.

There are TWO independent missing pieces of information:

1. "best" does not define the ranking metric.
2. "high monthly charges" does not define the numeric threshold.

Therefore BOTH must be preserved.

Output:

{{
    "target_entity": "customers",
    "selected_fields": [],
    "metric": null,
    "aggregation": null,
    "filters": [
        {{
            "field": "services.monthly_charge",
            "operator": ">",
            "value": null
        }}
    ],
    "group_by": [],
    "order_by": null,
    "order_direction": "DESC",
    "limit": null,
    "unresolved_slots": [
        "ranking_metric",
        "monthly_charge_threshold"
    ],
    "ambiguity_reasons": [
        "The question does not define what metric represents 'best'.",
        "The phrase 'high monthly charges' does not specify a numeric threshold."
    ],
    "clarification_question":
        "What metric should be used to rank the best customers?"
}}

IMPORTANT:

The presence of ranking_metric does NOT remove
monthly_charge_threshold.

The presence of monthly_charge_threshold does NOT remove
ranking_metric.

They represent separate missing pieces of information.


==================================================
FINAL VALIDATION
==================================================

Before returning the JSON, silently verify:

1. Did I inspect the entire question?

2. Did I capture every requested metric?

3. Did I capture every requested filter?

4. Did I capture every requested grouping?

5. Did I capture every requested ranking?

6. Does any qualitative comparison require a missing threshold?

7. Does any ranking require a missing ranking metric?

8. If multiple independent values are missing, did I include ALL
   of them in unresolved_slots?

9. Does every unresolved slot correspond to something actually
   missing from the user's question?

10. Did I avoid creating ambiguity merely because related schema
    columns exist?

11. Does clarification_question ask about the FIRST unresolved
    slot only?

12. Did I use only retrieved schema columns?


Return ONLY valid JSON matching exactly this structure:

{{
    "target_entity": "string or null",
    "selected_fields": [],
    "metric": "string or null",
    "aggregation": "string or null",
    "percentage_condition": null,
    "aggregation_filters": [],
    "filters": [
        {{
            "field": "string or null",
            "operator": "string or null",
            "value": "value or null"
        }}
    ],
    "group_by": [],
    "order_by": "string or null",
    "order_direction": "string or null",
    "limit": null,
    "unresolved_slots": [],
    "ambiguity_reasons": [],
    "clarification_question": "string or null"
}}


USER QUESTION:

{question}
"""

    # --------------------------------------------------
    # Step 3: Ask local Llama model to extract intent
    # --------------------------------------------------

    raw_result = chat_json(
        [
            {
                "role": "system",
                "content": (
                    "You are a schema-grounded structured intent parser. "
                    "Use only retrieved database columns. "
                    "Never invent missing information. "
                    "Inspect the entire question before responding. "
                    "A question may contain multiple independent "
                    "unresolved slots. Preserve all of them."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        local_model="llama3.2",
    )

    # --------------------------------------------------
    # Step 4: Parse returned JSON
    # --------------------------------------------------

    data = json.loads(raw_result)

    # --------------------------------------------------
    # Step 5: Validate with Pydantic
    # --------------------------------------------------

    intent = QueryIntent.model_validate(data)

    # LLMs can still contradict explicit language even at temperature 0.
    # Normalize high-confidence business expressions deterministically.
    from .intent_normalizer import normalize_intent

    return normalize_intent(
        question,
        intent,
    )



# --------------------------------------------------
# Manual test
# --------------------------------------------------

if __name__ == "__main__":

    question = input("Enter a question: ")

    intent = parse_intent(question)

    print("\nStructured Intent:\n")

    print(
        json.dumps(
            intent.model_dump(),
            indent=2
        )
    )
