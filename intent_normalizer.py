import re
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from intent_parser import QueryIntent


CUSTOMER_NOUN = r"(?:customers?|subscribers?|accounts?|clients?)"

GROUP_DIMENSIONS = {
    "payment method": "services.payment_method",
    "payment option": "services.payment_method",
    "contract type": "services.contract",
    "contract plan": "services.contract",
    "contract": "services.contract",
    "internet connection type": "services.internet_type",
    "internet type": "services.internet_type",
    "city": "location.city",
}

METRIC_CONCEPTS = {
    "monthly charge": "services.monthly_charge",
    "monthly charges": "services.monthly_charge",
    "monthly bill": "services.monthly_charge",
    "monthly bills": "services.monthly_charge",
    "total revenue": "services.total_revenue",
    "lifetime value": "status.cltv",
    "cltv": "status.cltv",
    "satisfaction score": "status.satisfaction_score",
    "satisfaction": "status.satisfaction_score",
    "tenure": "services.tenure_in_months",
    "months do customers stay": "services.tenure_in_months",
}

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _remove_slots(
    intent: "QueryIntent",
    should_remove: Callable[[str], bool],
) -> None:
    """Remove resolved slots and their positionally matching reasons."""

    old_slots = list(intent.unresolved_slots)
    keep_indexes = [
        index
        for index, slot in enumerate(old_slots)
        if not should_remove(slot.lower())
    ]

    intent.unresolved_slots = [
        old_slots[index]
        for index in keep_indexes
    ]

    if len(intent.ambiguity_reasons) == len(old_slots):
        intent.ambiguity_reasons = [
            intent.ambiguity_reasons[index]
            for index in keep_indexes
        ]
    elif not intent.unresolved_slots:
        intent.ambiguity_reasons = []

    intent.clarification_question = None


def _add_slot(
    intent: "QueryIntent",
    slot: str,
    reason: str,
) -> None:
    if slot not in intent.unresolved_slots:
        intent.unresolved_slots.append(slot)
        intent.ambiguity_reasons.append(reason)

    intent.clarification_question = None


def _table_name(column: str | None) -> str | None:
    if not column or "." not in column:
        return None

    return column.split(".", 1)[0]


def _customer_id_for_intent(intent: "QueryIntent") -> str:
    """Choose a customer identifier from a table already in the intent."""

    columns = list(intent.group_by)
    columns.extend(
        condition.field
        for condition in intent.filters
        if condition.field
    )

    for column in columns:
        table = _table_name(column)

        if table in {
            "demographics",
            "location",
            "services",
            "status",
        }:
            return f"{table}.customer_id"

    return "demographics.customer_id"


def _find_group_dimension(question: str) -> str | None:
    for phrase, column in GROUP_DIMENSIONS.items():
        if re.search(rf"\b{re.escape(phrase)}\b", question):
            return column

    return None


def _find_metric(question: str) -> str | None:
    for phrase, column in METRIC_CONCEPTS.items():
        if phrase in question:
            return column

    return None


def _extract_limit(question: str) -> int | None:
    match = re.search(
        r"\b(?:top|first|show)\s+(?:the\s+)?(\d+)\b",
        question,
    )

    if match:
        return int(match.group(1))

    word_match = re.search(
        r"\b(?:top|first|show)\s+(?:the\s+)?("
        + "|".join(NUMBER_WORDS)
        + r")\b",
        question,
    )

    if word_match:
        return NUMBER_WORDS[word_match.group(1)]

    return None


def _normalize_churned_filter(
    question: str,
    intent: "QueryIntent",
) -> None:
    churn_phrase = re.search(
        r"\bchurned\b|\bleft (?:the company|us)\b|"
        r"\bdiscontinued (?:their )?service\b",
        question,
    )

    if not churn_phrase:
        return

    from intent_parser import FilterCondition

    intent.filters = [
        condition
        for condition in intent.filters
        if not (
            condition.field in {
                "status.churn_score",
                "status.customer_status",
            }
            and (
                condition.value is None
                or str(condition.value).lower() in {"churned", "left"}
            )
        )
    ]

    churn_filter = next(
        (
            condition
            for condition in intent.filters
            if condition.field == "status.churn_value"
        ),
        None,
    )

    if churn_filter is None:
        intent.filters.append(
            FilterCondition(
                field="status.churn_value",
                operator="=",
                value=1,
            )
        )
    else:
        churn_filter.operator = "="
        churn_filter.value = 1

    _remove_slots(
        intent,
        lambda slot: (
            "churn" in slot
            and any(
                concept in slot
                for concept in {
                    "metric",
                    "score",
                    "status",
                    "threshold",
                    "value",
                }
            )
        ),
    )


