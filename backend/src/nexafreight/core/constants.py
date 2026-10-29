"""Authoritative multimodal physical and ESG constants for NexaFreight Control Tower.

Sources:
- GLEC Framework v3.2 (Smart Freight Centre, 2023):
  * SEA: Deep-sea container shipping (8.0 g CO2/t-km) - weighted average across
    Panamax (3,000–5,000 TEU @ 9.1 g/t-km) and Post-Panamax (>8,000 TEU @ 7.6 g/t-km).
  * ROAD: Heavy articulated diesel line-haul truck >32t (62.0 g CO2/t-km).
  * RAIL: Electric and diesel mixed freight train average (28.0 g CO2/t-km).
  * AIR: Dedicated freighter cargo aircraft belly and main deck average (602.0 g CO2/t-km).
"""

from __future__ import annotations

# GLEC Framework v3.2 default multimodal emission factors (g CO2 per tonne-km)
GLEC_CO2_G_PER_TONNE_KM: dict[str, float] = {
    "SEA": 8.0,
    "ROAD": 62.0,
    "RAIL": 28.0,
    "AIR": 602.0,
}

# Standard carbon price: USD 80 / tonne = USD 0.08 / kg CO2
CARBON_COST_PER_KG: float = 0.08
