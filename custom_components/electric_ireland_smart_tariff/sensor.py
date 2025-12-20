import logging

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, CURRENCY_EURO
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import DiscoveryInfoType

from .api import ElectricIrelandScraper
from .const import (
    TARIFF_OFF_PEAK,
    TARIFF_MID_PEAK,
    TARIFF_ON_PEAK,
    TARIFF_NAMES,
)
from .sensor_base import Sensor

PLATFORM = "sensor"

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        async_add_devices: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,  # noqa DiscoveryInfoType | None
):
    username = config_entry.data["username"]
    password = config_entry.data["password"]
    account_number = config_entry.data["account_number"]

    ei_api = ElectricIrelandScraper(username, password, account_number)

    sensors = [
        # Total sensors (all tariffs combined)
        ConsumptionSensor(device_id=config_entry.entry_id, ei_api=ei_api),
        CostSensor(device_id=config_entry.entry_id, ei_api=ei_api),
    ]
    
    # Add tariff-specific sensors only for TOU (Time of Use) tariffs
    # Skip flatRate as it's not used on TOU plans
    tou_tariffs = [TARIFF_OFF_PEAK, TARIFF_MID_PEAK, TARIFF_ON_PEAK]
    
    for tariff_type in tou_tariffs:
        sensors.extend([
            ConsumptionSensor(
                device_id=config_entry.entry_id,
                ei_api=ei_api,
                tariff_type=tariff_type
            ),
            CostSensor(
                device_id=config_entry.entry_id,
                ei_api=ei_api,
                tariff_type=tariff_type
            ),
        ])
    
    async_add_devices(sensors)


class ConsumptionSensor(Sensor):
    def __init__(self, device_id: str, ei_api: ElectricIrelandScraper, tariff_type: str = None):
        # Build name with tariff if specified
        tariff_name = TARIFF_NAMES.get(tariff_type, "") if tariff_type else ""
        name = f"Consumption {tariff_name}".strip() if tariff_type else "Consumption"
        
        super().__init__(
            device_id, ei_api,
            name, "consumption",
            UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY,
            tariff_type=tariff_type
        )


class CostSensor(Sensor):
    def __init__(self, device_id: str, ei_api: ElectricIrelandScraper, tariff_type: str = None):
        # Build name with tariff if specified
        tariff_name = TARIFF_NAMES.get(tariff_type, "") if tariff_type else ""
        name = f"Cost {tariff_name}".strip() if tariff_type else "Cost"
        
        super().__init__(
            device_id, ei_api,
            name, "cost",
            CURRENCY_EURO, SensorDeviceClass.MONETARY,
            tariff_type=tariff_type
        )
