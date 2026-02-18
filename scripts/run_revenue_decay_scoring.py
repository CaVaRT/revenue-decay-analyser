from pathlib import Path
import sys

# Allow direct script execution: `python scripts/run_revenue_decay_scoring.py ...`
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipelines.revenue_decay_scoring import build_parser, run


if __name__ == "__main__":
    parser = build_parser()
    try:
        run(parser.parse_args())
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
