"""High-confidence semantic parsing for explicit supported questions.

The local language model remains the fallback for requests that require
interpretation or clarification.  This module handles explicit operations
deterministically so common paraphrases cannot silently lose grouping,
filters, comparisons, rankings, or limits.
"""

import re
from typing import Any

from .intent_normalizer import (
    CUSTOMER_NOUN,
    GROUP_DIMENSIONS,
    NUMBER_WORDS,
    _comparison_for_metric,
    _comparison_from_question,
    _find_group_dimension,
    _find_metric,
    _grouping_requested as _is_grouping_expression,
)
from .schema_metadata import normalize_schema_language


COUNT_CUES = (
    r"\bhow many\b",
    r"\bcount\b",
    r"\bnumber of\b",
    r"\bsize of (?:our|the) customer base\b",
    r"\bcustomer base size\b",
    r"\bbreak(?:down| down)\b",
)

AVERAGE_CUES = r"\b(?:average|avg|mean|on average)\b"
SUM_CUES = r"\b(?:sum|combined|in total)\b"
PERCENTAGE_CUES = r"\b(?:percentage|percent|proportion|share)\b"
RANK_HIGH_CUES = r"\b(?:top|highest|greatest|largest|most)\b"
RANK_LOW_CUES = r"\b(?:bottom|lowest|least|smallest|fewest)\b"


def _base_intent(**overrides: Any) -> dict[str, Any]:
    intent: dict[str, Any] = {
        "target_entity": "customers",
        "selected_fields": [],
        "metric": None,
        "aggregation": None,
        "percentage_condition": None,
        "aggregation_filters": [],
        "filters": [],
        "group_by": [],
        "order_by": None,
        "order_direction": None,
        "limit": None,
        "unresolved_slots": [],
        "ambiguity_reasons": [],
        "clarification_question": None,
    }
    intent.update(overrides)
    return intent


def _add_filter(
    filters: list[dict[str, Any]],
    field: str,
    operator: str,
    value: str | int | float,
) -> None:
    existing = next(
        (item for item in filters if item["field"] == field),
        None,
    )
    condition = {
        "field": field,
        "operator": operator,
        "value": value,
    }
    if existing is None:
        filters.append(condition)
    else:
        existing.update(condition)


def _extract_explicit_filters(question: str) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []

    if re.search(
        r"\bchurned\b|\bleft (?:the company|us)\b|"
        r"\bdiscontinued (?:their )?service\b",
        question,
    ):
        _add_filter(filters, "status.churn_value", "=", 1)
    elif re.search(r"\b(?:did not churn|not churned|non[- ]churned)\b", question):
        _add_filter(filters, "status.churn_value", "=", 0)

    status_values = {
        "stayed": "Stayed",
        "joined": "Joined",
    }
    for phrase, value in status_values.items():
        if re.search(rf"\b{phrase}\b", question):
            _add_filter(filters, "status.customer_status", "=", value)

    contract_values = (
        (r"\bmonth[- ]to[- ]month\b", "Month-to-Month"),
        (r"\bone[- ]year(?: contract)?\b", "One Year"),
        (r"\btwo[- ]year(?: contract)?\b", "Two Year"),
    )
    for pattern, value in contract_values:
        if re.search(pattern, question):
            _add_filter(filters, "services.contract", "=", value)

    internet_type_values = (
        (r"\bfiber optic\b", "Fiber Optic"),
        (r"\bdsl\b", "DSL"),
        (r"\bcable\b", "Cable"),
    )
    for pattern, value in internet_type_values:
        if re.search(pattern, question):
            _add_filter(filters, "services.internet_type", "=", value)

    if re.search(
        r"\b(?:internet customers?|customers? (?:with|using|who use|who have) "
        r"internet|have internet service|using internet service)\b",
        question,
    ):
        _add_filter(filters, "services.internet_service", "=", "Yes")
    elif re.search(
        r"\b(?:without|no) internet service\b|\bdo not have internet\b",
        question,
    ):
        _add_filter(filters, "services.internet_service", "=", "No")

    if re.search(r"\bfemale customers?\b|\bwomen customers?\b", question):
        _add_filter(filters, "demographics.gender", "=", "Female")
    elif re.search(r"\bmale customers?\b|\bmen customers?\b", question):
        _add_filter(filters, "demographics.gender", "=", "Male")

    if re.search(r"\b(?:are|who are|is) married\b|\bmarried customers?\b", question):
        _add_filter(filters, "demographics.married", "=", "Yes")
    elif re.search(r"\bnot married\b|\bunmarried customers?\b", question):
        _add_filter(filters, "demographics.married", "=", "No")

    if re.search(r"\b(?:have|has|with) dependents\b", question):
        _add_filter(filters, "demographics.dependents", "=", "Yes")
    elif re.search(r"\b(?:without|no) dependents\b", question):
        _add_filter(filters, "demographics.dependents", "=", "No")

    metric = _find_metric(question)
    comparison = _comparison_for_metric(question, metric)
    if metric and comparison:
        operator, value = comparison
        _add_filter(filters, metric, operator, value)

    return filters


