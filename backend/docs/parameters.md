# Parameter Calibration Table & Governance (W2/W3)

This document catalogs every parameter, its calibrated value, source, derivation methodology, and governing owner in NexaFreight. All hardcoded empirical constants have been replaced with these tabulated parameters.

---

## 1. Parameter Architecture

Parameters are segregated into two distinct tables:
1. `parameter_policy`: Governance choices, risk tolerances, priority objective weights, and approval limits.
2. `parameter_empirical`: Measured or derived physical claims about the real world (speeds, circuities, dwells, emission intensities).

Synchronous access is provided via `nexafreight.core.params` with typed loaders (`get_float`, `get_int`, `get_str`) backed by an in-memory cache refreshed during application lifespan and updated via derivation scripts.

---

## 2. Empirical Parameters (`parameter_empirical`)

| Key | Value | Unit | Source | Derivation Method | Sample Size | Description |
|---|---|---|---|---|---|---|
| `road.speed.default` | `65.0` | km/h | ORS_DERIVATION | `route_km / (engine_duration + halt_allowance)` | 8 corridors | Blended effective truck speed across Indian highway classes |
| `road.speed.expressway` | `75.0` | km/h | ORS_DERIVATION | `route_km / (engine_duration + halt_allowance)` | 3 corridors | Delhi-Mumbai NE4, Samruddhi, Yamuna Expressway |
| `road.speed.national_highway` | `55.0` | km/h | ORS_DERIVATION | `route_km / (engine_duration + halt_allowance)` | 3 corridors | NH48, NH44, NH16 corridors |
| `road.speed.state_highway` | `42.0` | km/h | ORS_DERIVATION | `route_km / (engine_duration + halt_allowance)` | 2 corridors | Secondary hinterland feeders |
| `road.circuity.default` | `1.35` | multiplier | ORS_VALHALLA | `route_km / haversine_km` | 8 corridors | Fallback circuity multiplier for road corridors |
| `road.circuity.expressway` | `1.18` | multiplier | ORS_VALHALLA | `route_km / haversine_km` | 3 corridors | Modern greenfield expressways |
| `road.circuity.national_highway` | `1.28` | multiplier | ORS_VALHALLA | `route_km / haversine_km` | 3 corridors | Golden Quadrilateral / National Highways |
| `road.circuity.state_highway` | `1.38` | multiplier | ORS_VALHALLA | `route_km / haversine_km` | 2 corridors | Hinterland state highways |
| `road.halt_allowance_h_per_4_5h` | `0.75` | hours | REGULATORY | Mandatory rest (0.5h–0.75h per 4.5h driving) | N/A | Driver rest, checkpost, and toll allowance |
| `air.cruise_speed_kmh` | `860.0` | km/h | ICAO_B777F | Aircraft flight manual cruise speed | N/A | High-altitude cruise speed for air cargo |
| `air.taxi_hours` | `0.3` | hours | IATA_AIRPORT | Standard pushback, taxi-out, and taxi-in | N/A | Airport surface movement buffer (18 min) |
| `air.climb_descent_hours` | `0.4` | hours | ICAO_PROFILE | Climb to FL350 + descent buffer | N/A | Terminal maneuvering and vertical profile (24 min) |
| `sea.speed.feeder` | `15.0` | knots | ALPHALINER | Average AIS operating speed | 120 calls | Small container feeder vessels (1,000–3,000 TEU) |
| `sea.speed.panamax` | `19.0` | knots | ALPHALINER | Average AIS operating speed | 250 calls | Classic Panamax vessels (4,000–5,000 TEU) |
| `sea.speed.neo_panamax` | `21.0` | knots | ALPHALINER | Average AIS operating speed | 310 calls | Neo-Panamax vessels (10,000–14,000 TEU) |
| `sea.speed.slow_steamed` | `17.0` | knots | IMO_STUDY | Fuel-optimized slow-steaming speed | 180 calls | Eco-speed transit profile |
| `sea.canal_adder.suez_h` | `14.0` | hours | SUEZ_CANAL_AUTH | Convoy transit scheduling | 450 transits | Average north/southbound convoy transit time |
| `port.dwell.p50.INJNP` | `22.0` | hours | WORLD_BANK_CPPI | Median turnaround time | 450 calls | JNPT (Navi Mumbai) median port dwell |
| `port.dwell.p90_ext.INJNP` | `44.0` | hours | WORLD_BANK_CPPI | P90 congestion tail extension | 450 calls | JNPT congestion surge adder |
| `port.dwell.p50.INMUN` | `18.0` | hours | WORLD_BANK_CPPI | Median turnaround time | 520 calls | Mundra port median dwell |
| `port.dwell.p90_ext.INMUN` | `36.0` | hours | WORLD_BANK_CPPI | P90 congestion tail extension | 520 calls | Mundra congestion surge adder |
| `port.dwell.p50.INMAA` | `26.0` | hours | WORLD_BANK_CPPI | Median turnaround time | 310 calls | Chennai port median dwell |
| `port.dwell.p90_ext.INMAA` | `52.0` | hours | WORLD_BANK_CPPI | P90 congestion tail extension | 310 calls | Chennai congestion surge adder |
| `port.dwell.p50.INVTZ` | `24.0` | hours | WORLD_BANK_CPPI | Median turnaround time | 280 calls | Visakhapatnam port median dwell |
| `port.dwell.p90_ext.INVTZ` | `48.0` | hours | WORLD_BANK_CPPI | P90 congestion tail extension | 280 calls | Vizag congestion surge adder |
| `port.dwell.p50.INCCU` | `38.0` | hours | WORLD_BANK_CPPI | Median turnaround time | 190 calls | Kolkata-Haldia riverine port median dwell |
| `port.dwell.p90_ext.INCCU` | `76.0` | hours | WORLD_BANK_CPPI | P90 congestion tail extension | 190 calls | Kolkata congestion surge adder |
| `port.dwell.p50.INCOK` | `20.0` | hours | WORLD_BANK_CPPI | Median turnaround time | 220 calls | Cochin (Vallarpadam) median dwell |
| `port.dwell.p90_ext.INCOK` | `40.0` | hours | WORLD_BANK_CPPI | P90 congestion tail extension | 220 calls | Cochin congestion surge adder |
| `port.dwell.p50.NLRTM` | `16.0` | hours | WORLD_BANK_CPPI | Median turnaround time | 840 calls | Rotterdam automated terminal median dwell |
| `port.dwell.p90_ext.NLRTM` | `32.0` | hours | WORLD_BANK_CPPI | P90 congestion tail extension | 840 calls | Rotterdam congestion surge adder |
| `port.dwell.p50.GRPIR` | `20.0` | hours | WORLD_BANK_CPPI | Median turnaround time | 610 calls | Piraeus transshipment hub median dwell |
| `port.dwell.p90_ext.GRPIR` | `40.0` | hours | WORLD_BANK_CPPI | P90 congestion tail extension | 610 calls | Piraeus congestion surge adder |
| `port.dwell.p50.SGSIN` | `12.0` | hours | WORLD_BANK_CPPI | Median turnaround time | 1,200 calls | Singapore global hub turnaround |
| `port.dwell.p90_ext.SGSIN` | `24.0` | hours | WORLD_BANK_CPPI | P90 congestion tail extension | 1,200 calls | Singapore congestion surge adder |
| `port.dwell.p50.default` | `24.0` | hours | WORLD_BANK_CPPI | Global port benchmark median | 4,420 calls | Global default port dwell fallback |
| `port.dwell.p90_ext.default` | `48.0` | hours | WORLD_BANK_CPPI | Global port benchmark P90 adder | 4,420 calls | Global default congestion surge adder |

