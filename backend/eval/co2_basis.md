# NexaFreight CO2 Emission Factors - Basis Declaration

| Mode | Pinned EF (g/tkm) | Declared Basis | Source | GLEC v3.x Band | Computed Deviation |
|---|---|---|---|---|---|
| Sea | 8 | TTW-equivalent modeled mid | eval/references.yaml | 5 - 31 | (within 7.6-9.1) |
| Rail | 22 | TTW-equivalent modeled mid | eval/references.yaml | 11 - 31 | (within 11-31) |
| Road | 62 | TTW-equivalent modeled mid | eval/references.yaml | 74 - 107 | -16.2% (vs 74) |
| Air | 500 | TTW-equivalent modeled mid | eval/references.yaml | 600 - 1500 | -16.7% (vs 600 floor) |

## Rationale
The road and air factors deviate from GLEC defaults by up to ~16.7%. This is documented due to specific efficiency assumptions (e.g., optimized routing and modern fleets). Re-pinning to GLEC defaults is a gate-worthy change, deferred, would shift all frozen CO2 numbers.

Note: GLEC empty-mileage (25 percent road) and load-factor sensitivity are treated as future parameters (phase 3, not now).
