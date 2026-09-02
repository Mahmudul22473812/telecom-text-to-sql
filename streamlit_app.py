"""Browser interface for the telecom Text-to-SQL pipeline."""

from io import StringIO

import pandas as pd
import streamlit as st

from telecom_text_to_sql.pipeline import PipelineResult
from telecom_text_to_sql.ui_controller import (
    ConversationState,
    process_message,
)


DEFAULT_DISPLAY_ROWS = 20
DISPLAY_OPTIONS = (20, 50, 100)


def initialize_page() -> None:
    st.set_page_config(
        page_title="Telecom Data Assistant",
        page_icon="📡",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        .block-container {max-width: 1180px; padding-top: 2rem;}
        [data-testid="stChatMessage"] {
            border: 1px solid rgba(128, 128, 128, 0.18);
            border-radius: 14px;
            padding: 0.4rem 0.7rem;
        }
        [data-testid="stMetric"] {
            border: 1px solid rgba(128, 128, 128, 0.18);
            border-radius: 12px;
            padding: 0.7rem 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def get_conversation() -> ConversationState:
    if "conversation" not in st.session_state:
        st.session_state.conversation = ConversationState()
    return st.session_state.conversation


def result_dataframe(result: PipelineResult) -> pd.DataFrame:
    return pd.DataFrame(result.rows, columns=result.columns)


def csv_bytes(frame: pd.DataFrame) -> bytes:
    buffer = StringIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")


def render_success(result: PipelineResult, display_rows: int, key: str) -> None:
    st.success("Query completed successfully.")

    metric_columns = st.columns(3)
    metric_columns[0].metric("Rows returned", len(result.rows))
    metric_columns[1].metric(
        "Columns",
        len(result.columns),
    )
    metric_columns[2].metric(
        "Completed in",
        f"{result.total_latency_ms:.1f} ms",
    )

    if result.rows:
        frame = result_dataframe(result)
        visible_frame = frame.head(display_rows)
        st.dataframe(
            visible_frame,
            use_container_width=True,
            hide_index=True,
        )

        if len(frame) > display_rows:
            st.caption(
                f"Showing the first {display_rows:,} rows out of "
                f"{len(frame):,}. The SQL query returned the complete result."
            )

        st.download_button(
            "Download complete result as CSV",
            data=csv_bytes(frame),
            file_name="telecom_query_result.csv",
            mime="text/csv",
            key=f"download-{key}",
        )
    else:
        st.info("The query completed, but no matching rows were found.")

    if result.sql:
        with st.expander("Generated SQL"):
            st.code(result.sql, language="sql")

    with st.expander("Query details"):
        st.json(
            {
                "status": result.status,
                "initially_ambiguous": result.initially_ambiguous,
                "clarification_questions": result.clarification_questions,
                "clarification_answers": result.clarification_answers,
                "timings_ms": result.timings_ms,
            }
        )


def render_result(result: PipelineResult, display_rows: int, key: str) -> None:
    if result.status == "success":
        render_success(result, display_rows, key)
        return

    if result.status == "unsupported":
        st.warning(result.error or "This request is not supported.")
        return

    if result.status == "sql_rejected":
        st.error("The generated SQL did not pass the safety validator.")
        for error in result.sql_validation_errors:
            st.write(f"- {error}")
        return

    st.error(
        "The query could not be completed. Check the database and AI "
        "service configuration, then try again."
    )
    if result.error:
        with st.expander("Technical details"):
            st.code(result.error)


def render_message(message: dict, display_rows: int, index: int) -> None:
    with st.chat_message(message["role"]):
        if message["kind"] in {
            "question",
            "clarification_answer",
            "clarification",
        }:
            st.write(message["content"])
            return

        render_result(
            message["result"],
            display_rows,
            key=str(index),
        )


def render_sidebar(
    conversation: ConversationState,
) -> int:
    with st.sidebar:
        st.header("Query settings")
        display_rows = st.selectbox(
            "Rows to display",
            options=DISPLAY_OPTIONS,
            index=DISPLAY_OPTIONS.index(DEFAULT_DISPLAY_ROWS),
            help=(
                "This changes only the number of rows shown in the browser. "
                "It does not add a SQL LIMIT."
            ),
        )

        if conversation.awaiting_clarification:
            st.info("Waiting for your clarification answer.")
            if st.button("Cancel clarification", use_container_width=True):
                conversation.cancel_clarification()
                st.rerun()

        if st.button("Clear conversation", use_container_width=True):
            conversation.clear()
            st.rerun()

        st.divider()
        st.subheader("Example questions")
        st.caption("• How many customers are on each contract type?")
        st.caption("• Show customers with monthly charges above 100.")
        st.caption("• Give me the top 3 clients by total revenue.")
        st.caption("• Which city has healthy customer retention?")

        st.divider()
        st.caption(
            "Read-only telecom analytics. Unsafe or unsupported requests "
            "are rejected before SQL execution."
        )

    return display_rows


def main() -> None:
    initialize_page()
    conversation = get_conversation()
    display_rows = render_sidebar(conversation)

    st.title("📡 Telecom Data Assistant")
    st.write(
        "Ask a question about customers, services, churn, contracts, "
        "charges, locations, or population."
    )

    if not conversation.messages:
        st.info(
            "Try: “How many customers are on each type of contract?”"
        )

    for index, message in enumerate(conversation.messages):
        render_message(message, display_rows, index)

    placeholder = (
        "Enter your clarification answer..."
        if conversation.awaiting_clarification
        else "Ask a telecom database question..."
    )
    user_message = st.chat_input(placeholder, max_chars=1000)

    if user_message:
        with st.spinner("Analyzing your request..."):
            process_message(conversation, user_message)
        st.rerun()


if __name__ == "__main__":
    main()
