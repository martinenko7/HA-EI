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
    #
    # Base clases:
    # - SensorEntity: This is a sensor, obvious
    # - HistoricalSensor: This sensor implements historical sensor methods
    # - PollUpdateMixin: Historical sensors disable poll, this mixing
    #                    reenables poll only for historical states and not for
    #                    present state
    #

    def __init__(self, device_id: str, ei_api: ElectricIrelandScraper, name: str, metric: str, measurement_unit: str,
                 device_class: SensorDeviceClass, tariff_type: str = None):
        super().__init__()

        self._attr_has_entity_name = True
        self._attr_name = f"Electric Ireland {name}"

        # Include tariff type in unique_id if specified
        tariff_suffix = f"_{tariff_type}" if tariff_type else ""
        self._attr_unique_id = f"{DOMAIN}_{metric}{tariff_suffix}_{device_id}"
        self._attr_entity_id = f"{DOMAIN}_{metric}{tariff_suffix}_{device_id}"

        self._attr_entity_registry_enabled_default = True
        self._attr_state = None
        self._attr_native_unit_of_measurement = measurement_unit
        self._attr_device_class = device_class
        # NOTE: state_class is intentionally NOT set
        # HistoricalSensor manages statistics internally and state_class will break them
        
        self._api: ElectricIrelandScraper = ei_api

        self._metric = metric
        self._tariff_type = tariff_type
        self._last_data_timestamp = None  # Track last successful data retrieval
        self._last_update_time = None  # Track last API fetch to prevent excessive requests
        self._initial_fetch_done = False  # Flag to track if initial historical data has been fetched

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

    async def async_update_historical(self):
        # Fill `HistoricalSensor._attr_historical_states` with HistoricalState's
        # This functions is equivaled to the `Sensor.async_update` from
        # HomeAssistant core
        #
        # Important: You must provide datetime with tzinfo

        now = datetime.now(UTC)
        
        # Smart update logic: Skip if updated recently (unless first run)
        if self._last_update_time and self._initial_fetch_done:
            hours_since_update = (now - self._last_update_time).total_seconds() / 3600
            if hours_since_update < MIN_UPDATE_INTERVAL_HOURS:
                LOGGER.debug(f"Skipping update for {self._attr_name}: only {hours_since_update:.1f} hours since last update (min {MIN_UPDATE_INTERVAL_HOURS}h)")
                return

        loop = asyncio.get_running_loop()

        try:
            await loop.run_in_executor(None, self._api.refresh_credentials)
        except Exception as err:
            LOGGER.error(f"Failed to refresh credentials: {err}")
            LOGGER.debug(f"Full error details: {type(err).__name__}: {err}", exc_info=True)
            return

        scraper = self._api.scraper

        if not scraper:
            LOGGER.error("Failed to get scraper - login may have failed")
            return

        hist_states: List[HistoricalState] = []

        # Build a datetime for "yesterday" since data is never published on the same day
        yesterday = datetime(year=now.year, month=now.month, day=now.day, tzinfo=UTC) - timedelta(days=1)

        # Smart lookback: use full history on first run, then only recent days
        if not self._initial_fetch_done:
            lookback_days = LOOKUP_DAYS
            LOGGER.info(f"Initial data fetch for {self._attr_name}: retrieving {lookback_days} days of historical data")
        else:
            lookback_days = ONGOING_LOOKUP_DAYS
            LOGGER.debug(f"Ongoing update for {self._attr_name}: checking last {lookback_days} days for new data")

        executor_results = []

        with ThreadPoolExecutor(max_workers=PARALLEL_DAYS) as executor:
            current_date = yesterday - timedelta(days=lookback_days)
            while current_date <= yesterday:
                LOGGER.debug(f"Submitting {current_date}")
                try:
                    # Pass tariff_type to get_data
                    results = loop.run_in_executor(executor, scraper.get_data, current_date, self._tariff_type)
                    executor_results.append(results)
                except Exception as err:
                    LOGGER.warning(f"Failed to submit job for {current_date}: {err}")
                current_date += timedelta(days=1)
        
        # Mark update time
        self._last_update_time = now

        LOGGER.info("Finished launching jobs")

        # For every launched job
        for executor_result in executor_results:
            try:
                # And now we parse the datapoints
                for datapoint in await executor_result:
                    state = datapoint.get(self._metric)
                    dt = datetime.fromtimestamp(datapoint.get("intervalEnd"), tz=UTC)
                    
                    hist_states.append(HistoricalState(
                        state=state,
                        dt=dt,
                    ))
            except Exception as err:
                LOGGER.warning(f"Failed to process executor result: {err}")
                continue

        hist_states.sort(key=lambda d: d.dt)

        valid_datapoints: List[HistoricalState] = []
        null_datapoints: List[HistoricalState] = []
        invalid_datapoints: List[HistoricalState] = []
        for hist_state in hist_states:
            if hist_state.state is None:
                null_datapoints.append(hist_state)
                continue
            if not isinstance(hist_state.state, (int, float,)):
                invalid_datapoints.append(hist_state)
                continue
            valid_datapoints.append(hist_state)

        if null_datapoints:
            min_dt, max_dt = null_datapoints[0].dt, null_datapoints[len(null_datapoints) - 1].dt
            LOGGER.debug(f"Found {len(null_datapoints)} null datapoints for {self._attr_name}, ranging from {min_dt} to {max_dt}. This is normal for recent time periods.")

        if invalid_datapoints:
            LOGGER.info(f"Found {len(invalid_datapoints)} invalid datapoints for {self._attr_name}. These will be skipped.")

        if not valid_datapoints:
            # Check if we have recent data from a previous pull
            data_age_hours = None
            if self._last_data_timestamp:
                data_age = now - self._last_data_timestamp
                data_age_hours = data_age.total_seconds() / 3600
            
            # Only log error if data is stale (>48 hours old) or never retrieved
            if data_age_hours is None:
                LOGGER.warning(f"No valid datapoints found on first attempt for {self._attr_name}. This is normal - Electric Ireland data has 1-3 day delay.")
            elif data_age_hours > 48:
                LOGGER.error(f"No valid datapoints found for {self._attr_name}! Last successful data was {data_age_hours:.1f} hours ago. Check credentials or Electric Ireland website.")
            else:
                LOGGER.debug(f"No new datapoints for {self._attr_name}. Last data was {data_age_hours:.1f} hours ago (within expected 1-3 day delay).")
        else:
            min_dt, max_dt = valid_datapoints[0].dt, valid_datapoints[len(valid_datapoints) - 1].dt
            
            # Calculate how recent the data is
            data_age = now - max_dt
            data_age_hours = data_age.total_seconds() / 3600
            
            # Update last successful data timestamp
            self._last_data_timestamp = max_dt
            
            # Mark initial fetch as complete
            if not self._initial_fetch_done:
                self._initial_fetch_done = True
                LOGGER.info(f"Initial fetch complete for {self._attr_name}: {len(valid_datapoints)} datapoints from {min_dt} to {max_dt}")
            
            # Log with appropriate level based on data freshness
            if data_age_hours > 72:  # More than 3 days old
                LOGGER.warning(f"Found {len(valid_datapoints)} valid datapoints for {self._attr_name}, ranging from {min_dt} to {max_dt}. Latest data is {data_age_hours:.1f} hours old (older than typical 1-3 day delay).")
            else:
                LOGGER.info(f"Found {len(valid_datapoints)} valid datapoints for {self._attr_name}, ranging from {min_dt} to {max_dt}. Latest data is {data_age_hours:.1f} hours old.")

            self._attr_historical_states = [d for d in hist_states if d.state]

        # FIX: Update the 'Current State' so the entity is not 'Unknown'
        if self._attr_historical_states:
            # Set state to the most recent value found
            self._attr_native_value = self._attr_historical_states[-1].state
        else:
            # Set to 0 if no data yet (prevents "unknown" state in Energy Dashboard)
            self._attr_native_value = 0
            
        self.async_write_ha_state()


    @property
    def statistic_id(self) -> str:
        return self.entity_id

                def get_statistic_metadata(self) -> StatisticMetaData:
        """
        Add sum and mean to base statistics metadata.
        Updated to comply with Home Assistant 2024.11+ requirements.
        """
        meta = super().get_statistic_metadata()
        
        # 'has_sum' remains required for historical energy/cost tracking
        meta["has_sum"] = True
        
        # FIX: Replace deprecated 'has_mean' with explicit 'mean_type'
        # This resolves the MissingIntegrationFrame/RuntimeError
        meta["mean_type"] = StatisticMeanType.ARITHMETIC
        
        # Set unit_class based on device_class for proper statistics handling
        if self._attr_device_class == SensorDeviceClass.ENERGY:
            meta["unit_class"] = "energy"
        elif self._attr_device_class == SensorDeviceClass.MONETARY:
            meta["unit_class"] = "monetary"

        return meta



    async def async_calculate_statistic_data(
            self, hist_states: list[HistoricalState], *, latest: dict | None = None
    ) -> list[StatisticData]:
        #
        # Group historical states by hour
        # Calculate sum, mean, etc...
        #

        accumulated = latest["sum"] if latest else 0

        def hour_block_for_hist_state(hist_state: HistoricalState) -> datetime:
            # XX:00:00 states belongs to previous hour block
            if hist_state.dt.minute == 0 and hist_state.dt.second == 0:
                dt = hist_state.dt - timedelta(hours=1)
                return dt.replace(minute=0, second=0, microsecond=0)

            else:
                return hist_state.dt.replace(minute=0, second=0, microsecond=0)

        ret = []
        for dt, collection_it in itertools.groupby(hist_states, key=hour_block_for_hist_state):
            collection = list(collection_it)
            mean = statistics.mean([x.state for x in collection])
            partial_sum = sum([x.state for x in collection])
            accumulated = accumulated + partial_sum

            ret.append(
                StatisticData(
                    start=dt,
                    state=partial_sum,
                    mean=mean,
                    sum=accumulated,
                )
            )

        return ret