def _dimension_phrases(dimension: str) -> list[str]:
    return [
        phrase
        for phrase, column in GROUP_DIMENSIONS.items()
        if column == dimension
    ]


def _grouping_requested(question: str, dimension: str | None) -> bool:
    if _is_grouping_expression(question, dimension):
        return True

    if dimension is None:
        return False

    phrases = _dimension_phrases(dimension)
    phrase_pattern = "(?:" + "|".join(
        re.escape(normalize_schema_language(phrase))
        for phrase in phrases
    ) + ")"
    return bool(
        re.search(
            rf"\bwhich\s+{phrase_pattern}\b.*"
            rf"(?:{RANK_HIGH_CUES}|{RANK_LOW_CUES})",
            question,
        )
    )


def _has_any(question: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, question) for pattern in patterns)


def _sum_requested(
    question: str,
    *,
    has_filters: bool,
    ranking_direction: str | None,
) -> bool:
    if re.search(SUM_CUES, question):
        return True

    # "total" is an aggregation cue when it introduces the requested
    # result, but remains part of fields such as "total revenue" in filters
    # and rankings.
    return bool(
        not has_filters
        and ranking_direction is None
        and re.search(
            r"\b(?:what is|show|calculate|give me)\s+"
            r"(?:the\s+)?total\b",
            question,
        )
    )


