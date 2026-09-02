# Project Journey and Interview Guide

This document explains the Telecom Text-to-SQL project in simple language. It
covers what we built, the problems we discovered, how we solved them, how we
tested the system, and how to explain the project during an interview.

## One-minute project explanation

I built a read-only telecom analytics assistant that converts a user's natural
language question into SQL, safely executes that SQL on PostgreSQL, and shows
the result in a terminal or browser interface.

The difficult part was not simply asking an LLM to write SQL. A model can
misunderstand small wording changes, invent missing information, add unwanted
sorting or limits, create unnecessary joins, or generate unsafe SQL. To make
the system more reliable, I introduced a structured intent between the user's
question and the SQL. The application parses, normalizes, validates, and, when
necessary, clarifies that intent before a deterministic SQL generator creates
the query.

The project combines deterministic rules for clearly supported language with
semantic schema retrieval and a selectable local Ollama or hosted Gemini model
for broader phrasing. It also has SQL safety checks, read-only database
execution, multi-turn clarification, 66 deterministic tests, and an
83-scenario end-to-end evaluation matrix.

## The original goal

The goal was to let a normal user ask questions about telecom customer data
without knowing SQL. Examples include:

```text
How many customers are on each contract type?
Show customers whose monthly charge is above 100.
Which city has the fewest churned customers?
Give me the top 3 clients by total revenue.
```

The system needed to do more than produce SQL. It also needed to:

- understand paraphrases and informal language;
- ask questions when the user's meaning was genuinely incomplete;
- remember answers across multiple clarification turns;
- preserve exact filtering, grouping, ranking, and comparison semantics;
- reject unsafe and unsupported requests;
- verify SQL before execution;
- return correct database results, not merely SQL that looks reasonable.

## Why a direct LLM-to-SQL approach was not enough

At first, the model could answer many ambiguous questions correctly because it
knew when some information was missing. However, it performed much worse on
some clear questions. An early manual check showed roughly 70% overall
accuracy, with about 40% accuracy for the clear-question subset and 100% for
the small ambiguous subset.

This surprising result taught us an important lesson: knowing when to ask a
question is different from understanding a complete question precisely. The
model sometimes asked for information that was already present, or silently
changed the meaning of the request.

Instead of adding a separate fix for every failed sentence, we improved the
correct abstraction layers: schema language, intent parsing, intent
normalization, intent validation, clarification resolution, SQL generation,
execution safety, and evaluation.

## Final architecture

The request passes through these stages:

1. **Request guard** — rejects clearly unsupported or unsafe requests.
2. **Semantic parser** — deterministically recognizes well-defined supported
   patterns such as counts, comparisons, grouping, aggregation, and ranking.
3. **Schema retrieval** — embeds the question and schema descriptions to find
   relevant columns.
4. **Schema reranking** — uses the local model to distinguish direct semantic
   columns from supporting or technical join columns.
5. **Structured intent parsing** — returns typed JSON rather than executable
   SQL.
6. **Intent normalization** — corrects high-confidence semantic details that a
   small model may handle inconsistently.
7. **Intent validation** — identifies genuinely unresolved values or business
   definitions.
8. **Clarification resolver** — applies the user's answer while preserving
   information resolved in earlier turns.
9. **SQL generator** — deterministically compiles the complete intent to SQL.
10. **SQL validator** — accepts only one safe, read-only `SELECT` statement.
11. **Query executor** — validates again and uses a read-only PostgreSQL
    transaction.
12. **Client layer** — presents the result through the CLI or Streamlit UI.

The key design idea is that the model does not directly control database
execution. It helps interpret language, but typed validation and deterministic
code control the final SQL.

## Main data structure: `QueryIntent`

The `QueryIntent` model is the contract between language understanding and SQL
generation. It contains fields such as:

- selected columns;
- metric and aggregation;
- normal row filters;
- filters evaluated inside grouped aggregates;
- grouping dimensions;
- ordering and direction;
- result limit;
- unresolved information;
- ambiguity reasons and a clarification question.

This separation makes failures easier to inspect. If SQL is wrong, we can ask:

1. Did the parser understand the question?
2. Did normalization preserve its meaning?
3. Did validation miss an incomplete field?
4. Did SQL generation compile a correct intent incorrectly?

Without structured intent, all those problems are mixed together inside one
free-form model response.

## Complications and how we handled them

### 1. Clear questions sometimes caused unnecessary clarification

**Problem:**

