import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import (SensorEntity, SensorDeviceClass, SensorStateClass, SensorEntityDescription)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    sensors = list()
    sensors.append(UntrackedEnergyTrackerSensor(hass, entry))

    async_add_entities(sensors)

class UntrackedEnergyTrackerSensor(SensorEntity):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(self)
        self.hass = hass
        self.config_entry = entry

        self.entity_description = SensorEntityDescription(
            key="untracked",
            name="Untracked energy",
            native_unit_of_measurement="kWh",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL,
        )
        self._attr_unique_id = f"{entry.entry_id}-untracked-energy-tracker-sensor"

    @property
    def native_value(self):
        return 1