def _extract_limit(question: str) -> int | None:
    number_words = "|".join(NUMBER_WORDS)
    patterns = (
        rf"\b(?:top|bottom|first|show|find|list|give me)\s+"
        rf"(?:the\s+)?(\d+|{number_words})\b",
        rf"\b(\d+|{number_words})\s+{CUSTOMER_NOUN}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, question)
        if not match:
            continue
        raw_value = match.group(1)
        return int(raw_value) if raw_value.isdigit() else NUMBER_WORDS[raw_value]
    return None


def _table_name(field: str | None) -> str | None:
    return field.split(".", 1)[0] if field and "." in field else None


def _customer_id(
    dimension: str | None,
    filters: list[dict[str, Any]],
) -> str:
    candidate_fields = [dimension]
    candidate_fields.extend(item["field"] for item in filters)
    for field in candidate_fields:
        table = _table_name(field)
        if table in {"demographics", "location", "services", "status"}:
            return f"{table}.customer_id"
    return "demographics.customer_id"


def _ranking_direction(question: str) -> str | None:
    ranking_text = re.sub(
        r"\bat\s+(?:least|most)\b",
        "",
        question,
    )
    if re.search(r"\b(?:ascending|ascending order)\b", ranking_text):
        return "ASC"
    if re.search(r"\b(?:descending|descending order)\b", ranking_text):
        return "DESC"
    if re.search(RANK_LOW_CUES, ranking_text):
        return "ASC"
    if re.search(RANK_HIGH_CUES, ranking_text):
        return "DESC"
    return None


def parse_explicit_intent(question: str) -> dict[str, Any] | None:
    """Return a complete intent only when the language is explicit."""

    normalized = normalize_schema_language(question)
    filters = _extract_explicit_filters(normalized)
    metric = _find_metric(normalized)
    dimension = _find_group_dimension(normalized)
    grouped = _grouping_requested(normalized, dimension)
    ranking_direction = _ranking_direction(normalized)
    limit = _extract_limit(normalized)

    # Population is one row per ZIP code, so this is a direct ranking rather
    # than a customer grouping through location.
    if (
        re.search(r"\b(?:zip code|zipcode)\b", normalized)
        and re.search(r"\bpopulation\b", normalized)
        and ranking_direction
    ):
        return _base_intent(
            target_entity="zip codes",
            selected_fields=[
                "population.zip_code",
                "population.population",
            ],
            metric="population.population",
            filters=filters,
            order_by="population.population",
            order_direction=ranking_direction,
            limit=limit or 1,
        )

    if re.search(PERCENTAGE_CUES, normalized):
        if len(filters) != 1:
            return None
        percentage_condition = filters[0]
        customer_metric = _customer_id(dimension, filters)
        return _base_intent(
            target_entity=("groups" if grouped else "customers"),
            selected_fields=([dimension] if grouped and dimension else []),
            metric=customer_metric,
            aggregation="PERCENTAGE",
            percentage_condition=percentage_condition,
            filters=[],
            group_by=([dimension] if grouped and dimension else []),
        )

    explicit_count = _has_any(normalized, COUNT_CUES)
    implicit_grouped_count = bool(
        grouped
        and re.search(CUSTOMER_NOUN, normalized)
        and re.search(r"\bfor\s+all\b", normalized)
    )
    ranked_grouped_count = bool(
        grouped
        and ranking_direction
        and filters
        and re.search(CUSTOMER_NOUN, normalized)
    )
    if explicit_count or implicit_grouped_count or ranked_grouped_count:
        customer_metric = _customer_id(dimension, filters)
        count_ranking = ranking_direction if grouped else None
        return _base_intent(
            target_entity=(dimension or "customers"),
            selected_fields=([dimension] if grouped and dimension else []),
            metric=customer_metric,
            aggregation="COUNT",
            filters=([] if grouped else filters),
            aggregation_filters=(filters if grouped else []),
            group_by=([dimension] if grouped and dimension else []),
            order_by=(customer_metric if count_ranking else None),
            order_direction=count_ranking,
            limit=(1 if count_ranking else None),
        )

    customer_metric_ranking = bool(
        metric
        and ranking_direction
        and re.search(CUSTOMER_NOUN, normalized)
    )

    if (
        metric
        and re.search(AVERAGE_CUES, normalized)
        and not customer_metric_ranking
    ):
        return _base_intent(
            target_entity=(dimension or "customers"),
            selected_fields=([dimension] if grouped and dimension else []),
            metric=metric,
            aggregation="AVG",
            filters=filters,
            group_by=([dimension] if grouped and dimension else []),
            order_by=(metric if grouped and ranking_direction else None),
            order_direction=(ranking_direction if grouped else None),
            limit=(1 if grouped and ranking_direction else None),
        )

    if metric and _sum_requested(
        normalized,
        has_filters=bool(filters),
        ranking_direction=ranking_direction,
    ):
        return _base_intent(
            metric=metric,
            aggregation="SUM",
            filters=filters,
            selected_fields=([dimension] if grouped and dimension else []),
            group_by=([dimension] if grouped and dimension else []),
        )

    if metric and ranking_direction:
        asks_for_customer = bool(re.search(CUSTOMER_NOUN, normalized))
        if asks_for_customer:
            singular = bool(re.search(r"\b(?:which|the) customer\b", normalized))
            return _base_intent(
                metric=metric,
                filters=filters,
                order_by=metric,
                order_direction=ranking_direction,
                limit=limit or (1 if singular else None),
            )
        if re.search(r"\bwhat (?:is|was)\b", normalized):
            return _base_intent(
                metric=metric,
                aggregation=("MAX" if ranking_direction == "DESC" else "MIN"),
                filters=filters,
            )

    if (
        filters
        and (
            re.search(
                rf"\b(?:show|list|find|give me|which)\b.*{CUSTOMER_NOUN}",
                normalized,
            )
            or re.match(rf"{CUSTOMER_NOUN}\b", normalized)
        )
    ):
        return _base_intent(
            metric=(metric if _comparison_from_question(normalized) else None),
            filters=filters,
            limit=limit,
        )

    return None
