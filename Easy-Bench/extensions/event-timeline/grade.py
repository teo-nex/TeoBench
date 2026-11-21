"""Grade one event-timeline submission against the frozen answer."""

import argparse
import json
from pathlib import Path


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"invalid JSON constant: {value}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("submission", type=Path)
    args = parser.parse_args()
    expected = json.loads(Path(__file__).with_name("expected.json").read_text(encoding="utf-8"))
    try:
        actual = json.loads(
            args.submission.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
        passed = json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)
    except (OSError, ValueError, RecursionError):
        passed = False
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
