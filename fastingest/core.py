from __future__ import annotations
import os
import time
import os as _os
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import fnmatch
from .ignore import build_composite_ignore, CompositeIgnore
from .utils import (
    is_binary_path,
    read_text_file,
    guess_fence_lang,
    rel_to,
    build_tree,
    top_extensions,
)
from .tokenizer import count_tokens

# Default heavy dirs to prune early for speed.
DEFAULT_PRUNE_DIRS = {
    ".git", "node_modules", ".pnpm-store", ".yarn", ".npm",
    "venv", ".venv", ".tox",
    "dist", "build", "out", "target",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".cache",
    ".idea", ".vscode",
}

def _extract_dir_hints(patterns: List[str]) -> set:
    """
    Pull literal path segments from include patterns to avoid pruning
    those directories if the user explicitly targets them.
    """
    hints = set()
    for pat in patterns or []:
        parts = pat.replace("\\", "/").split("/")
        for seg in parts:
            if not seg or seg == ".":
                continue
            if any(ch in seg for ch in ("*", "?", "[", "]")):
                continue
            hints.add(seg)
    return hints

class Timer:
    def __init__(self):
        self.marks: Dict[str, float] = {}
        self.start("total")

    def start(self, name: str):
        self.marks[name] = time.perf_counter()

    def stop(self, name: str) -> float:
        return time.perf_counter() - self.marks.get(name, time.perf_counter())

def matches_any(path_posix: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatch(path_posix, pat) for pat in patterns)

def list_included_files(
    root: Path,
    include_globs: List[str],
    exclude_globs: List[str],
    ignore: Optional[CompositeIgnore],
) -> Tuple[List[Path], List[Path]]:
    """
    Walk the tree with aggressive pruning:
    - prune directories ignored by .gitignore/.fiignore
    - prune default heavy directories unless explicitly hinted in includes
    - do not follow symlinked directories
    - apply include/exclude globs on files
    - skip binaries
    """
    included: List[Path] = []
    excluded: List[Path] = []
    root = root.resolve()

    include_hints = _extract_dir_hints(include_globs)

    for cur_dir, dirs, files in os.walk(root, topdown=True, followlinks=False):
        cur_p = Path(cur_dir)

        # Prune dirs in-place
        kept: List[str] = []
        for d in dirs:
            dp = cur_p / d
            if d in DEFAULT_PRUNE_DIRS and d not in include_hints:
                continue
            if ignore and ignore.matches(dp):
                continue
            kept.append(d)
        dirs[:] = kept

        # Files
        for name in files:
            p = cur_p / name
            if ignore and ignore.matches(p):
                excluded.append(p)
                continue

            rel = rel_to(root, p)
            if include_globs and not matches_any(rel, include_globs):
                excluded.append(p)
                continue
            if exclude_globs and matches_any(rel, exclude_globs):
                excluded.append(p)
                continue
            if is_binary_path(p):
                excluded.append(p)
                continue
            included.append(p)

    return included, excluded

def build_markdown(
    root: Path,
    included: List[Path],
    excluded: List[Path],
    tree_text: str,
    max_file_bytes: int,
    max_total_bytes: int,
) -> Tuple[str, bool]:
    """
    Build Markdown; truncate overly large files and stop when total limit reached.
    Returns (markdown, truncated_flag).

    No header section at the top.
    Appends a multi-line footer from FASTINGEST_FOOTER; if not set or empty,
    uses the built-in default footer.
    """
    lines: List[str] = []

    # Directory tree (pretty)
    lines.append("## Directory Tree")
    lines.append("")
    lines.append("```text")
    lines.append(tree_text)
    lines.append("```")
    lines.append("")

    # Files
    lines.append("## Files")
    lines.append("")

    total_bytes = 0
    truncated = False

    for p in included:
        rel = rel_to(root, p)
        lang = guess_fence_lang(p)

        header = f"### `{rel}`"
        block_start = f"```{lang}".rstrip()

        chunk_lines = [header, "", block_start]

        content, was_truncated = read_text_file(p, limit_bytes=max_file_bytes)

        if was_truncated:
            content += "\n\n[... truncated due to FASTINGEST_MAX_FILE_BYTES ...]\n"

        chunk_lines.append(content)
        chunk_lines.append("```")
        chunk_lines.append("")

        chunk_text = "\n".join(chunk_lines)
        add_len = len(chunk_text.encode("utf-8", errors="replace"))

        if total_bytes + add_len > max_total_bytes:
            note = "\n[... truncated due to FASTINGEST_MAX_TOTAL_BYTES ...]\n"
            lines.append(header)
            lines.append("")
            lines.append(note.strip())
            lines.append("")
            truncated = True
            break

        lines.append(chunk_text)
        total_bytes += add_len

    # Footer logic: env or default
    env_footer = _os.environ.get("FASTINGEST_FOOTER", None)
    if env_footer is None or env_footer.strip() == "":
        footer = (
            "Do not use canvas.\n"
            "Always provide the full content of all files that need to be changed in the chat.\n"
            "Use only English characters in code.\n"
        )
    else:
        footer = env_footer.replace("\\r", "\r").replace("\\n", "\n").replace("\\t", "\t")
        if not footer.endswith("\n"):
            footer += "\n"

    lines.append(footer)

    return "\n".join(lines), truncated

