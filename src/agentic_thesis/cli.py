import argparse
import os
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv


REQUIRED_CREDENTIALS = (
    "OPENAI_API_KEY",
    "EMBEDDING_API_KEY",
    "EMBEDDING_BASE_URL",
    "AGENTIC_THESIS_EMBEDDING_MODEL",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentic-thesis")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the AgenticThesis web application")
    serve.add_argument(
        "--data-dir",
        type=Path,
        default=Path.home() / ".agentic-thesis",
        help="Persistent data directory (default: ~/.agentic-thesis)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    data_dir = args.data_dir.expanduser().resolve()
    load_dotenv(Path.cwd() / ".env")
    load_dotenv(data_dir / ".env")
    missing = [name for name in REQUIRED_CREDENTIALS if not os.getenv(name)]
    if missing:
        print("Missing required environment variables:", file=sys.stderr)
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
        print(
            f"Set them in the environment, ./.env, or {data_dir / '.env'}.",
            file=sys.stderr,
        )
        return 2

    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["AGENTIC_THESIS_DATA_DIR"] = str(data_dir)
    uvicorn.run("agentic_thesis.api:app", host="127.0.0.1", port=8000)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
