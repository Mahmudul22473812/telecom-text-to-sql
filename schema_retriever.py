import json
import math
from functools import lru_cache

import ollama

from schema_metadata import SCHEMA_METADATA


EMBEDDING_MODEL = "nomic-embed-text"
RERANK_MODEL = "llama3.2"


# --------------------------------------------------
# Cosine similarity
# --------------------------------------------------

def cosine_similarity(vector_a, vector_b):

    dot_product = sum(
        a * b
        for a, b in zip(vector_a, vector_b)
    )

    magnitude_a = math.sqrt(
        sum(a * a for a in vector_a)
    )

    magnitude_b = math.sqrt(
        sum(b * b for b in vector_b)
    )

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (
        magnitude_a * magnitude_b
    )


# --------------------------------------------------
# Generate embedding
# --------------------------------------------------

@lru_cache(maxsize=512)
def get_embedding(text):

    response = ollama.embed(
        model=EMBEDDING_MODEL,
        input=text
    )

    return tuple(response["embeddings"][0])


# --------------------------------------------------
# First stage: semantic retrieval
# --------------------------------------------------

def retrieve_candidate_columns(question, top_k=12):

    question_embedding = get_embedding(question)

    scored_columns = []

    for column_name, metadata in SCHEMA_METADATA.items():

        description = metadata["description"]

        schema_text = (
            f"Column: {column_name}. "
            f"Meaning: {description}"
        )

        column_embedding = get_embedding(
            schema_text
        )

        similarity = cosine_similarity(
            question_embedding,
            column_embedding
        )

        scored_columns.append(
            {
                "column": column_name,
                "description": description,
                "embedding_score": similarity
            }
        )

    scored_columns.sort(
        key=lambda item: item["embedding_score"],
        reverse=True
    )

    return scored_columns[:top_k]


# --------------------------------------------------
# Second stage: LLM reranking
# --------------------------------------------------

def rerank_columns(question, candidates, top_k=6):

    candidate_text = ""

    for index, item in enumerate(candidates, start=1):

        candidate_text += (
            f"\nCandidate {index}\n"
            f"Column: {item['column']}\n"
            f"Description: {item['description']}\n"
            f"Embedding score: {item['embedding_score']:.4f}\n"
        )

    prompt = f"""
You are a semantic schema reranker for a telecom Text-to-SQL system.

Your job is NOT to generate SQL.

Your job is to determine which database columns directly represent
the concepts expressed in the user's question.

USER QUESTION:

{question}

CANDIDATE COLUMNS:

{candidate_text}

--------------------------------------------------
RANKING PRINCIPLES
--------------------------------------------------

Analyze the meaning of the COMPLETE user question.

Identify the semantic roles required by the question, such as:

- entity being requested
- metric being measured
- aggregation
- filter or condition
- grouping dimension
- ranking criterion
- threshold
- identifier, only when needed for returning individual records

Rank columns according to how directly they represent those roles.

A column that directly represents a requested metric, condition,
grouping dimension, or ranking criterion should rank higher than
a column that is merely technically useful.

IMPORTANT:

Do NOT rank customer_id highly simply because tables may need to
be joined.

Join keys are implementation details.

The purpose of this stage is semantic schema selection,
NOT SQL join planning.

For example, if the question asks:

"What is the average monthly charge of customers who churned?"

The important semantic concepts are:

1. monthly charge
2. churned customers

Therefore columns representing monthly charge and churn status
must rank above customer identifiers.

Likewise, distinguish concepts that sound similar but have
different meanings.

For example:

- monthly charge is not monthly data download
- customer age is not customer tenure
- churn score is not necessarily historical churn
- total charges is not monthly charge

Do NOT infer that a loosely related column is relevant merely
because it describes the same customer.

--------------------------------------------------
RELEVANCE LEVELS
--------------------------------------------------

For every selected column assign one relevance level:

"direct"
    The column directly represents something explicitly requested
    or required by the question.

"supporting"
    The column is useful for interpreting the requested concept,
    but is not the primary representation.

"technical"
    The column is primarily useful for joins or implementation.

Only return columns that have a reasonable role in answering
the question.

Direct columns MUST appear before supporting columns.

Supporting columns MUST appear before technical columns.

--------------------------------------------------
OUTPUT
--------------------------------------------------

Return ONLY valid JSON:

{{
    "ranked_columns": [
        {{
            "column": "table.column",
            "relevance": "direct",
            "reason": "brief semantic reason"
        }}
    ]
}}

Return at most {top_k} columns.

Do not generate SQL.
"""

    response = ollama.chat(
        model=RERANK_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a semantic database schema reranker. "
                    "Rank columns according to their meaning in the "
                    "user question, not SQL implementation convenience."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        format="json",
        options={
            "temperature": 0
        }
    )

    raw_result = response["message"]["content"]

    data = json.loads(raw_result)

    candidate_lookup = {
        item["column"]: item
        for item in candidates
    }

    ranked = []

    for item in data.get("ranked_columns", []):

        column_name = item.get("column")

        if column_name not in candidate_lookup:
            continue

        ranked.append(
            {
                "column": column_name,
                "description": candidate_lookup[
                    column_name
                ]["description"],
                "embedding_score": candidate_lookup[
                    column_name
                ]["embedding_score"],
                "relevance": item.get(
                    "relevance",
                    "supporting"
                ),
                "reason": item.get(
                    "reason",
                    ""
                )
            }
        )

        if len(ranked) >= top_k:
            break

    return ranked


# --------------------------------------------------
# Full retrieval pipeline
# --------------------------------------------------

def retrieve_relevant_columns(
    question,
    candidate_k=12,
    final_k=6
):

    candidates = retrieve_candidate_columns(
        question,
        top_k=candidate_k
    )

    ranked_columns = rerank_columns(
        question,
        candidates,
        top_k=final_k
    )

    return ranked_columns


# --------------------------------------------------
# Manual test
# --------------------------------------------------

if __name__ == "__main__":

    question = input(
        "Enter a question: "
    )

    print(
        "\nRunning semantic retrieval..."
    )

    candidates = retrieve_candidate_columns(
        question,
        top_k=12
    )

    print(
        "\nTop embedding candidates:\n"
    )

    for item in candidates:

        print(
            f"{item['column']} "
            f"({item['embedding_score']:.4f})"
        )

        print(
            f"  {item['description']}"
        )

    print(
        "\nRunning Llama reranking..."
    )

    final_results = rerank_columns(
        question,
        candidates,
        top_k=6
    )

    print(
        "\nFinal Relevant Schema Columns:\n"
    )

    for index, item in enumerate(
        final_results,
        start=1
    ):

        print(
            f"{index}. {item['column']}"
        )

        print(
            f"   Description: "
            f"{item['description']}"
        )

        print(
            f"   Embedding score: "
            f"{item['embedding_score']:.4f}"
        )

        print(
            f"   Relevance: "
            f"{item['relevance']}"
        )

        print(
            f"   Reranker reason: "
            f"{item['reason']}"
        )

        print()
