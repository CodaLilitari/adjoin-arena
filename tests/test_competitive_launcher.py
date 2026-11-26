import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from bots import run
from bots.settings import engine_path


class CompetitiveLauncherTests(unittest.TestCase):
    def test_manual_launcher_and_manager_share_a_default_and_honor_overrides(self):
        default = engine_path({})
        self.assertEqual(default.name, "jk-bot-competitive")
        with TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "server.json"
            for config_engine, cli_engine, expected in (("", None, default), ("saved-engine", None, Path("saved-engine").resolve()),
                                                        ("saved-engine", "cli-engine", Path("cli-engine"))):
                with self.subTest(config=config_engine, cli=cli_engine):
                    cfg.write_text(json.dumps({"bots_engine": config_engine}))
                    args = ["--server-config", str(cfg), "--profiles", "jan_ors"]
                    if cli_engine:
                        args += ["--engine", cli_engine]
                    with patch.object(run, "launch", return_value=(0, Path(tmp))) as launch:
                        self.assertEqual(run.main(args), 0)
                        self.assertEqual(launch.call_args.kwargs["engine"], expected)