def _customer_count_kind(question: str) -> str | None:
    scalar_patterns = (
        rf"\bhow many\s+{CUSTOMER_NOUN}\b",
        rf"\b(?:total )?number of\s+{CUSTOMER_NOUN}\b",
        rf"\b(?:customer|subscriber|account|client) count\b",
        r"\bsize of (?:our|the) customer base\b",
    )
    grouped_patterns = (
        rf"\blargest number of\s+{CUSTOMER_NOUN}\b",
        rf"\blargest\s+(?:subscriber|customer) base\b",
        rf"\bmost\s+{CUSTOMER_NOUN}\b",
        rf"\bmost common among\s+{CUSTOMER_NOUN}\b",
        rf"\bnumber of\s+{CUSTOMER_NOUN}\s+by\b",
        rf"\b{CUSTOMER_NOUN}\s+count\s+(?:for each|by)\b",
        rf"\bbreak down (?:the )?number of\s+{CUSTOMER_NOUN}\s+by\b",
    )

    if any(re.search(pattern, question) for pattern in grouped_patterns):
        return "grouped"

    if any(re.search(pattern, question) for pattern in scalar_patterns):
        return "scalar"

    return None


def _normalize_customer_count(
    question: str,
    intent: "QueryIntent",
) -> None:
    count_kind = _customer_count_kind(question)

    if count_kind is None:
        return

    dimension = _find_group_dimension(question)

    if dimension is None and intent.group_by:
        dimension = intent.group_by[0]

    grouped = count_kind == "grouped" and dimension is not None
    has_explicit_filter_language = bool(
        re.search(
            r"\b(?:with|who|that|using|use|have|has|churned|left)\b",
            question,
        )
    )

    if grouped:
        intent.group_by = [dimension]
        intent.selected_fields = [dimension]
        # A grouped customer-count question names the dimension, not a
        # particular dimension value. Small models sometimes invent a
        # null-valued filter for that same column.
        intent.filters = []
    else:
        intent.group_by = []
        intent.selected_fields = []

        if not has_explicit_filter_language:
            intent.filters = []

    intent.aggregation = "COUNT"
    intent.metric = _customer_id_for_intent(intent)

    ranking_count = bool(
        re.search(
            r"\blargest\b|\bmost common\b|"
            rf"\bmost\s+{CUSTOMER_NOUN}\b",
            question,
        )
    )

    if grouped and ranking_count:
        intent.order_by = intent.metric
        intent.order_direction = "DESC"
        intent.limit = 1
    else:
        intent.order_by = None
        intent.order_direction = None

    _remove_slots(
        intent,
        lambda slot: (
            slot in {
                "aggregation",
                "metric",
                "ranking_metric",
            }
            or "count" in slot
            or (
                not has_explicit_filter_language
                and (
                    "filter" in slot
                    or "status" in slot
                    or slot.endswith("_value")
                )
            )
            or (
                grouped
                and (
                    slot.endswith("_value")
                    or "payment_method" in slot
                )
            )
        ),
    )


def _normalize_explicit_average(
    question: str,
    intent: "QueryIntent",
) -> None:
    if not re.search(r"\b(?:average|mean|on average)\b", question):
        return

    metric = _find_metric(question)

    if metric is None:
        return

    dimension = _find_group_dimension(question)
    intent.metric = metric
    intent.aggregation = "AVG"

    if dimension:
        intent.group_by = [dimension]
        intent.selected_fields = [dimension]
    else:
        intent.group_by = []
        intent.selected_fields = []

    if re.search(r"\b(?:highest|greatest|largest)\b", question):
        intent.order_by = metric
        intent.order_direction = "DESC"
        intent.limit = 1
    elif re.search(r"\b(?:lowest|smallest)\b", question):
        intent.order_by = metric
        intent.order_direction = "ASC"
        intent.limit = 1
    else:
        intent.order_by = None
        intent.order_direction = None

    _remove_slots(
        intent,
        lambda slot: (
            slot in {
                "aggregation",
                "metric",
                "ranking_metric",
            }
            or (
                not re.search(
                    r"\b(?:high|low|large|small|long|short|expensive|cheap)\b",
                    question,
                )
                and (
                    "threshold" in slot
                    or slot.endswith("_value")
                )
            )
        ),
    )


def _normalize_explicit_metric_ranking(
    question: str,
    intent: "QueryIntent",
) -> None:
    metric = _find_metric(question)
    ranking_requested = re.search(
        r"\b(?:top|highest|greatest|largest|lowest|least|smallest)\b",
        question,
    )

    if metric is None or not ranking_requested:
        return

    if intent.aggregation and not re.search(CUSTOMER_NOUN, question):
        return

    intent.metric = metric
    intent.aggregation = None
    intent.order_by = metric
    intent.order_direction = (
        "ASC"
        if re.search(r"\b(?:lowest|least|smallest)\b", question)
        else "DESC"
    )
    explicit_limit = _extract_limit(question)

    if explicit_limit is not None:
        intent.limit = explicit_limit

    intent.selected_fields = []
    _remove_slots(
        intent,
        lambda slot: slot in {"metric", "ranking_metric"},
    )


