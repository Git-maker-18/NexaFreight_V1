"""Unit tests for independent ML model loading and /health reporting (Items 6, 22, 25)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
from httpx import AsyncClient

from nexafreight.ml.registry import ModelRegistry
from nexafreight.ml.constants import (
    DELAY_MODEL_DIR,
    DEMAND_MODEL_DIR,
    ETA_MODEL_DIR,
)


def test_independent_model_loading_when_delay_missing():
    """ETA and demand models must load and work even if delay model artifact is missing."""
    with tempfile.TemporaryDirectory() as empty_dir:
        # Initialize registry with an empty delay_dir
        registry = ModelRegistry(
            delay_dir=empty_dir,
            eta_dir=ETA_MODEL_DIR,
            demand_dir=DEMAND_MODEL_DIR,
        )

        assert registry.delay_loaded is False
        assert registry.eta_loaded is True
        assert registry.demand_loaded is True
        assert registry.is_loaded is True

        # ETA model works
        eta_model = registry.get_eta_model()
        assert eta_model is not None
        assert registry.eta_model_version == "lane-quantiles-v1"

        # Demand model works
        demand_model = registry.get_demand_model()
        assert demand_model is not None

        # Getting delay model raises RuntimeError
        with pytest.raises(RuntimeError, match="Delay classifier model not loaded"):
            registry.get_delay_model()


def test_all_models_loaded_normally():
    """When all models are present, all 3 are marked loaded."""
    registry = ModelRegistry()
    assert registry.delay_loaded is True
    assert registry.eta_loaded is True
    assert registry.demand_loaded is True
    assert registry.is_loaded is True
    assert registry.eta_model_version == "lane-quantiles-v1"


@pytest.mark.asyncio
async def test_health_reports_ml_models_status(client: AsyncClient):
    """GET /health reports ml_models_loaded and per-model dict."""
    resp = await client.get("/health")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "ml_models_loaded" in data
    assert "models" in data
    assert isinstance(data["models"], dict)
    assert "delay" in data["models"]
    assert "eta" in data["models"]
    assert "demand" in data["models"]

