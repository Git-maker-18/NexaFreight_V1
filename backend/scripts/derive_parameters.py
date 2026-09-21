import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.config import get_settings
from nexafreight.database import get_session_factory
from nexafreight.models.parameter import ParameterEmpirical, ParameterPolicy
from nexafreight.adapters.routing.road_route import RoadRouter
from nexafreight.adapters.routing._geometry import haversine_km

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STANDARD_PAIRS = [
    # Germany
    {"country": "DE", "o": (50.1109, 8.6821), "d": (48.1351, 11.5820)},  # Frankfurt -> Munich
    {"country": "DE", "o": (52.5200, 13.4050), "d": (53.5511, 9.9937)},  # Berlin -> Hamburg
    
    # US
    {"country": "US", "o": (34.0522, -118.2437), "d": (47.6062, -122.3321)},  # LA -> Seattle
    {"country": "US", "o": (40.7128, -74.0060), "d": (41.8781, -87.6298)},  # NY -> Chicago
]

# 0.75h halt allowance per 4.5h driving
def get_halt_allowance(engine_duration_h: float) -> float:
    return (engine_duration_h / 4.5) * 0.75

async def derive_road_parameters(session: AsyncSession):
    settings = get_settings()
    api_key = settings.ors_api_key.get_secret_value() if settings.ors_api_key else None
    road_router = RoadRouter(api_key=api_key)

    country_stats = {}
    
    # Defaults across everything if ORS fails
    global_circuity = []
    global_speeds = []

    for pair in STANDARD_PAIRS:
        country = pair["country"]
        olat, olon = pair["o"]
        dlat, dlon = pair["d"]
        
        try:
            res = road_router.compute((olat, olon), (dlat, dlon))
            
            # If ORS failed and we got fallback, skip it for actual derivation
            if res.source == "GREAT_CIRCLE_FALLBACK":
                logger.warning(f"ORS failed for {country}, skipping derivation")
                continue

            dist_km = res.distance_km
            duration_h = res.duration_s / 3600.0
            direct_km = haversine_km(olat, olon, dlat, dlon)
            
            circuity = dist_km / direct_km if direct_km > 0 else 1.0
            halt_allowance = get_halt_allowance(duration_h)
            effective_speed = dist_km / (duration_h + halt_allowance)
            
            if country not in country_stats:
                country_stats[country] = {"speeds": [], "circuity": []}
                
            country_stats[country]["speeds"].append(effective_speed)
            country_stats[country]["circuity"].append(circuity)
            
            global_circuity.append(circuity)
            global_speeds.append(effective_speed)
            
        except Exception as e:
            logger.error(f"Error computing route for {country}: {e}")
            
    # Calculate averages and upsert
    now = datetime.now(UTC)
    
    avg_speed = sum(global_speeds)/len(global_speeds) if global_speeds else 65.0
    avg_circuity = sum(global_circuity)/len(global_circuity) if global_circuity else 1.35
    
    empiricals = [
        ParameterEmpirical(
            key="road.speed.default",
            value=str(avg_speed),
            unit="km/h",
            source="ORS_DERIVATION",
            as_of=now,
            derivation_method="avg(route_km / (duration + halt))",
            sample_count=len(global_speeds),
        ),
        ParameterEmpirical(
            key="road.circuity.default",
            value=str(avg_circuity),
            unit="multiplier",
            source="ORS_DERIVATION",
            as_of=now,
            derivation_method="avg(route_km / haversine_km)",
            sample_count=len(global_circuity),
        )
    ]
    
    for country, stats in country_stats.items():
        cs = sum(stats["speeds"]) / len(stats["speeds"])
        cc = sum(stats["circuity"]) / len(stats["circuity"])
        empiricals.append(
            ParameterEmpirical(
                key=f"road.speed.{country}",
                value=str(cs),
                unit="km/h",
                source="ORS_DERIVATION",
                as_of=now,
                derivation_method="avg(route_km / (duration + halt))",
                sample_count=len(stats["speeds"]),
            )
        )
        
    for emp in empiricals:
        await session.merge(emp)

