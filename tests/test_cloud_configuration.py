import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from telecom_text_to_sql import database, model_provider


class DatabaseConfigurationTests(unittest.TestCase):
    @patch("telecom_text_to_sql.database.psycopg.connect")
    def test_database_url_is_preferred_for_hosted_connections(self, connect):
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://reader:secret@cloud/db",
                "DB_CONNECT_TIMEOUT": "7",
            },
            clear=False,
        ):
            database.connect_database()

        connect.assert_called_once_with(
            "postgresql://reader:secret@cloud/db",
            connect_timeout=7,
            application_name="telecom_text_to_sql",
        )

    @patch("telecom_text_to_sql.database.psycopg.connect")
    def test_explicit_admin_url_overrides_application_url(self, connect):
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql://reader@cloud/app"},
            clear=False,
        ):
            database.connect_database("postgresql://owner@cloud/admin")

        self.assertEqual(
            connect.call_args.args[0],
            "postgresql://owner@cloud/admin",
        )


class ModelProviderTests(unittest.TestCase):
    def tearDown(self):
        model_provider.embed_texts.cache_clear()
        model_provider._gemini_client.cache_clear()

    @patch("telecom_text_to_sql.model_provider.ollama.chat")
    def test_local_ollama_remains_the_default(self, chat):
        chat.return_value = {"message": {"content": '{"ok": true}'}}

        with patch.dict(os.environ, {}, clear=True):
            result = model_provider.chat_json(
                [{"role": "user", "content": "hello"}]
            )

        self.assertEqual(result, '{"ok": true}')
        self.assertEqual(chat.call_args.kwargs["model"], "llama3.2")

    @patch("telecom_text_to_sql.model_provider.ollama.embed")
    def test_ollama_embeddings_are_batched(self, embed):
        embed.return_value = {"embeddings": [[1, 0], [0, 1]]}

        with patch.dict(os.environ, {"AI_PROVIDER": "ollama"}, clear=True):
            result = model_provider.embed_texts(("first", "second"))

        self.assertEqual(result, ((1.0, 0.0), (0.0, 1.0)))
        self.assertEqual(embed.call_args.kwargs["input"], ["first", "second"])

    def test_gemini_requires_a_server_side_api_key(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "gemini"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                model_provider.chat_json(
                    [{"role": "user", "content": "hello"}]
                )

    @patch("telecom_text_to_sql.model_provider._gemini_types")
    @patch("telecom_text_to_sql.model_provider._gemini_client")
    def test_gemini_chat_returns_json_text(self, get_client, get_types):
        generate_content = Mock(
            return_value=SimpleNamespace(text='{"status": "ok"}')
        )
        get_client.return_value.models.generate_content = generate_content

        class GenerateContentConfig:
            def __init__(self, **values):
                self.values = values

        get_types.return_value.GenerateContentConfig = GenerateContentConfig

        with patch.dict(
            os.environ,
            {
                "AI_PROVIDER": "gemini",
                "GEMINI_API_KEY": "test-key",
                "GEMINI_CHAT_MODEL": "test-model",
            },
            clear=True,
        ):
            result = model_provider.chat_json(
                [
                    {"role": "system", "content": "Return JSON."},
                    {"role": "user", "content": "hello"},
                ]
            )

        self.assertEqual(result, '{"status": "ok"}')
        self.assertEqual(generate_content.call_args.kwargs["model"], "test-model")


if __name__ == "__main__":
    unittest.main()
