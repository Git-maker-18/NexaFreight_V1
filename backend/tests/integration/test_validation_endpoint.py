"""Task 17: the public validation-matrix endpoint serves the live matrix,
consistent with the CI gate implementation.

Uses the conftest ``client`` fixture (test settings + DB override) so the
suite passes on a pristine clone — the app's lifespan parameter refresh
must not depend on a developer's local ``data/nexafreight.db``.
"""

from __future__ import annotations


async def test_validation_matrix_endpoint_serves_live_checks(client) -> None:
    resp = await client.get("/api/health/validation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["all_ok"] is True
    assert body["pass_count"] == body["total_count"]
    assert body["pass_count"] >= 37  # 30 static + 7 artifact (artifacts committed)
    names = {row["name"] for row in body["static"] + body["artifact"]}
    # spot-check the anchors that matter on screen
    assert "sea CO2 EF g/tkm" in names
    assert "dwell p50 INJNP" in names
    assert "carbon price $/kg" in names
    assert "cape ratio INJNP->NLRTM" in names


async def test_validation_matrix_matches_cli_implementation(client) -> None:
    """API and CI gate share one implementation — counts must agree."""
    from nexafreight.services.validation_matrix import build_matrix

    served = (await client.get("/api/health/validation")).json()
    direct = build_matrix()
    assert served["total_count"] == direct["total_count"]
    assert served["pass_count"] == direct["pass_count"]
