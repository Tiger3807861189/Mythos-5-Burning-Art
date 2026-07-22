from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_suite import validate_codex_marketplace


class CodexMarketplaceResolutionTests(unittest.TestCase):
    def test_declared_local_source_resolves_from_marketplace_root(self) -> None:
        catalog = ROOT / "marketplaces" / "codex" / ".agents" / "plugins" / "marketplace.json"
        payload = json.loads(catalog.read_text(encoding="utf-8"))
        declared = payload["plugins"][0]["source"]["path"]
        resolved = (ROOT / "marketplaces" / "codex" / declared).resolve()

        self.assertEqual(
            resolved,
            ROOT / "marketplaces" / "codex" / "plugins" / "mythos-5-burning-art",
        )
        self.assertTrue((resolved / ".codex-plugin" / "plugin.json").is_file())
        self.assertEqual(validate_codex_marketplace(ROOT), [])


if __name__ == "__main__":
    unittest.main()