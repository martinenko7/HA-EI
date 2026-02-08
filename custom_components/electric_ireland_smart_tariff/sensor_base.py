import asyncio
import itertools
import logging
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, UTC
from typing import List

from homeassistant.components.recorder.models import (
    StatisticData, 
    StatisticMetaData, 
    StatisticMeanType
)

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass

from homeassistant_historical_sensor import (
    HistoricalSensor,
    HistoricalState,
    PollUpdateMixin,
)

from .api import ElectricIrelandScraper
from .const import DOMAIN, LOOKUP_DAYS, ONGOING_LOOKUP_DAYS, PARALLEL_DAYS, MIN_UPDATE_INTERVAL_HOURS


LOGGER = logging.getLogger(DOMAIN)


class Sensor(PollUpdateMixin, HistoricalSensor, SensorEntity):

    def __init__(self, device_id: str, ei_api: ElectricIrelandScraper, name: str, metric: str, measurement_unit: str,
                 device_class: SensorDeviceClass, tariff_type: str = None):
        super().__init__()

        self._attr_has_entity_name = True
        self._attr_name = f"Electric Ireland {name}"

        tariff_suffix = f"_{tariff_type}" if tariff_type else ""
        self._attr_unique_id = f"{DOMAIN}_{metric}{tariff_suffix}_{device_id}"
        self._attr_entity_id = f"{DOMAIN}_{metric}{tariff_suffix}_{device_id}"

        self._attr_entity_registry_enabled_default = True
        self._attr_state = None
        self._attr_native_unit_of_measurement = measurement_unit
        self._attr_device_class = device_class
        
        self._api: ElectricIrelandScraper = ei_api

        self._metric = metric
        self._tariff_type = tariff_type
        self._last_data_timestamp = None
        self._last_update_time = None
        self._initial_fetch_done = False

    def _friendly_name_internal(self):
        """Backwards compatibility patch for homeassistant-historical-sensor."""
        # This fixes the crash in HA 2026.2 where the library tries to call 
        # a private method that was removed from Home Assistant Core.
        return self.name

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

    async def async_update_historical(self):
        now = datetime.now(UTC)
        
        if self._last_update_time and self._initial_fetch_done:
            hours_since_update = (now - self._last_update_time).total_seconds() / 3600
            if hours_since_update < MIN_UPDATE_INTERVAL_HOURS:
                return

        loop = asyncio.get_running_loop()

        try:
            await loop.run_in_executor(None, self._api.refresh_credentials)
        except Exception as err:
            LOGGER.error(f"Failed to refresh credentials: {err}")
            return

        scraper = self._api.scraper
        if not scraper:
            return

        hist_states: List[HistoricalState] = []
        yesterday = datetime(year=now.year, month=now.month, day=now.day, tzinfo=UTC) - timedelta(days=1)
        lookback_days = LOOKUP_DAYS if not self._initial_fetch_done else ONGOING_LOOKUP_DAYS

        executor_results = []
        with ThreadPoolExecutor(max_workers=PARALLEL_DAYS) as executor:
            current_date = yesterday - timedelta(days=lookback_days)
            while current_date <= yesterday:
                try:
                    results = loop.run_in_executor(executor, scraper.get_data, current_date, self._tariff_type)
                    executor_results.append(results)
                except Exception:
                    pass
                current_date += timedelta(days=1)
        
        self._last_update_time = now

        for executor_result in executor_results:
            try:
                for datapoint in await executor_result:
                    state = datapoint.get(self._metric)
                    dt = datetime.fromtimestamp(datapoint.get("intervalEnd"), tz=UTC)
                    hist_states.append(HistoricalState(state=state, dt=dt))
            except Exception:
                continue

        hist_states.sort(key=lambda d: d.dt)
        valid_datapoints = [d for d in hist_states if d.state is not None and isinstance(d.state, (int, float))]

        if valid_datapoints:
            max_dt = valid_datapoints[-1].dt
            self._last_data_timestamp = max_dt
            self._initial_fetch_done = True
            self._attr_historical_states = [d for d in hist_states if d.state]

        if self._attr_historical_states:
            self._attr_native_value = self._attr_historical_states[-1].state
        else:
            self._attr_native_value = 0
            
        self.async_write_ha_state()

    @property
    def statistic_id(self) -> str:
        return self.entity_id

    def get_statistic_metadata(self) -> StatisticMetaData:
        """
        Add sum and mean to base statistics metadata.
        Updated for Home Assistant 2024.11+ requirements.
        """
        meta = super().get_statistic_metadata()
        meta["has_sum"] = True
        meta["mean_type"] = StatisticMeanType.ARITHMETIC
        
        # Only set unit_class for physical quantities with converters.
        # Cost (monetary) uses None to avoid recorder errors.
        if self._attr_device_class == SensorDeviceClass.ENERGY:
            meta["unit_class"] = "energy"
        else:
            meta["unit_class"] = None

        return meta

    async def async_calculate_statistic_data(
            self, hist_states: list[HistoricalState], *, latest: dict | None = None
    ) -> list[StatisticData]:
        accumulated = latest["sum"] if latest else 0

        def hour_block_for_hist_state(hist_state: HistoricalState) -> datetime:
            if hist_state.dt.minute == 0 and hist_state.dt.second == 0:
                dt = hist_state.dt - timedelta(hours=1)
                return dt.replace(minute=0, second=0, microsecond=0)
            return hist_state.dt.replace(minute=0, second=0, microsecond=0)

        ret = []
        for dt, collection_it in itertools.groupby(hist_states, key=hour_block_for_hist_state):
            collection = list(collection_it)
            mean = statistics.mean([x.state for x in collection])
            partial_sum = sum([x.state for x in collection])
            accumulated = accumulated + partial_sum
            ret.append(StatisticData(start=dt, state=partial_sum, mean=mean, sum=accumulated))
        return ret