Questions such as `sum of total revenues` or grouped customer counts sometimes
triggered `What metric should be used for the ranking?` even though the user
had not requested a ranking.

**Root cause:**

Minor parser uncertainty was being represented as a missing ranking metric.
Aggregation language like `sum` or grouping language like `each` was not
always preserved consistently.

**Solution:**

- Represent explicit aggregation and grouping directly in structured intent.
- Normalize high-confidence aggregation words such as `sum`, `total`, `avg`,
  `average`, `mean`, and `count`.
- Make ranking intent depend on real ranking language rather than general model
  uncertainty.
- Let intent validation request clarification only when a required semantic
  slot is actually missing.

**Why it generalizes:**

The rule is based on semantic roles—aggregation, grouping, and ranking—not on
memorizing a complete evaluation sentence.

### 2. Singular and plural wording changed the result

**Problem:**

`sum of total revenue` worked, while `sum of total revenues` could ask an
irrelevant clarification. Similarly, `total charge` and `total charges` could
produce different intents.

**Root cause:**

Small wording differences changed embedding retrieval and model output enough
to select a different schema concept or leave the target table unresolved.

**Solution:**

- Add lightweight domain-level inflection normalization.
- Add genuine schema aliases such as `monthly bill`, `total charge`, and
  `total revenue`.
- Normalize concepts before semantic retrieval while keeping the original
  question for complete intent interpretation.
- Coerce values according to schema types.

**Why it generalizes:**

We normalize reusable domain concepts such as customers, clients, subscribers,
charges, revenues, contracts, methods, cities, and types. We do not store exact
questions.

### 3. Equivalent grouping phrases were interpreted differently

**Problem:**

The system needed to treat the following as equivalent grouping requests:

```text
customers by contract type
customers for every internet type
customers on each type of contract
customer count city wise
customers for all internet connection types
```

Some variations were previously interpreted as a total count or even as an
incomplete ranking.

**Root cause:**

Grouping can be expressed through several grammatical forms, not only the word
`by`.

**Solution:**

Create reusable grouping detection for `by`, `per`, `each`, `every`,
`for each`, `for every`, `-wise`, and category/type wording. Once a grouping
dimension is found, the count or aggregation is compiled with `GROUP BY`.

### 4. The system added `ORDER BY` and `LIMIT 20` without permission

**Problem:**

A request such as `Show customers with monthly charges above 100` should
return all matching customers. The model sometimes added an order and
`LIMIT 20`, changing the result.

**Root cause:**

The model mixed presentation convenience with SQL meaning. It assumed that a
terminal should display only a small number of rows and encoded that choice in
SQL.

**Solution:**

- Generate `ORDER BY` only when the user requests sorting or ranking.
- Generate `LIMIT` only for an explicit result count or ranking that logically
  selects a fixed number, such as `top 3` or `largest`.
- Keep output truncation in the CLI and Streamlit display layer.
- Fetch the complete database result while showing only the selected number of
  rows on screen.

**Lesson:**

Presentation limits and query semantics are different concerns and must remain
separate.

### 5. Numeric values were sometimes quoted as strings

**Problem:**

The model could generate:

```sql
WHERE monthly_charge < '50'
```

instead of:

```sql
WHERE monthly_charge < 50
```

**Root cause:**

The language model represented values as text even when the schema said the
field was numeric.

**Solution:**

Pydantic validation checks schema metadata and converts compatible textual
numbers, currencies, ages, months, and similar units into numeric Python
values. The SQL formatter then quotes strings but not numbers.

### 6. Comparison language had to remain exact

**Problem:**

Small comparison words change query meaning:

- `above 80` means `> 80`;
- `2 or lower` means `<= 2`;
- `at least 48 months` means `>= 48`;
- `30 or younger` means `<= 30`;
- `2 years or more` means `>= 24` months.

**Solution:**

Add deterministic comparison extraction for prefix and postfix wording and
convert tenure years into the schema's month unit. Regression tests ensure
normalization changes do not damage these operators.

### 7. Unnecessary joins made SQL harder and riskier

**Problem:**

Some generated queries joined through `demographics` even when `services` and
`status` could join directly through `customer_id`.

**Root cause:**

The original join planner treated one table as a central bridge instead of
finding the shortest valid path between only the required tables.

**Solution:**

- Determine required tables from the intent.
- Store valid join relationships explicitly.
- Find a join path between required tables.
- Join customer tables directly when possible.
- Keep semantic schema selection separate from technical join planning.

This produces simpler SQL and reduces the chance of accidental row
multiplication or dependency on irrelevant tables.