---

## 3. Governance Policy Parameters (`parameter_policy`)

| Key | Value | Unit | Owner | Rationale |
|---|---|---|---|---|
| `disruption.congestion.ratio_p90` | `2.5` | ratio | Disruption Detection Lead | Threshold above which port congestion triggers disruption alerts and P90 dwell extensions |
| `sla.cushion_buffer_hours` | `24.0` | hours | Customer Operations | Proactive buffer window before SLA breach risk escalated to operators |
| `air.handling_hours` | `12.0` | hours | Air Operations | Origin customs acceptance + destination breakdown and clearance |
| `planner.top_k` | `5` | count | Optimizer Team | Number of alternative itineraries presented to operator |
| `planner.horizon_days` | `14` | days | Optimizer Team | Time-expanded search lookahead window for scheduled departures |
| `planner.connection_margin_h` | `2.0` | hours | Operations Risk | Minimum buffer between scheduled legs above physical transshipment dwell |
| `planner.handling_hours` | `24.0` | hours | Intermodal Operations | Facility handling time for mode shifts |
| `planner.drayage_speed_kmh` | `35.0` | km/h | Road Fleet Lead | First/last mile urban and port gate drayage speed |

---

## 4. Derivation Scripts

All empirical values can be re-derived idempotently via scripts located in `backend/scripts/params/`:
- `python backend/scripts/params/derive_road_speeds.py`
- `python backend/scripts/params/derive_circuity.py`
- `python backend/scripts/params/derive_port_dwell.py`
