import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class StreamlitAppTests(unittest.TestCase):
    def test_initial_page_renders_without_errors(self):
        app = AppTest.from_file(
            str(PROJECT_ROOT / "streamlit_app.py"),
            default_timeout=10,
        ).run()

        self.assertEqual(app.exception, [])
        self.assertEqual(app.title[0].value, "📡 Telecom Data Assistant")
        self.assertEqual(len(app.chat_input), 1)
        self.assertEqual(app.selectbox[0].value, 20)
        self.assertGreaterEqual(len(app.button), 1)


if __name__ == "__main__":
    unittest.main()
