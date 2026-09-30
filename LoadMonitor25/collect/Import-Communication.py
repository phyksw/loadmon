"""Import user-selected EML/MBOX exports without connecting to an account."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from communication_import import import_paths  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Explicit EML/MBOX files or directories")
    parser.add_argument("--from", dest="d0", required=True)
    parser.add_argument("--to", dest="d1", required=True)
    parser.add_argument("--recursive", action="store_true", help="Include subdirectories of selected directories")
    parser.add_argument("--own-address", action="append", default=[])
    args = parser.parse_args(argv)
    config = {"collection": {"communicationImportRecursive": args.recursive,
                              "communicationImportOwnAddresses": args.own_address}}
    result = import_paths(ROOT, args.paths, args.d0, args.d1, config)
    print(json.dumps(result, ensure_ascii=True))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
