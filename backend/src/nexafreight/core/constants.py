"""Authoritative multimodal physical and ESG constants for NexaFreight Control Tower.

Emission factors are specified using GLEC default intensity factors (basis not independently verified)
(g CO2 per tonne-km):
- GLEC default intensity factors (basis not independently verified):
  * SEA: Deep-sea container shipping (8.0 g CO2/t-km).
  * ROAD: Heavy articulated diesel line-haul truck >32t (62.0 g CO2/t-km).
  * RAIL: Electric and diesel mixed freight train average (28.0 g CO2/t-km).
  * AIR: Dedicated freighter and air cargo average (602.0 g CO2/t-km).
"""

from __future__ import annotations

# GLEC default intensity factors (basis not independently verified) (g CO2 per tonne-km)
GLEC_CO2_G_PER_TONNE_KM: dict[str, float] = {
    "SEA": 8.0,
    "ROAD": 62.0,
    "RAIL": 28.0,
    "AIR": 602.0,
}

# Standard carbon price: USD 80 / tonne = USD 0.08 / kg CO2
CARBON_COST_PER_KG: float = 0.08
