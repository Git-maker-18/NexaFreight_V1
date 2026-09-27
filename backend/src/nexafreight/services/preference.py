"""Preference learning v1 (Task 14, P1): operators' revealed choices reorder
option slates.

Deliberately NOT a learned weight model (no blind alpha/beta/gamma): the
prior is an explainable, conservative reordering — an option family that
operators have NEVER chosen in a given (disruption type x cost band), across
at least MIN_SAMPLES historical decisions, is moved below the options that
do have acceptance there. The `recommended` flag stays the pure
cost-optimal answer; the prior only changes presentation order, and every
applied demotion is annotated in the option's assumptions list.

Data source: decision_outcomes rows (Task 12) joined decision -> alert ->
disruption. Cold start (fewer than MIN_SAMPLES in a band) = no reordering.
"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.models import Alert, Decision, DecisionOutcome, Disruption

MIN_SAMPLES = 3

BAND_EDGES = (0.0, 1000.0, 10000.0)


def cost_band(total_impact_usd: float) -> str:
    """Explainable cost band for an option's total impact (USD)."""
    if total_impact_usd <= BAND_EDGES[0]:
        return "nonpositive"
    if total_impact_usd <= BAND_EDGES[1]:
        return "low"
    if total_impact_usd <= BAND_EDGES[2]:
        return "mid"
    return "high"


async def preference_stats(session: AsyncSession) -> dict[tuple[str, str], dict[str, int]]:
    """Acceptance counts keyed by (disruption_type, cost_band) -> option_key -> n.

    Reads historical decisions only (phase-1 outcome rows are enough — the
    chosen option is what matters, realized numbers are not needed here).
    """
    rows = (
        await session.execute(
            select(DecisionOutcome, Alert, Disruption)
            .join(Decision, Decision.id == DecisionOutcome.decision_id)
            .join(Alert, Alert.id == Decision.alert_id)
            .join(Disruption, Disruption.id == Alert.disruption_id)
        )
    ).all()

    stats: dict[tuple[str, str], dict[str, int]] = {}
    for outcome, _alert, disruption in rows:
        key = (str(disruption.disruption_type), cost_band(outcome.predicted_total_impact_usd))
        bucket = stats.setdefault(key, {})
        bucket[outcome.chosen_option_key] = bucket.get(outcome.chosen_option_key, 0) + 1
    return stats


def apply_preference_prior(
    options: list,
    stats: dict[tuple[str, str], dict[str, int]],
    disruption_type: str,
    *,
    min_samples: int = MIN_SAMPLES,
) -> list:
    """Reorder the slate by revealed acceptance; pure function over options.

    - band = cost_band(option.total_impact_usd)
    - total = decisions recorded in (disruption_type, band)
    - an option with total >= min_samples and zero acceptances of its
      option_key is demoted below the rest (stable order inside each group)
    - `recommended` flags are never touched; demotions are annotated.
    """
    band_stats = {
        band: counts
        for (dt, band), counts in stats.items()
        if dt == str(disruption_type)
    }
    if not band_stats:
        return options

    kept: list = []
    demoted: list = []
    for option in options:
        band = cost_band(option.total_impact_usd)
        counts = band_stats.get(band, {})
        total = sum(counts.values())
        acceptance = counts.get(option.option_key, 0)
        if total >= min_samples and acceptance == 0:
            demoted.append(
                replace(
                    option,
                    assumptions=list(option.assumptions)
                    + [
                        f"preference prior: deprioritized — 0/{total} historical "
                        f"acceptance of {option.option_key} in band {band} "
                        f"({disruption_type})"
                    ],
                )
            )
        else:
            kept.append(option)
    return kept + demoted
