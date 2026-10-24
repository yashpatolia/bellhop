"""The frontend contract (contracts/openapi.json) must match the live API exactly."""

import json
from pathlib import Path

from bellhop.api.main import app

CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "openapi.json"


def test_contract_file_matches_live_api_schema():
    assert CONTRACT.exists(), "run: uv run python scripts/export_contract.py"
    on_disk = json.loads(CONTRACT.read_text())
    assert on_disk == json.loads(json.dumps(app.openapi())), (
        "API changed: run `uv run python scripts/export_contract.py` and commit contracts/"
    )
