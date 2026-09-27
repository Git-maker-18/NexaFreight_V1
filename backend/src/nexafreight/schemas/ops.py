"""Pydantic response/request models for operational APIs (Definitive Plan).

Alerts, disruptions, decisions, analytics, copilot, shipment predict +
financials. Every response carries a `provenance` field (contract rule).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Disruptions
# ---------------------------------------------------------------------------


class DisruptionOut(BaseModel):
    """Public shape of one Disruption row."""

    id: str
    shipment_id: str
    leg_id: int | None = None
    disruption_type: str
    status: str
    description: str | None = None
    detected_at: datetime | None = None
    resolved_at: datetime | None = None


class DisruptionsResponse(BaseModel):
    disruptions: list[DisruptionOut]


class DisruptionCreate(BaseModel):
    """Operator-reported disruption (MANUAL analysis — Plan Phase 6).

    delay_hours overrides the detector's estimate when given.
    """

    shipment_id: str
    disruption_type: str
    delay_hours: float | None = Field(default=None, ge=0.0, le=168.0)
    description: str | None = None


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


class AlertOut(BaseModel):
    id: str
    shipment_id: str
    disruption_id: str | None = None
    disruption_type: str | None = None
    severity: str
    status: str
    financial_exposure: float
    created_at: datetime | None = None
    acknowledged_by: str | None = None
    provenance: str = "DERIVED"
    source: str | None = None


class SlaBreachOut(BaseModel):
    order_id: int | None = None
    order_number: str | None = None
    revenue_usd: float = 0.0
    days_late: int = 0
    penalty_usd: float = 0.0
    sla_deadline: str | None = None


class AlertDetail(AlertOut):
    disruption: DisruptionOut | None = None
    sla_breach_details: list[SlaBreachOut] | None = None
    description: str | None = None
    detected_at: datetime | None = None


class AlertsResponse(BaseModel):
    alerts: list[AlertOut]


class AcknowledgeRequest(BaseModel):
    user_id: int = 1  # operator id until SSO lands


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


class RerouteOptionOut(BaseModel):
    option_key: str
    action: str
    display_name: str
    description: str
    revised_eta: datetime | None = None
    cost_delta_usd: float
    sla_penalty_usd: float
    demurrage_usd: float
    carbon_cost_usd: float
    co2_delta_kg: float
    sla_breaches: int
    total_impact_usd: float
    recommended: bool
    assumptions: list[str] = Field(default_factory=list)


class OptionsOut(BaseModel):
    options: list[RerouteOptionOut]


class ApproveRequest(BaseModel):
    option_key: str
    user_id: int | None = None  # falls back to JWT identity


class DecisionOut(BaseModel):
    id: str
    alert_id: str | None = None
    shipment_id: str | None = None
    action: str
    chosen_option_key: str
    financial_impact: float
    route_version_before: int | None = None
    route_version_after: int | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    provenance: str = "DERIVED"


class DecisionsResponse(BaseModel):
    decisions: list[DecisionOut]


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


class ShipmentSummaryOut(BaseModel):
    id: str
    status: str
    mode: str
    origin: str | None = None
    destination: str | None = None


class AnalyticsSummaryResponse(BaseModel):
    total_shipments: int = 0
    in_transit: int = 0
    delivered: int = 0
    delayed: int = 0
    sla_breach_count: int = 0
    open_alerts: int = 0
    summary_by_status: dict[str, int] = Field(default_factory=dict)
    shipments: list[ShipmentSummaryOut] = Field(default_factory=list)
    provenance: str = "DERIVED"


class WindowSliceOut(BaseModel):
    period: str
    shipments: int = 0
    total_revenue: float = 0.0
    total_shipping_cost: float = 0.0
    decided_margin: float = 0.0
    undecided_revenue: float = 0.0
    undecided_pending_sla_est: float = 0.0
    undecided_pending_demurrage_est: float = 0.0
    undecided_total_pending_est: float = 0.0


class AnalyticsFinancialRow(BaseModel):
    shipment_id: str
    mode: str
    status: str
    revenue_usd: float
    shipping_cost_usd: float
    sla_penalty_usd: float
    demurrage_usd: float
    freight_cost_usd: float
    carbon_cost_usd: float
    total_costs_usd: float
    margin_usd: float
    margin_pct: float | None = None


class ProvenanceBucket(BaseModel):
    """Per-provenance rollup (E12: bake vs runtime made visible)."""

    shipments: int = 0
    revenue_usd: float = 0.0
    realized_cost_usd: float = 0.0
    pending_sla_est_usd: float = 0.0
    pending_demurrage_est_usd: float = 0.0


class AnalyticsFinancialResponse(BaseModel):
    day: WindowSliceOut
    week: WindowSliceOut
    month: WindowSliceOut
    rows: list[AnalyticsFinancialRow] = Field(default_factory=list)
    provenance: str = "DERIVED"
    by_provenance: dict[str, ProvenanceBucket] = Field(default_factory=dict)


class AnalyticsSlaRow(BaseModel):
    shipment_id: str
    sla_status: str
    days_to_deadline: float | None = None
    disrupted: bool = False
    disruption_description: str | None = None
    delay_days: float | None = None


class AnalyticsSlaResponse(BaseModel):
    rows: list[AnalyticsSlaRow] = Field(default_factory=list)
    provenance: str = "DERIVED"


class AnalyticsEsgRow(BaseModel):
    shipment_id: str
    mode: str
    kg_co2: float
    kg_co2e_per_container: float
    vs_air_co2_saving_pct: float | None = None
    vs_air_freight_delta_pct: float | None = None


class AnalyticsEsgResponse(BaseModel):
    rows: list[AnalyticsEsgRow] = Field(default_factory=list)
    route_breakdown: dict[str, int] = Field(default_factory=dict)
    provenance: str = "DERIVED"


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------


class CopilotAskRequest(BaseModel):
    shipment_id: str
    question: str = Field(min_length=1, max_length=1000)


class CopilotAskResponse(BaseModel):
    answer: str
    source: Literal["llm", "rules", "rules_fallback"]
    provenance: str = "DERIVED"


# ---------------------------------------------------------------------------
# Shipment predict + financials (Plan: new endpoints)
# ---------------------------------------------------------------------------


class ShipmentPredictResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    shipment_id: str
    delay_p50_hours: float
    sla_risk_level: str
    model_version: str | None = None
    provenance: str = "DERIVED"  # DERIVED | FALLBACK


class FinancialOrderOut(BaseModel):
    order_number: str
    revenue: float
    shipping_cost: float
    sla_status: str


class PnlSnapshotOut(BaseModel):
    revenue_usd: float
    shipping_cost_usd: float
    sla_penalty_usd: float
    demurrage_usd: float
    freight_cost_usd: float
    carbon_cost_usd: float
    total_costs_usd: float
    margin_usd: float
    margin_pct: float | None = None
    warnings: list[str] = Field(default_factory=list)


class ShipmentFinancialsResponse(BaseModel):
    shipment_id: str
    container_count: int
    container_weight_t: float
    orders: list[FinancialOrderOut]
    pnl: PnlSnapshotOut
    provenance: str = "DERIVED"
