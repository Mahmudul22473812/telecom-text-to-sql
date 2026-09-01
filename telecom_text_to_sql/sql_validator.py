import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SQLValidationResult:
    """Result returned by :func:`validate_sql`."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)


# Keep this ordered so validation errors are deterministic.
FORBIDDEN_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "MERGE",
    "CALL",
    "EXEC",
    "EXECUTE",
    "COPY",
    "DO",
    "LOAD",
    "VACUUM",
    "REINDEX",
    "CLUSTER",
)

UNSAFE_FUNCTIONS = (
    "PG_READ_FILE",
    "PG_READ_BINARY_FILE",
    "PG_WRITE_FILE",
    "PG_LS_DIR",
    "PG_STAT_FILE",
    "LO_IMPORT",
    "LO_EXPORT",
    "PG_ADVISORY_LOCK",
    "PG_ADVISORY_XACT_LOCK",
    "PG_TERMINATE_BACKEND",
    "PG_RELOAD_CONF",
    "SET_CONFIG",
    "NEXTVAL",
    "SETVAL",
)

_DOLLAR_QUOTE = re.compile(
    r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$"
)


def _scan_sql(sql: str, *, mask_quoted: bool) -> tuple[str, list[str]]:
    """
    Remove comments and optionally mask quoted values and identifiers.

    Masking preserves character positions and makes keyword/semicolon checks
    ignore text inside SQL literals, quoted identifiers, and dollar strings.
    PostgreSQL nested block comments are supported.
    """

    output: list[str] = []
    errors: list[str] = []
    index = 0
    length = len(sql)

    def append_character(character: str) -> None:
        output.append(" " if mask_quoted and character != "\n" else character)

    while index < length:
        if sql.startswith("--", index):
            output.extend((" ", " "))
            index += 2

            while index < length and sql[index] not in "\r\n":
                output.append(" ")
                index += 1

            continue

        if sql.startswith("/*", index):
            output.extend((" ", " "))
            index += 2
            depth = 1

            while index < length and depth:
                if sql.startswith("/*", index):
                    output.extend((" ", " "))
                    index += 2
                    depth += 1
                elif sql.startswith("*/", index):
                    output.extend((" ", " "))
                    index += 2
                    depth -= 1
                else:
                    output.append("\n" if sql[index] == "\n" else " ")
                    index += 1

            if depth:
                errors.append("Unterminated SQL block comment.")

            continue

        if sql[index] == "'":
            append_character(sql[index])
            index += 1
            terminated = False

            while index < length:
                character = sql[index]
                append_character(character)
                index += 1

                if character == "'":
                    if index < length and sql[index] == "'":
                        append_character(sql[index])
                        index += 1
                    else:
                        terminated = True
                        break
                elif character == "\\" and index < length:
                    append_character(sql[index])
                    index += 1

            if not terminated:
                errors.append("Unterminated SQL string literal.")

            continue

        if sql[index] == '"':
            append_character(sql[index])
            index += 1
            terminated = False

            while index < length:
                character = sql[index]
                append_character(character)
                index += 1

                if character == '"':
                    if index < length and sql[index] == '"':
                        append_character(sql[index])
                        index += 1
                    else:
                        terminated = True
                        break

            if not terminated:
                errors.append("Unterminated quoted SQL identifier.")

            continue

        if sql[index] == "$":
            match = _DOLLAR_QUOTE.match(sql, index)

            if match:
                tag = match.group(0)
                for character in tag:
                    append_character(character)
                index = match.end()
                closing_index = sql.find(tag, index)

                if closing_index == -1:
                    for character in sql[index:]:
                        append_character(character)
                    errors.append("Unterminated dollar-quoted SQL string.")
                    index = length
                else:
                    for character in sql[index:closing_index]:
                        append_character(character)
                    for character in tag:
                        append_character(character)
                    index = closing_index + len(tag)

                continue

        output.append(sql[index])
        index += 1

    return "".join(output), errors


def remove_sql_comments(sql: str) -> str:
    """Remove SQL comments without changing comment markers inside strings."""

    cleaned_sql, _ = _scan_sql(sql, mask_quoted=False)
    return cleaned_sql.strip()


def validate_sql(sql: str) -> SQLValidationResult:
    """Validate that *sql* is one read-only SELECT statement."""

    if not isinstance(sql, str) or not sql.strip():
        return SQLValidationResult(
            is_valid=False,
            errors=["SQL query is empty."],
        )

    if "\x00" in sql:
        return SQLValidationResult(
            is_valid=False,
            errors=["SQL query contains a null byte."],
        )

    sanitized_sql, errors = _scan_sql(sql, mask_quoted=True)
    normalized_sql = sanitized_sql.upper()

    first_keyword = re.match(
        r"\s*([A-Z_][A-Z0-9_]*)\b",
        normalized_sql,
    )

    if not first_keyword or first_keyword.group(1) != "SELECT":
        errors.append("Only SELECT queries are allowed.")

    statements = [
        statement
        for statement in sanitized_sql.split(";")
        if statement.strip()
    ]

    if len(statements) > 1:
        errors.append("Multiple SQL statements are not allowed.")

    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", normalized_sql):
            errors.append(f"Forbidden SQL keyword detected: {keyword}.")

    for function_name in UNSAFE_FUNCTIONS:
        if re.search(
            rf"\b{re.escape(function_name)}\s*\(",
            normalized_sql,
        ):
            errors.append(
                f"Unsafe PostgreSQL function detected: {function_name}."
            )

    if re.search(r"\bINTO\b", normalized_sql):
        errors.append("SELECT INTO is not allowed.")

    row_lock_pattern = (
        r"\bFOR\s+"
        r"(?:NO\s+KEY\s+UPDATE|KEY\s+SHARE|UPDATE|SHARE)\b"
    )

    if re.search(row_lock_pattern, normalized_sql):
        errors.append("Row-locking SELECT clauses are not allowed.")

    return SQLValidationResult(
        is_valid=not errors,
        errors=errors,
    )


if __name__ == "__main__":
    query = input("Enter SQL to validate: ")
    result = validate_sql(query)

    print("\nSQL Validation Result:\n")
    print(f"Valid: {result.is_valid}")
    print(f"Errors: {result.errors}")