def copy_to_clipboard(text: str) -> str:
    """
    Copy text to clipboard. Try pyperclip; fallback to platform tools.
    Returns backend name used.
    """
    try:
        import pyperclip  # optional
        pyperclip.copy(text)
        return "pyperclip"
    except Exception:
        pass

    import subprocess
    import sys
    try:
        if sys.platform == "darwin":
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"))
            return "pbcopy(utf-8)"
        elif sys.platform.startswith("win"):
            try:
                p = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
                p.communicate(input=text.encode("utf-16le"))
                return "clip(utf-16le)"
            except Exception:
                cmd = ["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value -"]
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE, shell=True)
                p.communicate(input=text.encode("utf-8"))
                return "powershell Set-Clipboard"
        else:
            for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
                try:
                    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                    p.communicate(input=text.encode("utf-8"))
                    return " ".join(cmd) + "(utf-8)"
                except Exception:
                    continue
    except Exception:
        pass
    return "unavailable"

def run_ingest(
    directory: Path,
    include_globs: List[str],
    exclude_globs: List[str],
    g_param: Optional[str],
    output_file: Optional[Path],
    cwd: Optional[Path] = None,
) -> Dict[str, object]:
    # Limits (env-tunable)
    max_file_bytes = int(_os.environ.get("FASTINGEST_MAX_FILE_BYTES", str(512 * 1024)))         # 512 KiB
    max_total_bytes = int(_os.environ.get("FASTINGEST_MAX_TOTAL_BYTES", str(10 * 1024 * 1024))) # 10 MiB

    t = Timer()
    if cwd is None:
        cwd = Path.cwd()

    t.start("ignore")
    ignore = build_composite_ignore(directory, cwd, g_param)
    ignore_time = t.stop("ignore")

    # Expose discovered ignore files
    ignore_files = []
    if ignore is not None:
        try:
            ignore_files = [str(p.resolve()) for p in ignore.all_files]
        except Exception:
            ignore_files = [str(p) for p in ignore.all_files]

    t.start("scan")
    included, excluded = list_included_files(directory, include_globs, exclude_globs, ignore)
    scan_time = t.stop("scan")

    # Prepare per-file token annotations for console tree (respecting file-size limit)
    t.start("per_file_tokens")
    annotations_rel: Dict[str, str] = {}
    for p in included:
        content, was_truncated = read_text_file(p, limit_bytes=max_file_bytes)
        tok, _method = count_tokens(content)
        rel = rel_to(directory, p)
        suffix = f" (t={tok}{'*' if was_truncated else ''})"
        annotations_rel[rel] = suffix
    per_file_tokens_time = t.stop("per_file_tokens")

    t.start("tree")
    # For Markdown: pretty unicode, without per-file tokens
    tree_markdown = build_tree(included, directory, charset="unicode")
    # For console: annotated trees (unicode/ascii)
    tree_console_unicode = build_tree(included, directory, charset="unicode", annotations=annotations_rel)
    tree_console_ascii = build_tree(included, directory, charset="ascii", annotations=annotations_rel)
    tree_time = t.stop("tree")

    t.start("markdown")
    markdown, was_truncated = build_markdown(
        directory, included, excluded, tree_markdown, max_file_bytes, max_total_bytes
    )
    markdown_time = t.stop("markdown")

    t.start("tokens")
    if was_truncated or len(markdown) > 2_000_000:
        token_count, token_method = max(1, int(len(markdown) / 4)), "estimate(~4 chars/token)"
    else:
        token_count, token_method = count_tokens(markdown)
    tokens_time = t.stop("tokens")

    t.start("output")
    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(markdown, encoding="utf-8")
    cb_backend = copy_to_clipboard(markdown)
    output_time = t.stop("output")

    total_time = t.stop("total")

    return {
        "included": included,
        "excluded": excluded,
        "tree_console_unicode": tree_console_unicode,
        "tree_console_ascii": tree_console_ascii,
        "tree_markdown": tree_markdown,
        "markdown": markdown,
        "token_count": token_count,
        "token_method": token_method,
        "times": {
            "ignore": round(ignore_time, 4),
            "scan": round(scan_time, 4),
            "per_file_tokens": round(per_file_tokens_time, 4),
            "tree": round(tree_time, 4),
            "markdown": round(markdown_time, 4),
            "tokens": round(tokens_time, 4),
            "output": round(output_time, 4),
            "total": round(total_time, 4),
        },
        "truncated": was_truncated,
        "max_file_bytes": max_file_bytes,
        "max_total_bytes": max_total_bytes,
        "clipboard_backend": cb_backend,
        "output_file": str(output_file) if output_file else None,
        "root": str(directory),
        "ignore_files": ignore_files,
    }
