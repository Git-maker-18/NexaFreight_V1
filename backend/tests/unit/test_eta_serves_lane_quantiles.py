"""Proof test: /predictions and /shipments serve the lane-quantile table and NEVER load model.joblib (PR 2, 2B/6)."""
from __future__ import annotations

import unittest.mock as mock
from datetime import UTC, datetime, timedelta
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from nexafreight.enums import LegStatus, ShipmentStatus, TransportMode
from nexafreight.ml.registry import ModelRegistry


@pytest.mark.asyncio
async def test_predict_eta_serves_lane_quantiles_never_loads_joblib(
    test_app: FastAPI,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """Proof that POST /api/predict/eta serves from LANE_QUANTILES_TABLE and never loads model.joblib."""
    import joblib
    original_load = joblib.load

    def guarded_load(path, *args, **kwargs):
        path_str = str(path).replace("\\", "/")
        if "eta_quantile/model.joblib" in path_str:
            raise AssertionError(f"VIOLATION: Attempted to load {path_str} from disk!")
        return original_load(path, *args, **kwargs)

    with mock.patch("joblib.load", side_effect=guarded_load):
        test_app.state.ml_registry = ModelRegistry()

        # 1. SEA mode: residual p10=-2.0, p50=0.0, p85=2.0
        sea_payload = {
            "shipping_mode": "SEA",
            "cargo_class": "STANDARD",
            "revenue": 1000.0,
            "shipping_cost": 100.0,
            "scheduled_shipping_days": 10.0,
            "order_country": "US",
            "customer_country": "IN",
            "product_price": 50.0,
            "order_profit": 50.0,
            "sla_month": 5,
            "sla_weekday": 2,
            "sla_quarter": 2,
            "total_distance_km": 5000.0,
            "leg_count": 2,
        }
        resp = await client.post("/api/predict/eta", json=sea_payload, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Scheduled 10.0 + SEA residuals [-2, 0, 2]
        assert data["p10_eta_days"] == 8.0
        assert data["p50_eta_days"] == 10.0
        assert data["p85_eta_days"] == 12.0
        assert data["confidence_interval_width"] == 4.0
        assert data["provenance"] == "DERIVED"

        # 2. AIR mode: residual p10=0.0, p50=1.0, p85=1.0
        air_payload = dict(sea_payload, shipping_mode="AIR", scheduled_shipping_days=3.0)
        resp_air = await client.post("/api/predict/eta", json=air_payload, headers=auth_headers)
        assert resp_air.status_code == 200, resp_air.text
        data_air = resp_air.json()

        assert data_air["p10_eta_days"] == 3.0
        assert data_air["p50_eta_days"] == 4.0
        assert data_air["p85_eta_days"] == 4.0
        assert data_air["confidence_interval_width"] == 1.0
        assert data_air["provenance"] == "DERIVED"


@pytest.mark.asyncio
async def test_shipment_predict_serves_lane_quantiles_never_loads_joblib(
    test_app: FastAPI,
    client: AsyncClient,
    make_shipment,
    make_order,
    make_leg,
    auth_headers: dict[str, str],
) -> None:
    """Proof that GET /api/shipments/{id}/predict serves from LANE_QUANTILES_TABLE and never loads model.joblib."""
    import joblib
    original_load = joblib.load

    def guarded_load(path, *args, **kwargs):
        path_str = str(path).replace("\\", "/")
        if "eta_quantile/model.joblib" in path_str:
            raise AssertionError(f"VIOLATION: Attempted to load {path_str} from disk!")
        return original_load(path, *args, **kwargs)

    with mock.patch("joblib.load", side_effect=guarded_load):
        test_app.state.ml_registry = ModelRegistry()

        shipment = await make_shipment(status=ShipmentStatus.IN_TRANSIT, primary_transport_mode="SEA")
        now = datetime.now(UTC)
        await make_leg(
            shipment.id,
            status=LegStatus.PLANNED,
            mode=TransportMode.SEA,
            planned_departure=now - timedelta(days=2),
            planned_arrival=now + timedelta(days=8),
        )
        await make_order(
            shipment=shipment,
            order_number="ORD-LANE-QUANTILE-TEST",
            revenue=2000.0,
            shipping_cost=200.0,
            sla_deadline=now + timedelta(days=10),
        )

        resp = await client.get(
            f"/api/shipments/{shipment.id}/predict",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["provenance"] == "DERIVED"
        assert "delay_p50_hours" in data
        assert "sla_risk_level" in data
