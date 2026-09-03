"""Model pricing.

Rates are **configuration, not code**. No prices are hard-coded here,
because a hard-coded rate goes stale silently and produces confidently wrong
cost figures -- the same failure mode as a fabricated market price (Rule 4).

Operators supply rates through `AI_MODEL_PRICING` in the environment, as
JSON:

    AI_MODEL_PRICING={"claude-sonnet-5": {"input": 3.0, "output": 15.0,
                      "cache_read": 0.3, "cache_write": 3.75}}

All values are **per million tokens**, in `AI_PRICING_CURRENCY`.

A model with no configured rate produces `AICost.unknown(...)`, never a
zero. An unpriced model must not look free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ai.schemas import AICost, AIUsage
from config.logging import get_logger

logger = get_logger("ai")


@dataclass(frozen=True)
class ModelPricing:
    """Per-million-token rates.

    Cache reads and writes are priced separately because they genuinely are:
    a cache write typically costs more than an ordinary input token and a
    read substantially less. Collapsing them would make caching look free,
    and caching a prefix that is never reused is a real way to lose money.
    """

    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float | None = None
    cache_write_per_mtok: float | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, float]) -> ModelPricing:
        return cls(
            input_per_mtok=float(raw["input"]),
            output_per_mtok=float(raw["output"]),
            cache_read_per_mtok=(
                float(raw["cache_read"]) if raw.get("cache_read") is not None else None
            ),
            cache_write_per_mtok=(
                float(raw["cache_write"]) if raw.get("cache_write") is not None else None
            ),
        )


class PricingTable:
    def __init__(self, rates: dict[str, ModelPricing], currency: str = "USD") -> None:
        self._rates = rates
        self._currency = currency

    @classmethod
    def from_settings(cls, settings: object) -> PricingTable:
        raw = getattr(settings, "ai_model_pricing", "") or ""
        currency = getattr(settings, "ai_pricing_currency", "USD") or "USD"
        if not raw.strip():
            return cls({}, currency)

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Loud, and then empty. Silently treating malformed pricing as
            # "no pricing" is fine; silently treating it as "free" is not,
            # and an empty table yields unknown costs rather than zero ones.
            logger.warning(
                "ai_pricing_malformed",
                operation="from_settings",
                status="ignored",
                error=f"{type(exc).__name__}",
            )
            return cls({}, currency)

        rates: dict[str, ModelPricing] = {}
        for model, values in parsed.items():
            try:
                rates[model] = ModelPricing.from_dict(values)
            except (KeyError, TypeError, ValueError):
                logger.warning(
                    "ai_pricing_model_invalid",
                    operation="from_settings",
                    status="skipped",
                    model=model,
                )
        return cls(rates, currency)

    def has(self, model: str) -> bool:
        return model in self._rates

    def priced_models(self) -> list[str]:
        return sorted(self._rates)

    def estimate(self, model: str, usage: AIUsage) -> AICost:
        """Cost for observed usage, or an explicit unknown."""
        pricing = self._rates.get(model)
        if pricing is None:
            return AICost.unknown(
                f"No configured price for model {model!r}. Set AI_MODEL_PRICING."
            )
        if usage.input_tokens is None or usage.output_tokens is None:
            return AICost.unknown(
                "Provider did not report token usage, so cost cannot be computed."
            )

        total = (usage.input_tokens / 1e6) * pricing.input_per_mtok
        total += (usage.output_tokens / 1e6) * pricing.output_per_mtok

        if usage.cache_read_tokens:
            rate = pricing.cache_read_per_mtok
            if rate is None:
                return AICost.unknown(
                    f"Model {model!r} reported cached reads but has no configured "
                    "cache_read rate."
                )
            total += (usage.cache_read_tokens / 1e6) * rate

        if usage.cache_write_tokens:
            rate = pricing.cache_write_per_mtok
            if rate is None:
                return AICost.unknown(
                    f"Model {model!r} reported cache writes but has no configured "
                    "cache_write rate."
                )
            total += (usage.cache_write_tokens / 1e6) * rate

        return AICost(amount=round(total, 6), currency=self._currency, known=True)

    def project(self, model: str, input_chars: int, max_output_tokens: int) -> AICost:
        """Pre-flight worst-case estimate, used for budget checks.

        Assumes the full `max_output_tokens` is produced, deliberately.
        Under-estimating and discovering afterwards that the budget was
        exceeded is not a budget.
        """
        return self.estimate(
            model,
            AIUsage(
                input_tokens=max(1, input_chars // CHARS_PER_TOKEN_ESTIMATE),
                output_tokens=max_output_tokens,
            ),
        )


# Rough English-text ratio, used only for pre-flight projection -- never for
# billing, which always uses provider-reported counts.
CHARS_PER_TOKEN_ESTIMATE = 4
