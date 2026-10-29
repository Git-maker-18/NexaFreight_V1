"""
Map endpoints — GET /api/map/*  (T-031).

Five endpoints:
  1. GET /positions/stream    — SSE live position stream (5 s interval)
  2. GET /positions/snapshot  — single JSON snapshot of all positions
  3. GET /routes              — active leg geometries as GeoJSON FeatureCollection
  4. GET /ports               — port locations and congestion as GeoJSON FeatureCollection
  5. GET /feed-health         — adapter health statuses

All endpoints are read-only and require authentication (T-010).

Architecture notes
──────────────────
Position sources:
  • T-029 AIS Listener: get_position_tracker().get_positions()
    Produces AssetPosition with AssetType.SEA, provenance REAL or REPLAYED.
  • T-030 Position Interpolator: get_current_positions()
    Produces AssetPosition with AssetType.ROAD or AIR, provenance SIMULATED.

Merge policy (get_all_positions):
  In normal operation the two caches cover disjoint asset IDs (AIS uses
  9-digit MMSIs; interpolator uses str(leg_id) integers). If an asset_id
  collides (unexpected), T-029 REAL/REPLAYED wins over T-030 SIMULATED.
  This is documented and the frontend should never observe the conflict.

Route quality from provenance:
  CALIBRATED / REAL  → "high"
  DERIVED            → "medium"
  SIMULATED          → "low"
  anything else      → "unknown"

Caching strategy (routes and ports):
  Both caches use a 60-second TTL with lazy refresh on request.
  An asyncio.Lock prevents concurrent refresh (thundering-herd protection).
  Cache invalidation: the cache expires naturally after 60 seconds.
  Future tasks (T-055 decision_executor) should call _invalidate_routes_cache()
  after any reroute to force an immediate refresh on the next request.

SSE interval:
  5 seconds is chosen for smooth map animation. T-029 AIS updates may arrive
  faster (continuous WebSocket); T-030 interpolator runs every 30 seconds.
  The SSE layer re-emits the latest known position from the in-memory cache
  every 5 seconds regardless of whether it has changed — this keeps the
  frontend rendering loop simple and handles the case where T-030 positions
  update less frequently than the SSE cadence.

SSE keepalive:
  A HEARTBEAT event (event: HEARTBEAT, data: {}) is sent every 30 seconds
  even if position data has not changed, preventing proxy idle-timeout
  disconnections.

SSE format:
  One POSITION_UPDATE event per tick containing a JSON array of all current
  positions. The frontend accumulates and replaces its position state on each
  event. This is simpler than one-event-per-vehicle and ensures atomic
  snapshot delivery.

T-030 FeedHealth synthesis:
  T-030 does not expose a FeedHealth DTO directly. The feed-health endpoint
  synthesises one: adapter_name="position_interpolator", is_healthy derived
  from get_interpolator_worker().is_running, last_success_at from the most
  recent reported_at across all cached SIMULATED positions, messages_received
  from the cache size.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Annotated, Any
from fastapi import Header, Query
from jose import JWTError
from nexafreight.auth import create_stream_ticket, decode_access_token, decode_stream_ticket
from nexafreight.config import Settings, get_settings
from nexafreight.exceptions import AuthenticationError, InvalidTokenError
from nexafreight.models.user import User

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from nexafreight.adapters.protocols import AssetPosition, FeedHealth, Provenance
from nexafreight.database import get_db_session, get_session_factory
from nexafreight.dependencies import get_current_user
from nexafreight.enums import LegStatus, TransportMode
from nexafreight.models.leg import Leg
from nexafreight.models.location import Location
from nexafreight.models.port import Port, PortDailyStat
from nexafreight.models.vessel import Vessel
from nexafreight.schemas.map import (
    FeedHealthOut,
    FeedHealthResponse,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    PositionOut,
)
from nexafreight.workers.ais_listener import get_position_tracker
from nexafreight.workers.position_interpolator import (
    get_current_positions as get_interpolated_positions,
)
from nexafreight.workers.position_interpolator import (
    get_interpolator_worker,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: SSE push interval in real seconds.
_SSE_INTERVAL_S: float = 5.0

#: SSE keepalive / heartbeat interval in seconds.
_HEARTBEAT_INTERVAL_S: float = 30.0

#: Cache TTL for routes and ports in seconds.
_CACHE_TTL_S: float = 60.0

#: Leg statuses included in the routes response.
_ACTIVE_LEG_STATUSES: tuple[str, ...] = ("PLANNED", "IN_PROGRESS")

# ---------------------------------------------------------------------------
# Cache state (module-level, lazy-refreshed)
# ---------------------------------------------------------------------------

_routes_cache: GeoJSONFeatureCollection | None = None
_routes_cache_at: float = 0.0  # monotonic time of last refresh
_routes_lock: asyncio.Lock = asyncio.Lock()

_ports_cache: GeoJSONFeatureCollection | None = None
_ports_cache_at: float = 0.0
_ports_lock: asyncio.Lock = asyncio.Lock()

_warehouses_cache: GeoJSONFeatureCollection | None = None
_warehouses_cache_at: float = 0.0
_warehouses_lock: asyncio.Lock = asyncio.Lock()


def _cache_expired(refreshed_at: float) -> bool:
    """Return True if the cache timestamp is older than the TTL."""
    return (time.monotonic() - refreshed_at) >= _CACHE_TTL_S


def _invalidate_routes_cache() -> None:
    """
    Force immediate cache expiry on the next routes request.

    Call this from decision_executor (T-055) after any reroute operation
    so the frontend receives updated geometry immediately after a decision.
    Not part of the public HTTP API.
    """
    global _routes_cache_at
    _routes_cache_at = 0.0


def _invalidate_ports_cache() -> None:
    """Force immediate ports cache expiry."""
    global _ports_cache_at
    _ports_cache_at = 0.0


def _invalidate_warehouses_cache() -> None:
    global _warehouses_cache_at
    _warehouses_cache_at = 0.0


# ---------------------------------------------------------------------------
# Position helpers
# ---------------------------------------------------------------------------


def _position_to_out(pos: AssetPosition) -> PositionOut:
    """Convert an AssetPosition DTO to a PositionOut Pydantic schema."""
    asset_type_val = (
        pos.asset_type.value if hasattr(pos.asset_type, "value") else str(pos.asset_type)
    )
    provenance_val = (
        pos.provenance.value if hasattr(pos.provenance, "value") else str(pos.provenance)
    )
    return PositionOut(
        asset_id=pos.asset_id,
        asset_type=asset_type_val,
        latitude=pos.lat,
        longitude=pos.lon,
        lat=pos.lat,
        lon=pos.lon,
        speed_knots=pos.speed_knots,
        heading_deg=pos.heading_deg,
        provenance=provenance_val,
        recorded_at=pos.reported_at,
        reported_at=pos.reported_at,
        source=pos.source,
    )


async def _get_all_positions() -> list[PositionOut]:
    """
    Merge positions from T-029 (AIS) and T-030 (interpolated) caches.

    Merge policy:
      If the same asset_id appears in both caches (unexpected in normal
      operation), the T-029 entry takes precedence because REAL/REPLAYED
      data is always more authoritative than SIMULATED data.

    Returns an empty list if both caches are empty.
    """
    merged: dict[str, AssetPosition] = {}

    # 1. T-030 interpolated positions (lower precedence — added first).
    try:
        interpolated: dict[str, AssetPosition] = get_interpolated_positions()
        for asset_id, pos in interpolated.items():
            merged[asset_id] = pos
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read T-030 position cache: %s", exc)

    # 2. T-029 AIS positions (higher precedence — overwrites interpolated).
    try:
        tracker = get_position_tracker()
        ais_positions: list[AssetPosition] = await tracker.get_positions()
        for pos in ais_positions:
            merged[pos.asset_id] = pos
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read T-029 position cache: %s", exc)

    result: list[PositionOut] = []
    for pos in merged.values():
        try:
            result.append(_position_to_out(pos))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to serialize position for asset %s: %s",
                getattr(pos, "asset_id", "unknown"),
                exc,
            )

    return result


# ---------------------------------------------------------------------------
# Route quality helper
# ---------------------------------------------------------------------------


def _route_quality_from_provenance(provenance: str) -> str:
    """
    Map a leg's provenance label to a route quality string.

    Policy:
      CALIBRATED / REAL / REPLAYED → "high"   (authoritative reference or live data)
      DERIVED                      → "medium" (computed from real data)
      SIMULATED                    → "low"    (interpolated or approximate)
      anything else                → "unknown"
    """
    match provenance.upper():
        case "CALIBRATED" | "REAL" | "REPLAYED":
            return "high"
        case "DERIVED":
            return "medium"
        case "SIMULATED":
            return "low"
        case _:
            return "unknown"


# ---------------------------------------------------------------------------
# GeoJSON helpers
# ---------------------------------------------------------------------------


def _parse_route_geometry(leg_id: int, raw: str | None) -> dict[str, Any] | None:
    """
    Parse a stored GeoJSON geometry string.

    Returns the parsed dict if valid, None if absent or unparseable.
    Logs a warning and skips the leg on failure.
    """
    if not raw:
        logger.debug("Leg %d has no route_geometry; skipping route feature.", leg_id)
        return None
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Expected JSON object")
        geo_type = parsed.get("type", "")
        if geo_type not in {
            "LineString",
            "MultiLineString",
            "Feature",
            "FeatureCollection",
        }:
            raise ValueError(f"Unexpected geometry type: {geo_type!r}")
        return parsed
    except Exception as exc:  # noqa: BLE001
        logger.warning("Leg %d has malformed route_geometry (%s); skipping.", leg_id, exc)
        return None


# ---------------------------------------------------------------------------
# Routes cache builder
# ---------------------------------------------------------------------------


async def _execute_routes_query(session: AsyncSession) -> GeoJSONFeatureCollection:
    features: list[GeoJSONFeature] = []
    statuses = [
        LegStatus.PLANNED,
        LegStatus.IN_PROGRESS,
        "PLANNED",
        "IN_PROGRESS",
    ]
    stmt = (
        select(
            Leg.id,
            Leg.shipment_id,
            Leg.sequence_number,
            Leg.transport_mode,
            Leg.status,
            Leg.provenance,
            Leg.route_geometry_json,
            Vessel.mmsi.label("vessel_mmsi"),
        )
        .outerjoin(Vessel, Leg.vessel_id == Vessel.id)
        .where(
            Leg.route_geometry_json.isnot(None),
            Leg.status.in_(statuses),
        )
    )
    rows = (await session.execute(stmt)).all()

    for row in rows:
        geometry = _parse_route_geometry(row.id, row.route_geometry_json)
        if geometry is None:
            continue

        prov_val = (
            row.provenance.value if hasattr(row.provenance, "value") else str(row.provenance or "")
        )
        quality = _route_quality_from_provenance(prov_val)
        mode_val = (
            row.transport_mode.value
            if hasattr(row.transport_mode, "value")
            else str(row.transport_mode)
        )
        status_val = row.status.value if hasattr(row.status, "value") else str(row.status)
        vessel_mmsi_val = str(row.vessel_mmsi) if row.vessel_mmsi is not None else None
        features.append(
            GeoJSONFeature(
                geometry=geometry,
                properties={
                    "leg_id": str(row.id),
                    "shipment_id": str(row.shipment_id),
                    "mode": mode_val,
                    "status": status_val,
                    "provenance": prov_val,
                    "sequence": row.sequence_number,
                    "route_quality": quality,
                    "vessel_mmsi": vessel_mmsi_val,
                },
            )
        )

    logger.debug("Built routes FeatureCollection: %d feature(s).", len(features))
    return GeoJSONFeatureCollection(features=features)


async def _build_routes_collection(
    session: AsyncSession | None = None,
) -> GeoJSONFeatureCollection:
    """
    Query all PLANNED and IN_PROGRESS legs and build a GeoJSON FeatureCollection.

    Skips legs with missing or malformed route geometry.
    Returns an empty FeatureCollection on database failure.
    """
    try:
        if session is not None:
            return await _execute_routes_query(session)
        session_factory = get_session_factory()
        async with session_factory() as s:
            return await _execute_routes_query(s)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to build routes FeatureCollection: %s", exc)
        return GeoJSONFeatureCollection(features=[])


async def _get_routes_cached(
    session: AsyncSession | None = None,
) -> GeoJSONFeatureCollection:
    """
    Return the cached routes FeatureCollection, refreshing if stale.

    Uses an asyncio.Lock to prevent concurrent database refreshes
    (thundering-herd protection when multiple clients request simultaneously).
    """
    global _routes_cache, _routes_cache_at

    if _routes_cache is not None and not _cache_expired(_routes_cache_at):
        return _routes_cache

    async with _routes_lock:
        # Re-check after acquiring lock (another coroutine may have refreshed).
        if _routes_cache is not None and not _cache_expired(_routes_cache_at):
            return _routes_cache

        _routes_cache = await _build_routes_collection(session=session)
        _routes_cache_at = time.monotonic()
        return _routes_cache


# ---------------------------------------------------------------------------
# Ports cache builder
# ---------------------------------------------------------------------------


async def _execute_ports_query(session: AsyncSession) -> GeoJSONFeatureCollection:
    features: list[GeoJSONFeature] = []
    port_stmt = select(
        Port.id,
        Location.id.label("location_id"),
        Location.locode,
        Location.latitude,
        Location.longitude,
        Location.name.label("location_name"),
    ).join(
        Location,
        Port.location_id == Location.id,
        isouter=True,
    )
    port_rows = (await session.execute(port_stmt)).all()

    for row in port_rows:
        if row.latitude is None or row.longitude is None:
            logger.debug(
                "Port %d (%s) has no linked Location; skipping.",
                row.id,
                row.locode,
            )
            continue

        # Latest congestion stat for this port.
        stat_stmt = (
            select(
                PortDailyStat.congestion_index,
            )
            .where(PortDailyStat.port_id == row.id, PortDailyStat.source == 'CALIBRATED')
            .order_by(PortDailyStat.stat_date.desc())
            .limit(1)
        )
        stat_row = (await session.execute(stat_stmt)).one_or_none()
        if not stat_row:
            stat_stmt = (
                select(
                    PortDailyStat.congestion_index,
                )
                .where(PortDailyStat.port_id == row.id)
                .order_by(PortDailyStat.stat_date.desc())
                .limit(1)
            )
            stat_row = (await session.execute(stat_stmt)).one_or_none()
        congestion_index = stat_row.congestion_index if stat_row else None
        stat_provenance = "DERIVED"

        features.append(
            GeoJSONFeature(
                geometry={
                    "type": "Point",
                    "coordinates": [float(row.longitude), float(row.latitude)],
                },
                properties={
                    "port_id": str(row.id),
                    "location_id": str(row.location_id) if row.location_id else None,
                    "name": row.location_name,
                    "locode": row.locode,
                    "congestion_index": congestion_index,
                    "provenance": stat_provenance,
                },
            )
        )

    logger.debug("Built ports FeatureCollection: %d feature(s).", len(features))
    return GeoJSONFeatureCollection(features=features)


async def _build_ports_collection(
    session: AsyncSession | None = None,
) -> GeoJSONFeatureCollection:
    """
    Query all ports with their linked locations and most recent congestion data.

    Port filter: all ports (no active-shipment filter).
    Rationale: operators always want to see all major ports on the map,
    regardless of whether a NexaFreight shipment is currently heading there.

    For each port:
    - Loads the linked Location for coordinates.
    - Loads the most recent PortDailyStat (if any) for congestion_index.
    - Skips ports with no linked Location (logs debug).

    Returns an empty FeatureCollection on database failure.
    """
    try:
        if session is not None:
            return await _execute_ports_query(session)
        session_factory = get_session_factory()
        async with session_factory() as s:
            return await _execute_ports_query(s)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to build ports FeatureCollection: %s", exc)
        return GeoJSONFeatureCollection(features=[])


async def _get_ports_cached(
    session: AsyncSession | None = None,
) -> GeoJSONFeatureCollection:
    """Return the cached ports FeatureCollection, refreshing if stale."""
    global _ports_cache, _ports_cache_at

    if _ports_cache is not None and not _cache_expired(_ports_cache_at):
        return _ports_cache

    async with _ports_lock:
        if _ports_cache is not None and not _cache_expired(_ports_cache_at):
            return _ports_cache

        _ports_cache = await _build_ports_collection(session=session)
        _ports_cache_at = time.monotonic()
        return _ports_cache


# ---------------------------------------------------------------------------
# Warehouses cache builder
# ---------------------------------------------------------------------------


async def _execute_warehouses_query(session: AsyncSession) -> GeoJSONFeatureCollection:
    features: list[GeoJSONFeature] = []
    # Identify ports to avoid duplicating them in the warehouse layer
    port_loc_ids = (await session.execute(select(Port.location_id).where(Port.location_id.is_not(None)))).scalars().all()
    port_loc_set = set(port_loc_ids)

    stmt = (
        select(Location.id, Location.latitude, Location.longitude, Location.name, Location.locode, Leg.transport_mode)
        .join(Leg, (Leg.origin_id == Location.id) | (Leg.destination_id == Location.id))
        .where(
            (Leg.transport_mode == "ROAD")
            | (Leg.transport_mode == "RAIL")
            | (Leg.transport_mode == TransportMode.ROAD)
            | (Leg.transport_mode == TransportMode.RAIL)
        )
        .distinct()
    )
    rows = (await session.execute(stmt)).all()
    seen_ids = set()

    for row in rows:
        if row.latitude is None or row.longitude is None:
            continue
        if row.id in port_loc_set or row.id in seen_ids:
            continue
        seen_ids.add(row.id)

        loc_name = row.name or row.locode or "Logistics Node"
        mode_val = getattr(row.transport_mode, "value", str(row.transport_mode))

        if "ICD" in loc_name or "Rail" in loc_name or mode_val == "RAIL":
            facility_type = "INLAND_CONTAINER_DEPOT"
            fac_desc = "Intermodal Rail Terminal / ICD"
        elif "Airport" in loc_name:
            facility_type = "AIR_FREIGHT_STAGING"
            fac_desc = "Air Cargo Overland Drayage Station"
        else:
            facility_type = "DISTRIBUTION_CENTER"
            fac_desc = "Regional Freight Hub & Cross-Dock"

        features.append(
            GeoJSONFeature(
                geometry={
                    "type": "Point",
                    "coordinates": [float(row.longitude), float(row.latitude)],
                },
                properties={
                    "warehouse_id": str(row.id),
                    "name": loc_name,
                    "locode": row.locode or "",
                    "facility_type": facility_type,
                    "type_description": fac_desc,
                    "transport_mode": mode_val,
                    "status": "OPERATIONAL",
                },
            )
        )
    return GeoJSONFeatureCollection(features=features)


async def _build_warehouses_collection(
    session: AsyncSession | None = None,
) -> GeoJSONFeatureCollection:
    try:
        if session is not None:
            return await _execute_warehouses_query(session)
        session_factory = get_session_factory()
        async with session_factory() as s:
            return await _execute_warehouses_query(s)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to build warehouses FeatureCollection: %s", exc)
        return GeoJSONFeatureCollection(features=[])


async def _get_warehouses_cached(
    session: AsyncSession | None = None,
) -> GeoJSONFeatureCollection:
    global _warehouses_cache, _warehouses_cache_at

    if _warehouses_cache is not None and not _cache_expired(_warehouses_cache_at):
        return _warehouses_cache

    async with _warehouses_lock:
        if _warehouses_cache is not None and not _cache_expired(_warehouses_cache_at):
            return _warehouses_cache

        _warehouses_cache = await _build_warehouses_collection(session=session)
        _warehouses_cache_at = time.monotonic()
        return _warehouses_cache


# ---------------------------------------------------------------------------
# SSE generator
# ---------------------------------------------------------------------------


async def _sse_generator(
    interval_s: float = _SSE_INTERVAL_S,
    heartbeat_s: float = _HEARTBEAT_INTERVAL_S,
    max_lifetime_s: float = 1800.0,
) -> AsyncGenerator[str, None]:
    """
    Async generator that produces SSE-formatted strings for the position stream.

    SSE format produced:
        event: POSITION_UPDATE
        data: [{"asset_id": ..., ...}, ...]

        (blank line terminates event)

    Keepalive:
        event: HEARTBEAT
        data: {}

        (sent every heartbeat_s seconds even when positions unchanged)

    One POSITION_UPDATE event per tick contains ALL current positions as a
    JSON array. This gives the frontend an atomic snapshot and simplifies
    its rendering logic (replace, don't merge).

    Client disconnect:
        asyncio.CancelledError is raised by FastAPI when the client
        disconnects. We let it propagate cleanly — FastAPI/Starlette
        handles the connection close. No error is logged.

    Empty cache:
        Send an empty-array POSITION_UPDATE: `data: []`. Do not close.
    """
    elapsed_since_heartbeat: float = 0.0
    start_time: float = asyncio.get_event_loop().time()

    while True:
        if asyncio.get_event_loop().time() - start_time >= max_lifetime_s:
            logger.info("SSE position stream reached max lifetime (%s s); closing connection", max_lifetime_s)
            return
        try:
            positions = await _get_all_positions()
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("SSE: failed to gather positions: %s", exc)
            positions = []

        # Serialize positions to a JSON array.
        try:
            payload = json.dumps(
                [p.model_dump(mode="json") for p in positions],
                default=str,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("SSE: failed to serialize positions: %s", exc)
            payload = "[]"

        yield f"event: POSITION_UPDATE\ndata: {payload}\n\n"

        elapsed_since_heartbeat += interval_s
        if elapsed_since_heartbeat >= heartbeat_s:
            yield "event: HEARTBEAT\ndata: {}\n\n"
            elapsed_since_heartbeat = 0.0

        try:
            if interval_s > 0:
                await asyncio.sleep(interval_s)
            else:
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            return


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------



async def _verify_stream_auth(
    authorization: Annotated[str | None, Header()] = None,
    ticket: Annotated[str | None, Query()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    if ticket:
        try:
            decode_stream_ticket(ticket, settings)
            return
        except (JWTError, ValueError):
            raise AuthenticationError("Invalid or expired stream ticket")
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            try:
                decode_access_token(parts[1], settings)
                return
            except (JWTError, ValueError):
                raise InvalidTokenError()
    raise AuthenticationError("Authentication required: provide ?ticket= or Authorization header")


@router.post(
    "/positions/stream-ticket",
    summary="Issue short-lived SSE stream ticket",
    response_description="A short-lived ticket valid for 60 seconds",
)
async def create_position_stream_ticket(
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Generate a 60-second ticket scoped strictly to position streaming."""
    ticket = create_stream_ticket(current_user.id, settings, expires_in_seconds=60)
    return {"ticket": ticket, "expires_in": 60}


@router.get(
    "/positions/stream",
    summary="Live SSE position stream",
    response_description="Server-Sent Events stream of POSITION_UPDATE events",
    dependencies=[Depends(_verify_stream_auth)],
)
async def stream_positions() -> StreamingResponse:
    """
    SSE stream pushing all current asset positions every 5 seconds.

    Connect via:
        const es = new EventSource('/api/map/positions/stream');
        es.addEventListener('POSITION_UPDATE', (e) => {
            const positions = JSON.parse(e.data);
        });

    The stream is infinite until the client disconnects.
    """
    return StreamingResponse(
        _sse_generator(max_lifetime_s=1800.0),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering for SSE
        },
    )


