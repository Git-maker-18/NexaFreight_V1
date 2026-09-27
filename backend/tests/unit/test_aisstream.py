"""Tests for the AISStream adapter."""

import asyncio
import json
from datetime import UTC, datetime

import pytest

from nexafreight.adapters.feed.aisstream import (
    AISStreamAdapter,
    _build_subscription_payload,
    _parse_position_report,
)


def test_build_subscription_payload_default():
    """1. default mode: _build_subscription_payload output contains FiltersShipMMSI and does NOT contain 'BoundingBox'"""
    mmsis = frozenset(["123456789", "987654321"])
    payload = _build_subscription_payload("test-key", mmsis, None)
    
    parsed = json.loads(payload)
    assert "APIKey" in parsed
    assert parsed["APIKey"] == "test-key"
    assert "FiltersShipMMSI" in parsed
    assert sorted(parsed["FiltersShipMMSI"]) == ["123456789", "987654321"]
    assert "BoundingBox" not in parsed


def test_build_subscription_payload_bbox():
    """2. bbox mode: singular key 'BoundingBox' present with exact nesting and NO FiltersShipMMSI"""
    mmsis = frozenset(["123456789"])
    bbox_json = "[[[[-10.0, -10.0], [10.0, 10.0]]]]"
    payload = _build_subscription_payload("test-key", mmsis, bbox_json)
    
    parsed = json.loads(payload)
    assert "APIKey" in parsed
    assert parsed["APIKey"] == "test-key"
    assert "BoundingBox" in parsed
    assert parsed["BoundingBox"] == [[[[-10.0, -10.0], [10.0, 10.0]]]]
    assert "FiltersShipMMSI" not in parsed


def test_parse_position_report_permissive_parser():
    """3. bbox-mode parser accepts an arbitrary valid 9-digit MMSI not in any configured list"""
    now = datetime.now(UTC)
    message = {
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": "111222333"},
        "Message": {
            "PositionReport": {
                "Latitude": 12.34,
                "Longitude": 56.78,
                "Sog": 10.5,
                "TrueHeading": 90,
            }
        }
    }
    
    configured_mmsis = frozenset(["999999999"])
    
    # In default mode (bbox_active=False), it should return None because 111222333 is not in configured list
    assert _parse_position_report(message, now, configured_mmsis, bbox_active=False) is None
    
    # In bbox mode (bbox_active=True), it should accept it
    position = _parse_position_report(message, now, configured_mmsis, bbox_active=True)
    assert position is not None
    assert position.asset_id == "111222333"


@pytest.mark.asyncio
async def test_cache_cap_eviction():
    """4. cache cap: inserting cap+1 distinct MMSIs evicts the oldest"""
    # Create adapter with a small arbitrary MMSI list (adapter behavior doesn't care for cache insertion limit logic)
    adapter = AISStreamAdapter(["111111111"], api_key="test-key")
    
    now = datetime.now(UTC)
    
    # The cache cap is hardcoded to 5000 in _handle_raw_message
    cap = 5000
    
    adapter._bbox_json = "[[[[-10.0, -10.0], [10.0, 10.0]]]]"
    
    # Insert cap + 1
    for i in range(cap + 1):
        mmsi = f"{i:09d}"
        msg = {
            "MessageType": "PositionReport",
            "MetaData": {"MMSI": mmsi},
            "Message": {
                "PositionReport": {
                    "Latitude": 10.0,
                    "Longitude": 20.0,
                }
            }
        }
        await adapter._handle_raw_message(json.dumps(msg))
        
    async with adapter._lock:
        assert len(adapter._state.cache) == cap
        
        # The oldest MMSI "000000000" should be evicted
        assert "000000000" not in adapter._state.cache
        
        # The newest MMSI "000005000" should be present
        assert f"{cap:09d}" in adapter._state.cache
