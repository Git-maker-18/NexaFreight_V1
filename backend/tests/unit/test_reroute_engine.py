"""Unit tests for the reroute engine (Definitive Plan — Phase 5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.enums import AlertSeverity, AlertStatus, LegStatus, TransportMode
from nexafreight.exceptions import ResourceNotFoundError
from nexafreight.models import Alert, CorridorAlternative, Disruption
from nexafreight.services.reroute_engine import generate_options

pytestmark = pytest.mark.asyncio

NOW = datetime.now(UTC)


async def _traffic_jam(
    db_session, make_shipment, make_order, make_leg, make_location, *, delay_hours: float = 50.0
):
    """Sea shipment NYC→Rotterdam, one 5000 km PLANNED sea leg, 20000 order.

    Geometry tuned so an extra 36h from the corridor makes the ETA 1 day
    late (1000 SLA), and the disruption's own +50h make it 2 days late
    (2000 SLA).
    """
    nyc = await make_location(locode="USNYC", name="New York", latitude=40.7128, longitude=-74.006)
    rotterdam = await make_location(
        locode="NLRTM", name="Rotterdam", country_code="NL", latitude=51.9225, longitude=4.479
    )
    shipment = await make_shipment(
        origin=nyc,
        destination=rotterdam,
        status="IN_TRANSIT",
        primary_transport_mode=TransportMode.SEA,
        container_count=2,
    )
    leg = await make_leg(
        shipment_id=shipment.id,
        sequence_number=1,
        mode=TransportMode.SEA,
        status=LegStatus.PLANNED,
        origin=nyc,
        destination=rotterdam,
        planned_departure=NOW - timedelta(days=1),
        planned_arrival=NOW + timedelta(days=10, hours=6),
    )
    leg.distance_km = 5000.0

    order = await make_order(
        order_number="ORD-RT-1",
        shipment=shipment,
        revenue=20_000.0,
        shipping_cost=1_500.0,
        sla_deadline=NOW + timedelta(days=11, hours=6),
    )

    disruption = Disruption(
        shipment_id=shipment.id,
        disruption_type="PORT_CONGESTION",
        status="ACTIVE",
        description="congestion",
        detected_at=datetime.now(UTC),
    )
    db_session.add(disruption)
    await db_session.flush()

    alert = Alert(
        disruption_id=disruption.id,
        shipment_id=shipment.id,
        severity=AlertSeverity.HIGH,
        status=AlertStatus.OPEN,
        financial_exposure=2_000.0,
        sla_breach_details_json=json.dumps(
            {
                "breaches": [
                    {
                        "order_id": order.id,
                        "order_number": order.order_number,
                        "revenue_usd": 20_000.0,
                        "days_late": 2,
                        "penalty_usd": 2_000.0,
                    }
                ],
                "sla_penalty_total_usd": 2_000.0,
                "demurrage_total_usd": 0.0,
                "estimated_delay_hours": delay_hours,
                "revised_eta": None,
            }
        ),
    )
    db_session.add(alert)
    await db_session.commit()
    await db_session.refresh(alert, ["disruption"])
    return {"shipment": shipment, "order": order, "leg": leg, "alert": alert}


async def _corridor(db_session, **overrides) -> CorridorAlternative:
    corridor = CorridorAlternative(
        option_key=overrides.get("option_key", "VIA_PIRAEUS"),
        display_name=overrides.get("display_name", "Divert via Piraeus"),
        applicable_disruption_types_json=json.dumps(
            overrides.get("types", ["PORT_CONGESTION"])
        ),
        route_template_json=json.dumps(
            overrides.get("template", {"legs": [{"mode": "SEA", "to": "DESTINATION"}]})
        ),
        cost_delta_factor=overrides.get("cost_delta_factor", 1.2),
        time_delta_hours=overrides.get("time_delta_hours", 30.0),
        co2_delta_factor=overrides.get("co2_delta_factor", 1.1),
    )
    db_session.add(corridor)
    await db_session.commit()
    return corridor


async def test_exactly_three_options_stable_order(
    db_session: AsyncSession, make_shipment, make_order, make_leg, make_location
) -> None:
    fx = await _traffic_jam(db_session, make_shipment, make_order, make_leg, make_location)
    await _corridor(db_session)

    options = await generate_options(db_session, fx["alert"], now=NOW)
    assert len(options) == 3
    assert options[0].option_key == "ACCEPT_DELAY"
    assert options[1].action == "REROUTE"
    assert options[2].option_key == "MODAL_SHIFT_AIR"


async def test_recommendation_is_single_and_lowest_impact(
    db_session: AsyncSession, make_shipment, make_order, make_leg, make_location
) -> None:
    fx = await _traffic_jam(db_session, make_shipment, make_order, make_leg, make_location)
    await _corridor(db_session)

    options = await generate_options(db_session, fx["alert"], now=NOW)
    recommended = [o for o in options if o.recommended]
    assert len(recommended) == 1
    assert recommended[0].option_key == "VIA_PIRAEUS"
    assert recommended[0].total_impact_usd == min(o.total_impact_usd for o in options)


async def test_accept_delay_option_math(
    db_session: AsyncSession, make_shipment, make_order, make_leg, make_location
) -> None:
    fx = await _traffic_jam(db_session, make_shipment, make_order, make_leg, make_location)

    options = await generate_options(db_session, fx["alert"], now=NOW)
    accept = options[0]
    assert accept.cost_delta_usd == 0.0
    # 50h + base ETA → 2 days past deadline → 20000 × 5% × 2 = 2000
    assert accept.sla_penalty_usd == 2_000.0
    # 3 days delay < 4 demurrage free days → 0
    assert accept.demurrage_usd == 0.0
    assert accept.total_impact_usd == 2_000.0
    # ETA = latest planned arrival (NOW+10d6h) + 50h = NOW+12d8h
    expected_eta = fx["leg"].planned_arrival + timedelta(hours=50)
    assert accept.revised_eta == expected_eta.replace(tzinfo=None) or accept.revised_eta.replace(tzinfo=None) == expected_eta.replace(tzinfo=None)


async def test_accept_delay_falls_back_to_24h_when_payload_missing(
    db_session: AsyncSession, make_shipment, make_order, make_leg, make_location
) -> None:
    fx = await _traffic_jam(db_session, make_shipment, make_order, make_leg, make_location)
    fx["alert"].sla_breach_details_json = "{}"  # no delay estimate
    await db_session.commit()

    options = await generate_options(db_session, fx["alert"], now=NOW)
    accept = options[0]
    # 24h delay → ETA NOW+11d6h → deadline exactly at ETA → on time → 0
    expected_eta = fx["leg"].planned_arrival + timedelta(hours=24)
    assert accept.revised_eta.replace(tzinfo=None) == expected_eta.replace(tzinfo=None)
    assert accept.sla_penalty_usd == 0.0


async def test_corridor_picks_least_added_time(
    db_session: AsyncSession, make_shipment, make_order, make_leg, make_location
) -> None:
    fx = await _traffic_jam(db_session, make_shipment, make_order, make_leg, make_location)
    await _corridor(db_session, option_key="SLOW", time_delta_hours=60.0)
    piraeus = await _corridor(db_session, option_key="VIA_PIRAEUS", time_delta_hours=30.0)

    options = await generate_options(db_session, fx["alert"], now=NOW)
    divert = options[1]
    assert divert.option_key == "VIA_PIRAEUS"
    assert divert.corridor_alternative_id == piraeus.id


async def test_divert_corridor_financial_math(
    db_session: AsyncSession, make_shipment, make_order, make_leg, make_location
) -> None:
    fx = await _traffic_jam(db_session, make_shipment, make_order, make_leg, make_location)
    await _corridor(db_session)

    options = await generate_options(db_session, fx["alert"], now=NOW)
    divert = options[1]
    # freight: 5000km × 28t × $0.02 = 2800 → ×1.2 ⇒ Δ 560
    assert divert.cost_delta_usd == pytest.approx(560.0)
    # co2: 6.5 g/t-km × 5000 × 28 /1000 = 910 kg → ×1.1 ⇒ Δ91 kg → $7.28
    assert divert.co2_delta_kg == pytest.approx(91.0)
    assert divert.carbon_cost_usd == pytest.approx(7.28)
    # ETA has 30h added → crosses deadline by 6h → 1 day late → 1000
    assert divert.sla_penalty_usd == 1_000.0
    # 2 days < 4 demurrage free days
    assert divert.demurrage_usd == 0.0
    assert divert.total_impact_usd == pytest.approx(1567.28)
    assert divert.route_template is not None


async def test_generic_fallback_when_no_corridor_matches(
    db_session: AsyncSession, make_shipment, make_order, make_leg, make_location
) -> None:
    fx = await _traffic_jam(db_session, make_shipment, make_order, make_leg, make_location)
    # Disruption is PORT_CONGESTION; corridor only matches WEATHER
    await _corridor(db_session, types=["WEATHER"])

    options = await generate_options(db_session, fx["alert"], now=NOW)
    divert = options[1]
    assert divert.option_key == "DIVERT_GENERIC"
    assert "legs" in divert.route_template
    assert len(divert.route_template["legs"]) >= 1


async def test_modal_shift_option_math(
    db_session: AsyncSession, make_shipment, make_order, make_leg, make_location
) -> None:
    fx = await _traffic_jam(db_session, make_shipment, make_order, make_leg, make_location)

    options = await generate_options(db_session, fx["alert"], now=NOW)
    modal = options[2]
    assert modal.option_key == "MODAL_SHIFT_AIR"
    # air: 1.8 × 5000 × 28 = 252000 vs sea 2800 → Δ 249200
    assert modal.cost_delta_usd == pytest.approx(249_200.0)
    # co2: (500 − 6.5) g/t-km × 5000 × 28 /1000 = 69090 kg
    assert modal.co2_delta_kg == pytest.approx(69_090.0)
    # air ETA = now + 5000/800 + 12h → ~18h — well before the deadline
    assert modal.sla_penalty_usd == 0.0
    assert modal.total_impact_usd > 200_000.0


async def test_modal_shift_revised_eta_uses_now_as_anchor(
    db_session: AsyncSession, make_shipment, make_order, make_leg, make_location
) -> None:
    fx = await _traffic_jam(db_session, make_shipment, make_order, make_leg, make_location)
    options = await generate_options(db_session, fx["alert"], now=NOW)
    modal = options[2]
    from nexafreight.core import params
    speed = params.get_float("air.cruise_speed_kmh", 860.0)
    taxi = params.get_float("air.taxi_hours", 0.3)
    climb = params.get_float("air.climb_descent_hours", 0.4)
    handling = params.get_float("air.handling_hours", 12.0)
    transit_hours = 5000 / speed + taxi + climb + handling
    assert modal.revised_eta == NOW + timedelta(hours=transit_hours)


async def test_options_for_shipment_without_orders(
    db_session: AsyncSession, make_shipment, make_leg, make_location
) -> None:
    """No orders on the shipment → zero SLA impact; options still render."""
    nyc = await make_location(locode="USNYC", name="New York")
    shipment = await make_shipment(status="IN_TRANSIT", container_count=1)
    await make_leg(
        shipment_id=shipment.id,
        status=LegStatus.PLANNED,
        origin=nyc,
        planned_departure=NOW,
        planned_arrival=NOW + timedelta(days=5),
    )
    disruption = Disruption(
        shipment_id=shipment.id,
        disruption_type="WEATHER",
        status="ACTIVE",
        description="storm",
        detected_at=datetime.now(UTC),
    )
    db_session.add(disruption)
    await db_session.flush()
    alert = Alert(
        disruption_id=disruption.id,
        shipment_id=shipment.id,
        severity="MEDIUM",
        status="OPEN",
        financial_exposure=0.0,
        sla_breach_details_json="{}",
    )
    db_session.add(alert)
    await db_session.commit()
    await db_session.refresh(alert, ["disruption"])

    options = await generate_options(db_session, alert, now=NOW)
    assert len(options) == 3
    assert all(o.sla_penalty_usd == 0.0 for o in options)
    assert sum(1 for o in options if o.recommended) == 1


async def test_generate_options_missing_shipment_raises_404(
    db_session: AsyncSession,
) -> None:
    # In-memory alert pointing at a shipment that no longer exists (no
    # persistence — FK rules would reject an orphan row outright).
    alert = Alert(
        shipment_id="no-such-shipment",
        severity="LOW",
        status="OPEN",
        financial_exposure=0.0,
        sla_breach_details_json="{}",
    )
    with pytest.raises(ResourceNotFoundError):
        await generate_options(db_session, alert, now=NOW)