### 8. Filtering before grouped counting removed zero-count groups

**Problem:**

For `Which city has the fewest churned customers?`, this approach is wrong:

```sql
WHERE churn_value = 1
GROUP BY city
```

It removes every city with zero churned customers before grouping, although
zero is the smallest possible count.

**Root cause:**

The intent did not distinguish between these two meanings:

- filter the entire dataset to matching rows;
- count matching rows inside every group.

**Solution:**

- Add `aggregation_filters` to structured intent.
- Use a `LEFT JOIN` when the matching side must not remove base groups.
- Generate conditional aggregation such as:

```sql
COUNT(CASE WHEN churn_value = 1 THEN 1 END)
```

- Order by that conditional count and apply a ranking limit only when asked.

**Why it generalizes:**

The same representation works for the most, fewest, or zero occurrences of
any supported condition within any supported group.

### 9. Multi-turn clarification could lose earlier answers

**Problem:**

`Find young customers who spend a lot` contains two independent missing
definitions. After answering the age question, the system still needs a
spending definition. A weak implementation can lose the age answer during the
second turn.

**Solution:**

- Detect all unresolved slots in the full question.
- Ask one contextual question at a time.
- Apply each answer to the existing intent instead of reparsing from nothing.
- Preserve previously resolved filters and remove only the resolved slot.
- Keep the original question and clarification-answer list in conversation
  state across Streamlit reruns.

### 10. A small fixed question set did not prove general behavior

**Problem:**

Accuracy measured on only 20 questions could hide overfitting and give false
confidence about real users' paraphrases.

**Solution:**

- Expand evaluation to 83 scenarios across 30 categories.
- Include singular/plural forms, informal wording, grouping variants,
  thresholds, joins, rankings, percentages, multi-turn ambiguity, and unsafe
  requests.
- Compare database rows with reference SQL instead of relying only on exact SQL
  text.
- Allow order-insensitive comparison where SQL row order is not part of the
  request.
- Use numeric tolerance for database numeric types.
- Run the full matrix three times to measure output stability.
- Introduce explicit release gates for accuracy, clarification F1, safety,
  runtime failures, and stability.

During development, the three-run matrix completed 249 evaluations for 83
questions. The deterministic suite currently contains 66 tests. These results
describe the tested contract and environment; they are not a claim that every
possible natural-language question will work.

### 11. Unsafe requests needed to stop before SQL generation

**Problem:**

A Text-to-SQL application must not execute mutations, administrative commands,
credential requests, or prompt-injection instructions.

**Solution:**

Use defense in depth:

1. The request guard rejects unsupported intent before model access.
2. The SQL validator accepts only one `SELECT` statement.
3. It rejects mutation and administrative keywords.
4. It rejects unsafe PostgreSQL functions, `SELECT INTO`, multiple statements,
   and row locks.
5. It understands comments and quoted strings so harmless text does not create
   false positives and hidden SQL does not bypass checks.
6. The executor validates SQL again.
7. The database transaction is explicitly read-only.

### 12. Production code became inconvenient to navigate

**Problem:**

As the project grew, production modules were scattered in the repository root.

**Solution:**

Move them into the `telecom_text_to_sql/` package while keeping thin root-level
entry points for the CLI and Streamlit application. Tests, scripts, evaluation,
and documentation remain in their own folders.

This organization makes imports reusable and prevents interactive terminal
input from running when another module imports the pipeline.

### 13. The terminal interface was not convenient for normal users

**Problem:**

The command-line version worked, but users had to enter one question at a time
and read raw tuple output.

**Solution:**

Build a Streamlit chat interface with:

- conversation history;
- multi-turn clarification;
- result tables and latency information;
- generated SQL and query-detail panels;
- display-only row controls;
- complete CSV downloads;
- clarification cancellation and conversation clearing.

Conversation handling was placed in a framework-independent controller so it
could be tested without a browser.

### 14. Local success did not automatically mean cloud deployment

**Problem:**

The first Streamlit version ran locally, but it depended on PostgreSQL and
Ollama on the same computer. Streamlit Community Cloud cannot connect to the
developer's `localhost`, and `.env` is intentionally not pushed to GitHub.

**Solution:**

- Add a provider boundary so local development can keep Ollama while public
  hosting uses Gemini.
- Support a hosted PostgreSQL `DATABASE_URL` and automatically create the
  schema during the one-time import.