def _comparison_from_question(
    question: str,
) -> tuple[str, float | int] | None:
    comparison_patterns = (
        (r"\b(?:at least|no less than|minimum of)\s+(\d+(?:\.\d+)?)", ">="),
        (r"\b(?:above|over|more than|greater than)\s+(\d+(?:\.\d+)?)", ">"),
        (r"\b(?:at most|no more than|maximum of)\s+(\d+(?:\.\d+)?)", "<="),
        (r"\b(?:below|under|less than)\s+(\d+(?:\.\d+)?)", "<"),
    )

    for pattern, operator in comparison_patterns:
        match = re.search(pattern, question)

        if match:
            raw_value = match.group(1)
            value = float(raw_value) if "." in raw_value else int(raw_value)
            return operator, value

    return None


def _normalize_explicit_threshold(
    question: str,
    intent: "QueryIntent",
) -> None:
    comparison = _comparison_from_question(question)
    metric = _find_metric(question)

    if comparison is None or metric is None:
        return

    from intent_parser import FilterCondition

    operator, value = comparison
    condition = next(
        (
            item
            for item in intent.filters
            if item.field == metric
        ),
        None,
    )

    if condition is None:
        condition = FilterCondition(field=metric)
        intent.filters.append(condition)

    condition.operator = operator
    condition.value = value

    if not intent.aggregation:
        intent.metric = metric
        intent.selected_fields = []
        intent.order_by = metric
        intent.order_direction = (
            "DESC"
            if operator in {">", ">="}
            else "ASC"
        )

    _remove_slots(
        intent,
        lambda slot: (
            "threshold" in slot
            or slot.endswith("_value")
            or slot in {"filter_value", "filter_operator"}
        ),
    )


def _normalize_internet_service_percentage(
    question: str,
    intent: "QueryIntent",
) -> None:
    percentage_pattern = (
        rf"\b(?:percentage|percent)\s+of\s+{CUSTOMER_NOUN}\b"
        r".*\b(?:have|has|with|using|use|are using)\s+internet service\b"
    )

    if not re.search(percentage_pattern, question):
        return

    from intent_parser import FilterCondition

    intent.target_entity = "customers"
    intent.selected_fields = []
    intent.metric = "services.customer_id"
    intent.aggregation = "PERCENTAGE"
    intent.filters = []
    intent.group_by = []
    intent.order_by = None
    intent.order_direction = None
    intent.limit = None
    intent.percentage_condition = FilterCondition(
        field="services.internet_service",
        operator="=",
        value="Yes",
    )
    intent.unresolved_slots = []
    intent.ambiguity_reasons = []
    intent.clarification_question = None


def _normalize_vague_business_language(
    question: str,
    intent: "QueryIntent",
) -> None:
    if re.search(rf"\bpremium\s+{CUSTOMER_NOUN}\b", question):
        intent.filters = []
        intent.metric = None
        intent.order_by = None
        _add_slot(
            intent,
            "premium_customer_definition",
            "The business meaning of a premium customer is not defined.",
        )
        return

    vague_ranking = re.search(
        rf"\b(?:best|strongest|top)\s+{CUSTOMER_NOUN}\b|"
        rf"\bwho are (?:our|the) (?:best|strongest)\s+{CUSTOMER_NOUN}\b",
        question,
    )
    explicit_metric = _find_metric(question)

    if vague_ranking and explicit_metric is None:
        has_bill_threshold = bool(
            re.search(r"\b(?:bill|charge|plan)\b", question)
        )
        intent.metric = None
        intent.order_by = None
        intent.order_direction = "DESC"
        intent.filters = [
            condition
            for condition in intent.filters
            if condition.field == "services.monthly_charge"
            and has_bill_threshold
        ]

        if has_bill_threshold:
            kept_slots = [
                slot
                for slot in intent.unresolved_slots
                if (
                    "monthly" in slot.lower()
                    or "charge" in slot.lower()
                    or "threshold" in slot.lower()
                )
            ]
            intent.unresolved_slots = kept_slots
        else:
            intent.unresolved_slots = []

        intent.ambiguity_reasons = []
        _add_slot(
            intent,
            "ranking_metric",
            "The ranking metric is not defined.",
        )


def normalize_intent(
    question: str,
    intent: "QueryIntent",
) -> "QueryIntent":
    """Apply deterministic schema semantics to an LLM-produced intent."""

    normalized_question = " ".join(question.lower().split())
    normalized_intent = intent.model_copy(deep=True)

    aggregation_aliases = {
        "AVERAGE": "AVG",
        "MEAN": "AVG",
    }

    if normalized_intent.aggregation:
        normalized_intent.aggregation = aggregation_aliases.get(
            normalized_intent.aggregation.upper(),
            normalized_intent.aggregation.upper(),
        )

    _normalize_churned_filter(normalized_question, normalized_intent)
    _normalize_customer_count(normalized_question, normalized_intent)
    _normalize_explicit_average(normalized_question, normalized_intent)
    _normalize_explicit_metric_ranking(
        normalized_question,
        normalized_intent,
    )
    _normalize_explicit_threshold(normalized_question, normalized_intent)
    _normalize_internet_service_percentage(
        normalized_question,
        normalized_intent,
    )
    _normalize_vague_business_language(
        normalized_question,
        normalized_intent,
    )

    return normalized_intent
