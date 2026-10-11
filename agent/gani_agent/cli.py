"""Offline CLI: index a corpus, check round-trips, measure a file. No editor or API key needed."""
import argparse
import json
import sys
from pathlib import Path

from . import gani as G
from . import metrics as M
from .corpus import Corpus


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gani-cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index"); p.add_argument("root"); p.add_argument("--db", default="corpus.sqlite")
    p = sub.add_parser("check"); p.add_argument("file")
    p = sub.add_parser("stats"); p.add_argument("category"); p.add_argument("--db", default="corpus.sqlite")
    a = ap.parse_args(argv)
    if a.cmd == "index":
        print(json.dumps(Corpus(a.db).index_dir(a.root), indent=2, default=str))
    elif a.cmd == "check":
        doc = G.parse(Path(a.file).read_text(errors="replace"))
        rep = M.compute(doc, static_ids=M.static_ids_from_refs([doc]))
        print(json.dumps({"frames": len(doc.frames), "total_ms": doc.total_ms(),
                          "unknown": doc.unknown_directives, "summary": rep["summary"]}, indent=2))
    elif a.cmd == "stats":
        print(json.dumps(Corpus(a.db).category_stats(a.category), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