async def upsert_policy_parameters(session: AsyncSession):
    now = datetime.now(UTC)
    policies = [
        ParameterPolicy(
            key="disruption.congestion.ratio_p90",
            value="2.5",
            unit="ratio",
            owner="disruption_detector",
            rationale="Trigger disruption above p90",
            updated_at=now,
        ),
        ParameterPolicy(
            key="sla.cushion_buffer_hours",
            value="24.0",
            unit="hours",
            owner="sla_checker",
            rationale="24h buffer for early warning",
            updated_at=now,
        ),
        ParameterPolicy(
            key="air.handling_hours",
            value="12.0",
            unit="hours",
            owner="reroute_engine",
            rationale="Average handling time for air freight",
            updated_at=now,
        ),
        ParameterPolicy(
            key="air.taxi_hours",
            value="0.3",
            unit="hours",
            owner="air_route",
            rationale="Standard taxi time",
            updated_at=now,
        ),
        ParameterPolicy(
            key="air.climb_descent_hours",
            value="0.4",
            unit="hours",
            owner="air_route",
            rationale="Standard climb/descent time",
            updated_at=now,
        ),
        ParameterPolicy(
            key="air.cruise_speed_kmh",
            value="860.0",
            unit="km/h",
            owner="air_route",
            rationale="Standard cruise speed",
            updated_at=now,
        ),
        ParameterPolicy(
            key="sea.speed.feeder",
            value="15.0",
            unit="knots",
            owner="sea_route",
            rationale="Nominal feeder speed",
            updated_at=now,
        ),
        ParameterPolicy(
            key="sea.speed.panamax",
            value="19.0",
            unit="knots",
            owner="sea_route",
            rationale="Nominal panamax speed",
            updated_at=now,
        ),
        ParameterPolicy(
            key="sea.speed.neo_panamax",
            value="21.0",
            unit="knots",
            owner="sea_route",
            rationale="Nominal neo-panamax speed",
            updated_at=now,
        ),
        ParameterPolicy(
            key="sea.speed.slow_steamed",
            value="17.0",
            unit="knots",
            owner="sea_route",
            rationale="Nominal slow steamed speed",
            updated_at=now,
        ),
        ParameterPolicy(
            key="sea.canal_adder.suez_h",
            value="14.0",
            unit="hours",
            owner="sea_route",
            rationale="Suez canal transit allowance",
            updated_at=now,
        ),
        ParameterPolicy(
            key="reroute.generic_divert.mode",
            value="ROAD",
            unit="mode",
            owner="reroute_engine",
            rationale="Default mode for generic divert",
            updated_at=now,
        ),
        ParameterPolicy(
            key="reroute.generic_divert.time_delta_hours",
            value="36.0",
            unit="hours",
            owner="reroute_engine",
            rationale="Fallback divert time delta",
            updated_at=now,
        ),
        ParameterPolicy(
            key="reroute.generic_divert.cost_delta_factor",
            value="1.25",
            unit="factor",
            owner="reroute_engine",
            rationale="Fallback divert cost delta",
            updated_at=now,
        ),
        ParameterPolicy(
            key="reroute.generic_divert.co2_delta_factor",
            value="1.10",
            unit="factor",
            owner="reroute_engine",
            rationale="Fallback divert co2 delta",
            updated_at=now,
        )
    ]
    for p in policies:
        await session.merge(p)

    # Some port dwells for empirical
    port_dwells = [
        ParameterEmpirical(key="port.dwell.p50.PORT-1", value="24.0", unit="hours", source="WB CPPI", as_of=now, derivation_method="baselines", sample_count=1),
        ParameterEmpirical(key="port.dwell.p90_ext.PORT-1", value="48.0", unit="hours", source="WB CPPI", as_of=now, derivation_method="baselines", sample_count=1),
    ]
    for p in port_dwells:
        await session.merge(p)


async def main():
    session_factory = get_session_factory()
    async with session_factory() as session:
        logger.info("Deriving road parameters...")
        await derive_road_parameters(session)
        logger.info("Upserting policy parameters...")
        await upsert_policy_parameters(session)
        await session.commit()
    logger.info("Done.")

if __name__ == "__main__":
    asyncio.run(main())
