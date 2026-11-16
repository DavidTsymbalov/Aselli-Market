import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import launcher


class LauncherTests(unittest.TestCase):
    def test_first_launch_configures_token_and_hosted_app(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {}, clear=True):
            launcher.prepare_config(root, prompt=lambda _: "123456:TEST_TOKEN")
            path = Path(root) / ".env"
            self.assertIn("BOT_TOKEN=123456:TEST_TOKEN", path.read_text())
            self.assertIn("WEBAPP_URL=" + launcher.WEBAPP_URL, path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_existing_config_is_preserved_without_prompt(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {}, clear=True):
            path = Path(root) / ".env"
            original = "BOT_TOKEN=123456:EXISTING\nWEBAPP_URL=https://example.com/\nDATABASE_PATH=data/shop.sqlite3\n"
            path.write_text(original)
            prompt = Mock(side_effect=AssertionError("Unexpected prompt"))
            launcher.prepare_config(root, prompt=prompt)
            self.assertEqual(path.read_text(), original)

    def test_invalid_token_is_not_saved_or_printed_in_error(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as caught:
                launcher.prepare_config(root, prompt=lambda _: "PRIVATE_INVALID_TOKEN")
            self.assertNotIn("PRIVATE_INVALID_TOKEN", str(caught.exception))
            self.assertFalse((Path(root) / ".env").exists())


if __name__ == "__main__":
    unittest.main()
