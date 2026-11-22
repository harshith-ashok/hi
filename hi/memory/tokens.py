"""A cheap token estimate, shared by the history budget and the artifact context. No tokenizer dependency."""


def estimate_tokens(text: str) -> int:
    """About three characters a token, a little generous for code."""
    return len(text) // 3 + 1
