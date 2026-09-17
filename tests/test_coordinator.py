"""Unit tests for the AIL energy coordinator statistics logic."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.ail.api_client import (
    AILEnergyClient,
    ConsumptionRecord,
    ConsumptionResponse,
)
from custom_components.ail.coordinator import (
    ConsumptionData,
    EnergyDataUpdateCoordinator,
)


def _record(
    day: float, night: float, from_: str, readings_count: int | None = 1
) -> ConsumptionRecord:
    """Build a ConsumptionRecord using the API's alias field names (as raw JSON does)."""
    ts = datetime.fromisoformat(from_)
    return ConsumptionRecord(
        day=day,
        night=night,
        **{
            "from": ts,
            "to": ts + timedelta(minutes=15),
            "isPending": False,
            "readingsCount": readings_count,
        },
    )


class TestConsumptionData:
    def test_from_api_response_skips_records_without_readings(self):
        """Records with readings_count None must be dropped."""
        response = ConsumptionResponse(
            response=[
                _record(1.0, 0.5, "2026-09-17T08:00:00", readings_count=1),
                _record(2.0, 1.0, "2026-09-17T08:15:00", readings_count=None),
                _record(3.0, 1.5, "2026-09-17T08:30:00", readings_count=1),
            ]
        )
        data = ConsumptionData.from_api_response(response)
        assert len(data) == 2
        assert [d.day for d in data] == [1.0, 3.0]

    def test_from_api_response_empty_when_all_readings_missing(self):
        """A response with no usable readings yields an empty list (the crash path)."""
        response = ConsumptionResponse(
            response=[
                _record(1.0, 0.5, "2026-09-17T08:00:00", readings_count=None),
                _record(2.0, 1.0, "2026-09-17T08:15:00", readings_count=None),
            ]
        )
        assert ConsumptionData.from_api_response(response) == []


class TestEnergyDataUpdateCoordinator:
    def _coordinator(self, client):
        hass = MagicMock()
        entry = MagicMock()
        return EnergyDataUpdateCoordinator(hass, entry, client)

    async def test_update_returns_empty_consumption_when_api_has_no_data(self):
        """No-data from the API must return a zeroed ConsumptionData, not crash."""
        client = MagicMock(spec=AILEnergyClient)
        client.login = AsyncMock(return_value=True)
        client.get_consumption_data = AsyncMock(
            return_value=ConsumptionResponse(response=[])
        )
        coordinator = self._coordinator(client)

        data = await coordinator._async_update_data()

        assert data.day == 0.0
        assert data.night == 0.0
        assert coordinator.api_client.login.await_count == 1

    async def test_update_bubbles_auth_failure(self):
        client = MagicMock(spec=AILEnergyClient)
        client.login = AsyncMock(return_value=False)
        coordinator = self._coordinator(client)

        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

    async def test_update_returns_last_consumption_record(self):
        """A normal response returns the final record and persists statistics."""
        client = MagicMock(spec=AILEnergyClient)
        client.login = AsyncMock(return_value=True)
        client.get_consumption_data = AsyncMock(
            return_value=ConsumptionResponse(
                response=[
                    _record(1.0, 0.5, "2026-09-17T08:00:00", readings_count=1),
                    _record(2.0, 1.0, "2026-09-17T08:15:00", readings_count=1),
                ]
            )
        )
        coordinator = self._coordinator(client)
        coordinator._insert_statistics = AsyncMock()

        data = await coordinator._async_update_data()

        assert data.day == 2.0
        coordinator._insert_statistics.assert_awaited_once()