- Create a separate read-only database role for the public application.
- Store credentials in Streamlit Secrets rather than Git.
- Add database connection and statement timeouts.
- Embed the public Streamlit application in the Vercel portfolio.

**Still required for a larger production service:**

- account-level authentication and centralized rate limiting;
- usage budgets, structured logs, monitoring, and health checks;
- a fresh database-backed evaluation run for the selected cloud model.

## How testing is organized

### Unit tests

Unit tests check individual behavior such as:

- intent normalization;
- comparison operators;
- singular/plural equivalence;
- grouped parsing;
- SQL construction;
- conditional aggregation;
- shortest joins;
- clarification resolution;
- request rejection;
- SQL comment, quote, statement, and function safety;
- UI conversation state and initial rendering.

These tests are fast and mostly deterministic because model and database calls
can be replaced with injected test functions.

### Semantic regression tests

Every important bug becomes a general regression test. For example, the tests
do not check only one exact sentence. They compare several equivalent phrases
and assert semantic properties such as:

- no `ORDER BY` or `LIMIT` for unrestricted lists;
- correct `ORDER BY` and `LIMIT` for explicit rankings;
- equivalent intent for singular and plural metrics;
- conditional counting instead of filtering away zero groups;
- numeric values remain numeric;
- irrelevant tables are not joined.

### End-to-end evaluation

The evaluator runs the real pipeline and, where appropriate, executes both the
generated SQL and a reference SQL query. It compares the returned rows and
records classification, clarification, validity, execution accuracy, safety,
latency, failures, and stability.

This is stronger than checking whether two SQL strings look the same because
different SQL statements can return the same correct result.

## Results achieved

The project moved from a small manual test with inconsistent clear-question
behavior to a repeatable verification process:

- **66 out of 66 deterministic tests passed** in the latest local test run.
- **83 end-to-end scenarios** cover 30 behavior categories.
- The verified three-pass development run executed all 83 scenarios three
  times, producing **249 out of 249 passing evaluations**.
- The release gate also checks SQL validity, database-result equivalence,
  clarification quality, unsafe-request rejection, runtime failures, latency,
  and consistency across runs.

These numbers are evidence for the defined and tested support contract. They
should not be presented as 100% accuracy for every sentence a future user
might invent.

## Important engineering decisions

### Why use both rules and an LLM?

Rules are reliable for explicit, supported forms such as comparisons and
grouping quantifiers. The LLM is useful for broader semantic phrasing and
schema relevance. The hybrid approach uses each where it is strongest.

### Why not let the LLM generate final SQL?

Free-form SQL is harder to validate semantically and can contain invented
joins, values, filters, ordering, or unsafe operations. Structured intent gives
the program a typed checkpoint before deterministic SQL generation.

### Why ask clarification questions?

Some business words do not have one universal database meaning. `Loyal`,
`young`, `high churn score`, `best contract`, and `effective payment method`
need a threshold or metric. Guessing would create confident but incorrect SQL.

### Why is clarification validation separate from the model?

The model identifies possible intent, but programmatic validation decides
whether required fields are complete. This prevents minor model uncertainty
from automatically becoming an unnecessary question.

### Why keep display limits outside SQL?

The database query must represent what the user asked. A browser can show the
first 20 rows for readability while still allowing the complete result to be
downloaded. Adding `LIMIT 20` to SQL would silently change the answer.

## What the project currently supports

- scalar and filtered customer counts;
- grouped counts with common grouping paraphrases;
- `SUM`, `AVG`, `MIN`, and `MAX` over named numeric metrics;
- grouped aggregations and grouped rankings;
- explicit top/bottom customer rankings;
- numeric comparison filters;
- conditional percentages;
- joins across the five telecom tables;
- contextual and multi-turn clarification;
- common telecom synonyms and informal paraphrases;
- read-only and unsupported-request rejection.

See [SUPPORTED_QUESTIONS.md](SUPPORTED_QUESTIONS.md) for the formal contract.

## Honest limitations to mention in an interview

Do not claim that this system understands every possible question. A strong
interview explanation should acknowledge that:

- support is limited to the exposed telecom schema and verified operations;
- local and hosted models can behave differently on language outside the test
  distribution;
- complex subqueries, arbitrary `OR`, window functions, `HAVING`, and
  unrestricted multi-metric reports are not yet supported;
- result rows are currently loaded into application memory;
- provider accounts, secret entry, and the final deployment clicks still have
  to be completed by the account owner;
- regex request guards help with known unsafe intent but are not a complete
  security boundary by themselves;
