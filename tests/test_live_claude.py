"""Live Claude Code check of `bin/tareq sync` output (opt-in: TAREQ_LIVE_CLAUDE=1).

Runs a real `claude -p` session in an isolated temp project produced by the manager and asks
the model which skills and rules it sees. Calls the model, so it is skipped by default.
OpenCode is never run here (not installed; documented-only, R-17).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import unittest

from test_manager import Env

LIVE = os.environ.get("TAREQ_LIVE_CLAUDE") == "1" and shutil.which("claude")


def ask(project, prompt: str) -> str:
    proc = subprocess.run(["claude", "-p", "--model", "haiku", "--max-turns", "1", prompt],
                          cwd=project, capture_output=True, text=True, timeout=180)
    return proc.stdout


@unittest.skipUnless(LIVE, "set TAREQ_LIVE_CLAUDE=1 to run against a real Claude Code CLI")
class TestLiveClaudeCode(Env):
    def test_generated_project_loads_in_claude_code(self):
        self.edit_config(lambda d: d["include"].append("demo-pentest"))  # manual skill
        self.sync()
        listed = ask(self.proj, "Without using tools, list every skill name in your available skills "
                     "listing that starts with 'demo-'. Output only the names, one per line.")
        names = {line.strip() for line in listed.splitlines() if line.strip().startswith("demo-")}
        self.assertEqual(names, {"demo-project-review", "demo-spring-guide", "demo-testing-base"}, listed)
        rules = ask(self.proj, "Without using tools: quote the first Markdown heading of every project "
                    "rules or instructions file loaded in your context. Output only the headings.")
        self.assertIn("Skills managed by tareq-skills", rules)


if __name__ == "__main__":
    unittest.main()
