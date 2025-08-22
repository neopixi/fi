from pathlib import Path
from typing import Iterable, List, Tuple, Dict, Optional

BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".pdf", ".zip", ".rar", ".7z", ".gz", ".tar", ".xz",
    ".mp3", ".wav", ".ogg", ".flac",
    ".mp4", ".mkv", ".mov", ".avi",
    ".woff", ".woff2", ".ttf", ".otf",
    ".dll", ".so", ".dylib", ".exe", ".bin", ".class", ".o",
}

LANG_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".m": "objectivec",
    ".mm": "objectivec",
    ".sh": "bash",
    ".zsh": "bash",
    ".ps1": "powershell",
    ".sql": "sql",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".xml": "xml",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".md": "markdown",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".txt": "",
}

def is_binary_path(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTS:
        return True
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
            if b"\x00" in chunk:
                return True
    except Exception:
        return True
    return False

def read_text_file(path: Path, limit_bytes: Optional[int] = None) -> Tuple[str, bool]:
    """
    Read text as UTF-8 (fallback latin-1). If limit_bytes is set, stop after that many bytes.
    Returns (text, truncated_flag).
    """
    data: bytes = b""
    truncated = False
    try:
        if limit_bytes is not None:
            with path.open("rb") as f:
                remaining = limit_bytes
                chunks = []
                while remaining > 0:
                    chunk = f.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                data = b"".join(chunks)
                if f.read(1):
                    truncated = True
        else:
            data = path.read_bytes()
    except Exception:
        return "", False

    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        try:
            text = data.decode("latin-1", errors="replace")
        except Exception:
            text = ""
    return text, truncated

def guess_fence_lang(path: Path) -> str:
    return LANG_BY_EXT.get(path.suffix.lower(), "")

def rel_to(base: Path, target: Path) -> str:
    try:
        return str(target.relative_to(base).as_posix())
    except Exception:
        return str(target.as_posix())

def _connectors(charset: str):
    if charset == "unicode":
        mid = "\u251c\u2500\u2500 "
        last = "\u2514\u2500\u2500 "
        bar = "\u2502   "
    else:
        mid = "|-- "
        last = "`-- "
        bar = "|   "
    return mid, last, bar

def build_tree(
    paths: Iterable[Path],
    root: Path,
    charset: str = "unicode",
    annotations: Optional[Dict[str, str]] = None,
) -> str:
    """
    Render a directory tree for the given included files.
    charset: "unicode" or "ascii".
    annotations: optional map {relative_posix_path: " suffix"} to append to file leaves.
    Only directories that contain included files are printed.
    """
    root = root.resolve()
    parts_map: Dict[Tuple[str, ...], List[str]] = {}
    for p in paths:
        rel = Path(rel_to(root, p))
        if not rel.parts:
            continue
        tup = tuple(rel.parts[:-1])
        leaf = rel.parts[-1]
        parts_map.setdefault(tup, []).append(leaf)

    from collections import defaultdict
    children = defaultdict(set)
    for tup, leaves in parts_map.items():
        for i in range(len(tup)):
            parent = tup[:i]
            child = tup[:i + 1]
            children[parent].add(child)
        children[tup].update({(*tup, leaf) for leaf in sorted(leaves)})

    mid, last, bar = _connectors(charset)
    lines: List[str] = []

    def is_dir_node(node: Tuple[str, ...]) -> bool:
        return node in children and any(len(g) > len(node) for g in children.get(node, []))

    def render(node: Tuple[str, ...], prefix: str = ""):
        kids = sorted(children.get(node, []), key=lambda t: (t == node or len(t) == len(node), t))
        for idx, child in enumerate(kids):
            is_last = idx == len(kids) - 1
            connector = last if is_last else mid
            next_prefix = prefix + ("    " if is_last else bar)
            name = child[-1] if child else root.name
            is_dir = is_dir_node(child)
            display = name + ("/" if is_dir else "")

            # Append annotation only for file leaves
            if not is_dir and annotations:
                rel_key = "/".join(child)
                suffix = annotations.get(rel_key, "")
                if suffix:
                    display += suffix

            lines.append(prefix + connector + display)
            if is_dir:
                render(child, next_prefix)

    lines.append(root.name + "/")
    render((), "")
    return "\n".join(lines)

def top_extensions(files: Iterable[Path], k: int = 5) -> List[Tuple[str, int]]:
    from collections import Counter
    exts = [p.suffix.lower() or "<none>" for p in files]
    cnt = Counter(exts)
    return cnt.most_common(k)