- database-level least privilege is still required;
- the evaluation matrix improves confidence but cannot mathematically prove
  correctness for unseen language.

Being clear about these limits demonstrates engineering judgment rather than
weakness.

## Public deployment improvement

The original application used PostgreSQL and Ollama on `localhost`. That works
for development, but a public Streamlit server cannot connect to services
running on a developer's laptop. We handled this without replacing the working
pipeline:

- added `DATABASE_URL` support for hosted PostgreSQL;
- added automatic schema and index creation for a new database;
- added a setup script for a database role with only read access;
- introduced a small model-provider boundary;
- kept Ollama as the local default;
- added Gemini chat and embeddings for the hosted environment;
- batched and cached schema embeddings to reduce cloud calls;
- added database connection and statement timeouts;
- documented Streamlit secret storage and Vercel iframe embedding.

This is an example of separating application logic from infrastructure. The
intent parser, clarification system, SQL generator, and safety validator do not
need to know where the database or AI model is hosted.

## Suggested future improvements

1. Add versioned database schema migrations for future schema changes.
2. Add cancellation, structured logs, and health checks.
3. Add authentication and centralized rate limiting.
4. Store user feedback and turn incorrect queries into regression cases.
5. Add human-readable answer summaries and appropriate charts.
6. Add server-side pagination or streaming for large results.
7. Expand the supported contract only when new cases and reference results are
   added to the evaluation matrix.

## Interview-ready explanation

### Short version

> I built a clarification-aware Text-to-SQL system for telecom analytics. I
> found that direct LLM output was unreliable for small wording changes and
> could silently change query meaning. I solved that by introducing a typed
> intent layer, deterministic normalization and SQL generation, semantic
> schema retrieval, multi-turn clarification, and defense-in-depth SQL safety.
> I evaluated it with unit tests and an 83-scenario database-backed matrix that
> compares actual results with reference SQL.

### Longer version

> The user can ask a telecom database question in normal language through a
> terminal or Streamlit chat UI. Unsafe requests are rejected first. Explicit
> supported language is parsed deterministically, while broader wording uses
> local embeddings and Llama-based schema reranking to produce structured
> intent. The intent is normalized and validated. If a required threshold or
> business definition is missing, the system asks a contextual question and
> preserves answers across turns. Once the intent is complete, deterministic
> code generates SQL, validates it as a single safe SELECT, and executes it in
> a read-only PostgreSQL transaction. The project includes regression tests for
> the semantic bugs we found and an end-to-end release gate based on database
> result equivalence.

## Common interview questions and answers

### What was the hardest problem?

The hardest problem was semantic correctness, not SQL syntax. A query can be
valid SQL but still be wrong because it adds a limit, loses a group, chooses
the wrong metric, or filters away zero-count categories. Structured intent and
result-based evaluation made those mistakes visible and fixable.

### How did you prevent overfitting to test questions?

I fixed reusable semantic concepts such as inflection, grouping quantifiers,
comparison wording, conditional aggregation, and ranking intent. I also tested
multiple paraphrases for each behavior instead of adding exact full-question
matches.

### How do you know the SQL is correct?

There are several levels of evidence: typed intent validation, deterministic
SQL-generation tests, SQL safety validation, and end-to-end comparison of
generated query results with reference SQL results. The last check is important
because correct SQL can have more than one textual form.

### How is ambiguity handled?

The parser records unresolved semantic slots. The validator checks whether the
intent is complete. The application asks a clarification only for the next
missing slot, applies the answer to the existing intent, and continues until
the query is complete or the maximum number of turns is reached.

### What makes the system safe?

Unsafe intent is rejected before parsing, generated SQL is restricted to one
read-only `SELECT`, dangerous PostgreSQL features are blocked, SQL is validated
again before execution, and the transaction is set to read-only. In production
I would also enforce a least-privilege database account and network controls.

### Why did you use local models?

Ollama keeps development self-contained and avoids sending database schema or
questions to an external model provider. The tradeoff is that cloud deployment
must host or replace those model services.

### What would you improve next?

First I would make the backend deployable with hosted PostgreSQL, managed
secrets, and a reachable model service. Then I would add authentication,
timeouts, monitoring, user feedback, answer summaries, charts, and scalable
pagination.

## Final lesson

The main lesson from this project is that a good Text-to-SQL system is not just
an LLM prompt. Reliability comes from combining language understanding with a
clear semantic contract, typed intermediate data, deterministic compilation,
clarification, layered safety, and evaluation against real database results.
