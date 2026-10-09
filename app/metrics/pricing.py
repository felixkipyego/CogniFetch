from typing import Optional

# Best-effort $/1M-token published OpenAI rates, used only to estimate cost
# for display in the admin panel — NOT a real billing figure. Two caveats,
# carried over from eval/BASELINE.md's Phase 0 cost measurement:
#   1. This project's configured OPENAI_API_BASE may point at a third-party
#      gateway rather than api.openai.com directly, whose actual rates can
#      differ from OpenAI's published ones entirely.
#   2. A model name not in this table (including anything the admin panel's
#      runtime config swaps in) returns None, not 0 — an unpriced run must
#      show up as "unknown" in aggregates, never be silently counted as free.
# (input_usd_per_1m, output_usd_per_1m)
_RATES_USD_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-3.5-turbo": (0.50, 1.50),
}


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> Optional[float]:
    rates = _RATES_USD_PER_1M.get(model)
    if rates is None:
        return None
    input_rate, output_rate = rates
    return (prompt_tokens / 1_000_000) * input_rate + (completion_tokens / 1_000_000) * output_rate