@router.get(
    "/positions/snapshot",
    response_model=list[PositionOut],
    summary="One-time position snapshot",
)
async def snapshot_positions(
    _current_user: Any = Depends(get_current_user),
) -> list[PositionOut]:
    """
    Return all current asset positions as a JSON array.

    Returns an empty array [] if no positions are cached yet.
    """
    return await _get_all_positions()


@router.get(
    "/routes",
    response_model=GeoJSONFeatureCollection,
    summary="Active shipment route geometries",
)
async def get_routes(
    _current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> GeoJSONFeatureCollection:
    """
    Return all PLANNED and IN_PROGRESS leg geometries as a GeoJSON FeatureCollection.

    Response is cached for 60 seconds to avoid repeated database queries.
    Returns an empty FeatureCollection if no active legs exist.
    """
    return await _get_routes_cached(session=db)


@router.get(
    "/ports",
    response_model=GeoJSONFeatureCollection,
    summary="Port locations and congestion data",
)
async def get_ports(
    _current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> GeoJSONFeatureCollection:
    """
    Return all port locations with current congestion indices as a GeoJSON FeatureCollection.

    Response is cached for 60 seconds.
    Returns an empty FeatureCollection if no ports exist.
    """
    return await _get_ports_cached(session=db)


@router.get(
    "/warehouses",
    summary="Get warehouse locations",
    response_description="GeoJSON FeatureCollection of warehouse origins",
    response_model=GeoJSONFeatureCollection,
)
async def get_warehouses(
    session: AsyncSession = Depends(get_db_session),
    _current_user: Any = Depends(get_current_user),
) -> GeoJSONFeatureCollection:
    """
    Return all warehouse locations as a GeoJSON FeatureCollection.
    Warehouses are defined as the origin locations of ROAD legs.
    """
    return await _get_warehouses_cached(session=session)


@router.get(
    "/feed-health",
    response_model=FeedHealthResponse,
    summary="Position feed adapter health statuses",
)
async def get_feed_health(
    _current_user: Any = Depends(get_current_user),
) -> FeedHealthResponse:
    """
    Return health status for all active position feed adapters.

    Always returns HTTP 200, even when adapters are unhealthy.
    Adapters included:
      - AIS adapter (T-029): live or replay AIS positions.
      - Position interpolator (T-030): simulated truck/flight positions.
    """
    adapters: list[FeedHealthOut] = []

    # ── T-029 AIS health ───────────────────────────────────────────────────
    try:
        tracker = get_position_tracker()
        ais_health: FeedHealth = await tracker.get_feed_health()
        prov_val = (
            ais_health.provenance.value
            if hasattr(ais_health.provenance, "value")
            else str(ais_health.provenance)
        )
        adapters.append(
            FeedHealthOut(
                adapter_name=ais_health.adapter_name,
                is_healthy=ais_health.is_healthy,
                last_success_at=ais_health.last_success_at,
                messages_received=ais_health.messages_received,
                provenance=prov_val,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to retrieve AIS feed health: %s", exc)
        adapters.append(
            FeedHealthOut(
                adapter_name="ais",
                is_healthy=False,
                last_success_at=None,
                messages_received=0,
                provenance=Provenance.MOCK.value,
            )
        )

    # ── T-030 interpolator health (synthesised) ────────────────────────────
    try:
        worker = get_interpolator_worker()
        interp_cache = get_interpolated_positions()

        is_healthy = worker.is_running
        last_success: datetime | None = None
        if interp_cache:
            last_success = max(
                (p.reported_at for p in interp_cache.values()),
                default=None,
            )

        adapters.append(
            FeedHealthOut(
                adapter_name="position_interpolator",
                is_healthy=is_healthy,
                last_success_at=last_success,
                messages_received=len(interp_cache),
                provenance=Provenance.SIMULATED.value,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to retrieve interpolator feed health: %s", exc)
        adapters.append(
            FeedHealthOut(
                adapter_name="position_interpolator",
                is_healthy=False,
                last_success_at=None,
                messages_received=0,
                provenance=Provenance.SIMULATED.value,
            )
        )

    return FeedHealthResponse(adapters=adapters)
