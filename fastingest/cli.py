from __future__ import annotations
import argparse
from pathlib import Path
import sys
from .core import run_ingest

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="fi",
        description="FastIngest: convert a folder into one LLM-friendly Markdown (summary + tree + file contents).",
    )
    p.add_argument("-d", "--dir", default=".", help="Target directory (default: current directory).")
    p.add_argument("-i", "--include", action="append", default=[], help="Include glob (can be used multiple times).")
    p.add_argument("-e", "--exclude", action="append", default=[], help="Exclude glob (can be used multiple times).")
    p.add_argument("-g", "--gitignore", default=None,
                   help='Path to folder with ignore files, or "false" to disable.')
    p.add_argument("-o", "--output", default=None, help="Write Markdown to this file (also copies to clipboard).")
    return p.parse_args(argv)

def _stdout_supports_unicode() -> bool:
    enc = getattr(sys.stdout, "encoding", None)
    return bool(enc and "utf" in enc.lower())

def _try_enable_utf8_stdout():
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def _normalize_globs(patterns: list[str]) -> list[str]:
    """
    Make short masks like *.py match in subdirectories too by expanding to **/*.py.
    Only when the mask has wildcards and no path separators.
    """
    out = []
    for pat in patterns:
        if (("*" in pat) or ("?" in pat)) and ("/" not in pat) and ("\\" not in pat):
            out.append(f"**/{pat}")
        else:
            out.append(pat)
    return out

def main(argv=None):
    args = parse_args(argv)

    _try_enable_utf8_stdout()

    target = Path(args.dir).resolve()
    if not target.exists() or not target.is_dir():
        print(f"[fi] Error: directory not found: {target}", file=sys.stderr)
        return 2

    includes = _normalize_globs(args.include or [])
    excludes = _normalize_globs(args.exclude or [])

    output_file = Path(args.output).resolve() if args.output else None

    res = run_ingest(
        directory=target,
        include_globs=includes,
        exclude_globs=excludes,
        g_param=args.gitignore,
        output_file=output_file,
        cwd=Path.cwd(),
    )

    # Print discovered ignore files (absolute paths)
    print("=== Ignore files ===")
    if res.get("ignore_files"):
        for p in res["ignore_files"]:
            print(p)
    else:
        print("(none)")
    print("")

    # Console tree with per-file token annotations
    tree_to_print = res["tree_console_unicode"] if _stdout_supports_unicode() else res["tree_console_ascii"]

    print("=== Directory tree (included) ===")
    print(tree_to_print)
    print("")
    print("=== Token count ===")
    print(f"{res['token_count']} ({res['token_method']})")
    print("")
    print("=== Timings (seconds) ===")
    for k, v in res["times"].items():
        print(f"{k}: {v}")
    print("")
    if res["output_file"]:
        print(f"Output file: {res['output_file']}")
    print(f"Clipboard: {res['clipboard_backend']}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
