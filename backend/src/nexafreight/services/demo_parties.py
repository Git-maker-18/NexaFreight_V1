"""Demo-world party logic (Task 18, P1). Importable core; scripts 20/21
delegate to this module.

Nine fictional-but-realistic actors tell the India export story:
3 Indian shippers -> 3 foreign consignees, moved by 3 Indian carriers.
Seeding is idempotent by unique name; assignment is deterministic under
the dripper's seeded RNG so every world rebuild tells the same story.
"""

from __future__ import annotations

import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexafreight.models.party import Party

PARTY_SPECS: list[dict[str, str]] = [
    {"name": "Deccan Textiles Ltd", "role": "SHIPPER", "city": "Hyderabad", "country_code": "IN"},
    {"name": "Kaveri Agro Exports", "role": "SHIPPER", "city": "Chennai", "country_code": "IN"},
    {"name": "Ganga Pharma Labs", "role": "SHIPPER", "city": "Ahmedabad", "country_code": "IN"},
    {"name": "Meridian Retail GmbH", "role": "CONSIGNEE", "city": "Hamburg", "country_code": "DE"},
    {"name": "Atlas Home NL BV", "role": "CONSIGNEE", "city": "Rotterdam", "country_code": "NL"},
    {"name": "Nordic Fresh AB", "role": "CONSIGNEE", "city": "Gothenburg", "country_code": "SE"},
    {"name": "Monsoon Maritime Lines", "role": "CARRIER", "city": "Mumbai", "country_code": "IN"},
    {"name": "Deccan Carriers Roadlines", "role": "CARRIER", "city": "Hyderabad", "country_code": "IN"},
    {"name": "Garuda Air Cargo", "role": "CARRIER", "city": "Bengaluru", "country_code": "IN"},
]


async def seed_parties(session: AsyncSession) -> int:
    """Insert missing parties; returns how many were created (idempotent)."""
    existing = {name for (name,) in (await session.execute(select(Party.name))).all()}
    created = 0
    for spec in PARTY_SPECS:
        if spec["name"] in existing:
            continue
        session.add(Party(**spec))
        created += 1
    await session.commit()
    return created


async def load_party_pools(session: AsyncSession) -> dict[str, list[int]]:
    """Role -> list[party_id] for the dripper's deterministic assignment."""
    rows = (await session.execute(select(Party))).scalars().all()
    pools: dict[str, list[int]] = {"SHIPPER": [], "CONSIGNEE": [], "CARRIER": []}
    for party in rows:
        role = str(party.role).split(".")[-1]
        if role in pools:
            pools[role].append(party.id)
    return pools


def assign_parties(
    order,
    pools: dict[str, list[int]],
    rng: random.Random,
) -> None:
    """Deterministically stamp shipper/consignee/carrier onto an order.

    Uses ``rng`` (the dripper's seeded Random) so the same world seed
    reproduces the same party assignments. Empty pools leave None.
    """
    order.shipper_id = rng.choice(pools["SHIPPER"]) if pools.get("SHIPPER") else None
    order.consignee_id = rng.choice(pools["CONSIGNEE"]) if pools.get("CONSIGNEE") else None
    order.carrier_id = rng.choice(pools["CARRIER"]) if pools.get("CARRIER") else None
