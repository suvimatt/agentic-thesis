import json
from pathlib import Path

from agentic_thesis.api import create_app


output = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
output.write_text(
    json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
