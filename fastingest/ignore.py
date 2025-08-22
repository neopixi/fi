from __future__ import annotations
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import os
from pathspec import PathSpec

IGNORE_FILE_NAMES = [".gitignore", ".fiignore"]

def _read_lines(file_path: Path) -> List[str]:
    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as f:
            raw = f.read().splitlines()
    except Exception:
        return []
    out: List[str] = []
    for line in raw:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out

def _normalize_git_line(line: str) -> str:
    """
    Apply git-like conveniences:
    - If pattern ends with '/', treat it as a directory: append '**'
    - If pattern has no '/', make it recursive by prefixing '**/'
    (Negation '!' is preserved.)
    """
    neg = False
    body = line
    if body.startswith("!"):
        neg = True
        body = body[1:]

    # strip leading './'
    if body.startswith("./"):
        body = body[2:]

    # Leading '/' anchors to the ignore file's base; we'll rebase later anyway.
    body = body.lstrip("/")

    if body.endswith("/"):
        body = body + "**"

    if "/" not in body:
        body = "**/" + body

    return ("!" + body) if neg else body

def _common_anchor(dirs: List[Path]) -> Path:
    """
    Smallest common directory that contains all the ignore files' parent dirs.
    """
    if not dirs:
        return Path.cwd().resolve()
    parts = [str(d.resolve()) for d in dirs]
    anc = Path(os.path.commonpath(parts))
    return anc

def _rebase_pattern_to_anchor(pattern: str, base: Path, anchor: Path) -> str:
    """
    Convert a pattern relative to 'base' into an anchor-relative one by
    prefixing the anchor->base relative path.
    Keep negation '!' as-is.
    """
    neg = pattern.startswith("!")
    body = pattern[1:] if neg else pattern

    prefix = ""
    try:
        rel = base.resolve().relative_to(anchor.resolve()).as_posix()
        if rel and rel != ".":
            prefix = rel + "/"
    except Exception:
        # If base is not under anchor (should not happen), leave prefix empty.
        prefix = ""

    rebased = prefix + body
    return ("!" + rebased) if neg else rebased

class CompositeIgnore:
    """
    A single combined PathSpec rebased to a common anchor.
    'all_files' keeps the discovered ignore files for diagnostics.
    """
    def __init__(self, spec: PathSpec, all_files: List[Path], anchor: Path):
        self.spec = spec
        self.all_files = all_files
        self.anchor = anchor.resolve()
        self._cache: Dict[str, bool] = {}

    def matches(self, path: Path) -> bool:
        """
        Return True if path should be ignored according to the combined spec.
        """
        try:
            rel = path.resolve().relative_to(self.anchor).as_posix()
        except Exception:
            # Outside of anchor -> cannot be ignored by these specs
            return False

        key = rel
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        val = bool(self.spec.match_file(rel))
        self._cache[key] = val
        return val

def collect_ignore_files_along_path(start: Path, end: Path) -> List[Path]:
    """
    Collect ignore files on the path from 'start' down to 'end' (inclusive),
    if 'end' is a subdirectory of 'start'.
    Order: start -> ... -> end (top to bottom).
    """
    try:
        rel = end.resolve().relative_to(start.resolve())
    except Exception:
        return []
    dirs = [start.resolve()]
    for part in rel.parts:
        dirs.append(dirs[-1] / part)
    files: List[Path] = []
    for d in dirs:
        for name in IGNORE_FILE_NAMES:
            p = d / name
            if p.is_file():
                files.append(p)
    return files

def collect_ignore_files_from_ancestors(dir_path: Path) -> List[Path]:
    """
    Collect ignore files from dir_path up to filesystem root.
    Order: root -> ... -> dir_path (top to bottom).
    """
    files: List[Path] = []
    cur = dir_path.resolve()
    ancestors: List[Path] = []
    while True:
        ancestors.append(cur)
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    for d in reversed(ancestors):
        for name in IGNORE_FILE_NAMES:
            p = d / name
            if p.is_file():
                files.append(p)
    return files

def build_composite_ignore(
    target_dir: Path,
    cwd: Path,
    g_param: Optional[str],
) -> Optional[CompositeIgnore]:
    """
    Decide which ignore files to use and build a single combined spec:

    - If g_param is "false" (case-insensitive), disable ignores entirely.
    - If g_param is a path, load ignore files from that folder and its ancestors.
    - Else, if target_dir is inside cwd, load ignore files along path from cwd to target_dir.
    - Else, load ignore files from target_dir and its ancestors.

    Precedence is preserved by concatenating patterns in the collected order
    (top to bottom); deeper rules appear later and override earlier ones.
    """
    if g_param is not None and g_param.strip().lower() == "false":
        return None

    files: List[Path] = []
    if g_param:
        base = Path(g_param).resolve()
        files.extend(collect_ignore_files_from_ancestors(base))
    else:
        try:
            _ = target_dir.resolve().relative_to(cwd.resolve())
            files.extend(collect_ignore_files_along_path(cwd, target_dir))
        except Exception:
            files.extend(collect_ignore_files_from_ancestors(target_dir))

    if not files:
        return None

    # Determine common anchor
    bases = [f.parent for f in files]
    anchor = _common_anchor(bases)

    # Read, normalize and rebase every pattern into anchor-relative form,
    # then build one combined spec in the same order as 'files'.
    combined_lines: List[str] = []
    for f in files:
        base = f.parent
        raw_lines = _read_lines(f)
        norm_lines = [_normalize_git_line(s) for s in raw_lines]
        rebased = [_rebase_pattern_to_anchor(s, base, anchor) for s in norm_lines]
        combined_lines.extend(rebased)

    # Build one spec using recommended API
    spec = PathSpec.from_lines("gitwildmatch", combined_lines)
    return CompositeIgnore(spec, files, anchor)
