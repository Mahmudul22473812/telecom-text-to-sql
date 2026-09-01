import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from .schema_metadata import normalize_schema_language

if TYPE_CHECKING:
    from .intent_parser import QueryIntent


CUSTOMER_NOUN = (
    r"(?:customers?|subscribers?|accounts?|clients?|users?|people|folks)"
)

GROUP_DIMENSIONS = {
    "payment method": "services.payment_method",
    "payment option": "services.payment_method",
    "contract type": "services.contract",
    "contract plan": "services.contract",
    "contract": "services.contract",
    "internet connection type": "services.internet_type",
    "internet type": "services.internet_type",
    "customer status": "status.customer_status",
    "status": "status.customer_status",
    "city": "location.city",
    "zip code": "location.zip_code",
    "zipcode": "location.zip_code",
    "gender": "demographics.gender",
}

METRIC_CONCEPTS = {
    "customer age": "demographics.age",
    "years old": "demographics.age",
    "aged": "demographics.age",
    "age": "demographics.age",
    "older": "demographics.age",
    "younger": "demographics.age",
    "monthly charge": "services.monthly_charge",
    "monthly charges": "services.monthly_charge",
    "monthly bill": "services.monthly_charge",
    "monthly bills": "services.monthly_charge",
    "total charge": "services.total_charges",
    "total charges": "services.total_charges",
    "total revenue": "services.total_revenue",
    "average monthly gb download": "services.avg_monthly_gb_download",
    "monthly gb download": "services.avg_monthly_gb_download",
    "monthly data download": "services.avg_monthly_gb_download",
    "lifetime value": "status.cltv",
    "cltv": "status.cltv",
    "churn score": "status.churn_score",
    "satisfaction score": "status.satisfaction_score",
    "satisfaction": "status.satisfaction_score",
    "months of tenure": "services.tenure_in_months",
    "tenure": "services.tenure_in_months",
    "months do customers stay": "services.tenure_in_months",
    "staying with us": "services.tenure_in_months",
    "been with us": "services.tenure_in_months",
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
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
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
    question = normalize_schema_language(question)
    for phrase, column in GROUP_DIMENSIONS.items():
        if re.search(rf"\b{re.escape(phrase)}\b", question):
            return column

    return None


def _find_metric(question: str) -> str | None:
    question = normalize_schema_language(question)
    for phrase, column in METRIC_CONCEPTS.items():
        if re.search(
            rf"(?<!\w){re.escape(phrase)}(?!\w)",
            question,
        ):
            return column

    return None


def _grouping_requested(
    question: str,
    dimension: str | None,
) -> bool:
    """Recognize equivalent category-distribution expressions."""

    if dimension is None:
        return False

    question = normalize_schema_language(question)
    phrases = [
        phrase
        for phrase, column in GROUP_DIMENSIONS.items()
        if column == dimension
    ]
    phrase_pattern = "(?:" + "|".join(
        re.escape(normalize_schema_language(phrase))
        for phrase in phrases
    ) + ")"
    category_prefix = r"(?:type|kind|category|option)\s+of\s+(?:the\s+)?"
    patterns = (
        rf"\bby\s+(?:each\s+|every\s+)?{phrase_pattern}\b",
        rf"\bper\s+{phrase_pattern}\b",
        rf"\bfor\s+(?:each|every|all)\s+{phrase_pattern}\b",
        rf"\bin\s+each\s+{phrase_pattern}\b",
        rf"\b(?:each|every|all)\s+{phrase_pattern}\b",
        rf"\b(?:each|every|all)\s+{category_prefix}{phrase_pattern}\b",
        rf"\b{phrase_pattern}\s+wise\b",
        rf"\b{phrase_pattern}\b.*\b(?:breakdown|distribution)\b",
    )
    return any(re.search(pattern, question) for pattern in patterns)


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

    from .intent_parser import FilterCondition

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
    question = normalize_schema_language(question)
    dimension = _find_group_dimension(question)

    if (
        dimension
        and _grouping_requested(question, dimension)
        and re.search(CUSTOMER_NOUN, question)
    ):
        return "grouped"

    scalar_patterns = (
        rf"\bhow many\s+{CUSTOMER_NOUN}\b",
        rf"\b(?:total )?number of\s+{CUSTOMER_NOUN}\b",
        rf"\bcount\s+(?:the\s+)?{CUSTOMER_NOUN}\b",
        rf"\b(?:customer|subscriber|account|client) count\b",
        r"\bsize of (?:our|the) customer base\b",
    )
    grouped_patterns = (
        rf"\blargest number of\s+{CUSTOMER_NOUN}\b",
        rf"\blargest\s+(?:subscriber|customer) base\b",
        rf"\bmost\s+{CUSTOMER_NOUN}\b",
        rf"\bmost common among\s+{CUSTOMER_NOUN}\b",
        rf"\bnumber of\s+{CUSTOMER_NOUN}\s+by\b",
        rf"\b{CUSTOMER_NOUN}\s+count\s+"
        r"(?:for\s+(?:each|every)|per|by)\b",
        rf"\bbreak down (?:the )?number of\s+{CUSTOMER_NOUN}\s+by\b",
        rf"\bhow many\s+{CUSTOMER_NOUN}\b.*"
        r"\b(?:for\s+(?:each|every)|in\s+each|per|by)\b",
        rf"\bcount\s+(?:the\s+)?{CUSTOMER_NOUN}\b.*"
        r"\b(?:for\s+(?:each|every)|in\s+each|per|by)\b",
        rf"\b{CUSTOMER_NOUN}\s+count\b.*\b\w+\s+wise\b",
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
        intent.filters = [
            condition
            for condition in intent.filters
            if not (
                condition.field == dimension
                and condition.value is None
            )
        ]
        # The filters describe which customer records are counted inside
        # each requested group. Keeping them out of WHERE preserves groups
        # whose matching count is zero.
        intent.aggregation_filters = list(intent.filters)
        intent.filters = []
    else:
        intent.aggregation_filters = []
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
    intent.aggregation_filters = []

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


def _normalize_explicit_sum(
    question: str,
    intent: "QueryIntent",
) -> None:
    explicit_sum = re.search(r"\b(?:sum|combined|in total)\b", question)
    leading_total = re.search(
        r"\b(?:what is|show|calculate|give me)\s+(?:the\s+)?total\b",
        question,
    )
    ranking_language = re.search(
        r"\b(?:top|bottom|highest|lowest|largest|smallest|most|least)\b",
        question,
    )
    if not explicit_sum and (not leading_total or ranking_language):
        return

    metric = _find_metric(question)
    if metric is None:
        return

    dimension = _find_group_dimension(question)
    intent.metric = metric
    intent.aggregation = "SUM"
    intent.aggregation_filters = []
    intent.selected_fields = [dimension] if dimension else []
    intent.group_by = [dimension] if dimension else []
    intent.order_by = None
    intent.order_direction = None
    intent.limit = None

    _remove_slots(
        intent,
        lambda slot: slot in {"aggregation", "metric", "ranking_metric"},
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
    number = r"\$?(\d+(?:\.\d+)?)"
    optional_unit = (
        r"(?:\s*(?:years?(?:\s+old)?|months?|gb|points?|dollars?))?"
    )
    comparison_patterns = (
        (rf"\b(?:at least|no less than|minimum of)\s+{number}", ">="),
        (
            rf"\b(?:above|over|more than|greater than|older than)\s+{number}",
            ">",
        ),
        (rf"\b(?:at most|no more than|maximum of)\s+{number}", "<="),
        (
            rf"\b(?:below|under|less than|younger than)\s+{number}",
            "<",
        ),
        (rf"\b(?:exactly|equal to)\s+{number}", "="),
        (
            rf"\b{number}{optional_unit}\s+(?:or|and)\s+"
            r"(?:older|above|higher|more)\b",
            ">=",
        ),
        (
            rf"\b{number}{optional_unit}\s+(?:or|and)\s+"
            r"(?:younger|below|lower|less)\b",
            "<=",
        ),
        (rf"\b{number}{optional_unit}\s*\+", ">="),
    )

    for pattern, operator in comparison_patterns:
        match = re.search(pattern, question)

        if match:
            raw_value = match.group(1)
            value = float(raw_value) if "." in raw_value else int(raw_value)
            return operator, value

    return None


def _comparison_for_metric(
    question: str,
    metric: str | None,
) -> tuple[str, float | int] | None:
    comparison = _comparison_from_question(question)

    if comparison is None:
        return None

    operator, value = comparison
    if (
        metric == "services.tenure_in_months"
        and re.search(r"\b\d+(?:\.\d+)?\s+years?\b", question)
    ):
        value *= 12
        if isinstance(value, float) and value.is_integer():
            value = int(value)

    return operator, value


def _normalize_explicit_threshold(
    question: str,
    intent: "QueryIntent",
) -> None:
    metric = _find_metric(question)
    comparison = _comparison_for_metric(question, metric)

    if comparison is None or metric is None:
        return

    from .intent_parser import FilterCondition

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
        # A comparison chooses rows; it does not imply sorting them.
        intent.order_by = None
        intent.order_direction = None

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

    from .intent_parser import FilterCondition

    intent.target_entity = "customers"
    intent.selected_fields = []
    intent.metric = "services.customer_id"
    intent.aggregation = "PERCENTAGE"
    intent.aggregation_filters = []
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


def _normalize_ambiguous_business_language(
    question: str,
    intent: "QueryIntent",
) -> None:
    """Stabilize known vague concepts without inventing their meaning."""

    from .intent_parser import FilterCondition

    if re.search(rf"\bloyal\s+{CUSTOMER_NOUN}\b", question):
        intent.target_entity = "customers"
        intent.selected_fields = []
        intent.metric = "services.tenure_in_months"
        intent.aggregation = None
        intent.filters = [
            FilterCondition(
                field="services.tenure_in_months",
                operator=">=",
                value=None,
            )
        ]
        intent.group_by = []
        intent.order_by = None
        intent.order_direction = None
        intent.limit = None
        intent.unresolved_slots = ["tenure_threshold"]
        intent.ambiguity_reasons = [
            "The minimum tenure that defines loyalty is not specified."
        ]
        intent.clarification_question = (
            "What minimum tenure in months should define a loyal customer?"
        )
        return

    if re.search(r"\bcontract\b.*\b(?:best|performing best)\b", question):
        intent.target_entity = "contracts"
        intent.selected_fields = ["services.contract"]
        intent.metric = None
        intent.aggregation = None
        intent.filters = []
        intent.group_by = ["services.contract"]
        intent.order_by = None
        intent.order_direction = None
        intent.limit = 1
        intent.unresolved_slots = ["ranking_metric"]
        intent.ambiguity_reasons = [
            "The metric that defines the best contract is not specified."
        ]
        intent.clarification_question = (
            "Which metric should define the best contract type?"
        )
        return

    if re.search(r"\bhigh\s+churn score\b", question):
        intent.target_entity = "customers"
        intent.selected_fields = []
        intent.metric = "status.churn_score"
        intent.aggregation = None
        intent.filters = [
            FilterCondition(
                field="status.churn_score",
                operator=">",
                value=None,
            )
        ]
        intent.group_by = []
        intent.order_by = None
        intent.order_direction = None
        intent.limit = None
        intent.unresolved_slots = ["churn_score_threshold"]
        intent.ambiguity_reasons = [
            "The churn score that should count as high is not specified."
        ]
        intent.clarification_question = (
            "What churn score should be considered high?"
        )
        return

    if re.search(r"\bhealthy\s+(?:customer\s+)?retention\b", question):
        intent.target_entity = "cities"
        intent.selected_fields = ["location.city"]
        intent.metric = None
        intent.aggregation = None
        intent.filters = []
        intent.group_by = ["location.city"]
        intent.order_by = None
        intent.order_direction = None
        intent.limit = 1
        intent.unresolved_slots = ["retention_metric"]
        intent.ambiguity_reasons = [
            "The database measure that defines healthy retention is not specified."
        ]
        intent.clarification_question = (
            "Which metric should define healthy city retention?"
        )
        return

    if re.search(r"\baffordable\s+monthly (?:charge|charges|bill|bills)\b", question):
        intent.target_entity = "customers"
        intent.selected_fields = []
        intent.metric = "services.monthly_charge"
        intent.aggregation = None
        intent.filters = [
            FilterCondition(
                field="services.monthly_charge",
                operator="<=",
                value=None,
            )
        ]
        intent.group_by = []
        intent.order_by = None
        intent.order_direction = None
        intent.limit = None
        intent.unresolved_slots = ["monthly_charge_threshold"]
        intent.ambiguity_reasons = [
            "The maximum monthly charge that counts as affordable is not specified."
        ]
        intent.clarification_question = (
            "What maximum monthly charge should be considered affordable?"
        )
        return

    if re.search(r"\bpayment method\b.*\b(?:effective|effectiveness)\b", question):
        intent.target_entity = "payment methods"
        intent.selected_fields = ["services.payment_method"]
        intent.metric = None
        intent.aggregation = None
        intent.filters = []
        intent.group_by = ["services.payment_method"]
        intent.order_by = None
        intent.order_direction = None
        intent.limit = 1
        intent.unresolved_slots = ["ranking_metric"]
        intent.ambiguity_reasons = [
            "The metric that defines payment-method effectiveness is not specified."
        ]
        intent.clarification_question = (
            "Which metric should define the most effective payment method?"
        )
        return

    if re.search(r"\byoung\s+customers?\b.*\bspend a lot\b", question):
        intent.target_entity = "customers"
        intent.selected_fields = []
        intent.metric = None
        intent.aggregation = None
        intent.filters = [
            FilterCondition(
                field="demographics.age",
                operator="<=",
                value=None,
            )
        ]
        intent.group_by = []
        intent.order_by = None
        intent.order_direction = None
        intent.limit = None
        intent.unresolved_slots = [
            "young_age_threshold",
            "spending_metric",
        ]
        intent.ambiguity_reasons = [
            "The maximum age that counts as young is not specified.",
            "The spending field and threshold are not specified.",
        ]
        intent.clarification_question = (
            "What maximum age should be considered young?"
        )
        return

    if re.search(r"\bpoor\s+service experience\b", question):
        intent.target_entity = "customers"
        intent.selected_fields = []
        intent.metric = None
        intent.aggregation = None
        intent.filters = []
        intent.group_by = []
        intent.order_by = None
        intent.order_direction = None
        intent.limit = None
        intent.unresolved_slots = ["service_experience_metric"]
        intent.ambiguity_reasons = [
            "The database measure that defines poor service experience is not specified."
        ]
        intent.clarification_question = (
            "How should poor service experience be measured, such as by a maximum satisfaction score?"
        )


def normalize_intent(
    question: str,
    intent: "QueryIntent",
) -> "QueryIntent":
    """Apply deterministic schema semantics to an LLM-produced intent."""

    normalized_question = normalize_schema_language(question)
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
    _normalize_explicit_sum(normalized_question, normalized_intent)
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
    _normalize_ambiguous_business_language(
        normalized_question,
        normalized_intent,
    )

    return normalized_intent
