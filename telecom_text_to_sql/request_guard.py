"""Reject requests outside the read-only descriptive SQL contract."""

import re


UNSUPPORTED_PATTERNS = (
    (
        r"\b(?:predict|forecast|estimate)\b.*\b(?:future|next|will|churn)\b|"
        r"\bwho will churn\b|\bwill (?:leave|churn)\b",
        "Predictive questions require a trained forecasting model; this system only queries historical data.",
    ),
    (
        r"\bwhy\b.*\b(?:will|would)\b|\bexplain\b.*\bfuture\b",
        "Future causal explanations are not available from the supported database fields.",
    ),
    (
        r"\b(?:delete|drop|update|insert|alter|truncate|create|grant|revoke)\b",
        "Data-changing or administrative requests are not supported; only read-only analysis is allowed.",
    ),
    (
        r"\b(?:passwords?|credentials?|secrets?|api keys?|"
        r"environment variables?|\.env)\b",
        "Credentials and environment secrets cannot be queried or disclosed.",
    ),
    (
        r"\bignore\b.*\b(?:rules|instructions|system prompt)\b",
        "Prompt-injection requests that attempt to override system rules are not supported.",
    ),
)


def unsupported_reason(question: str) -> str | None:
    normalized = " ".join(question.lower().split())
    for pattern, reason in UNSUPPORTED_PATTERNS:
        if re.search(pattern, normalized):
            return reason
    return None
