import argparse
import json

from ai_sidecar import _run_once


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one local AI review against the current tradebot runtime snapshot.")
    parser.add_argument("--persist", action="store_true", help="Append this review to ai_decisions.jsonl.")
    parser.add_argument("--write-signal", action="store_true", help="Write this review to ai_signal.json.")
    args = parser.parse_args()

    decision = _run_once(persist=args.persist, write_signal=args.write_signal)
    print(json.dumps(decision, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
