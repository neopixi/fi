from __future__ import annotations

def count_tokens(text: str) -> tuple[int, str]:
    """
    Try tiktoken for exact count. Fallback to a rough estimate.
    Returns (count, method).
    """
    try:
        import tiktoken  # optional
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text)), "tiktoken(cl100k_base)"
    except Exception:
        # Rough heuristic: ~4 chars per token (common rule of thumb)
        # Count words + punctuation as proxy.
        approx = max(1, int(len(text) / 4))
        return approx, "estimate(~4 chars/token)"
