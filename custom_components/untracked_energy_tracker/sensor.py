import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import (SensorEntity, SensorDeviceClass, SensorStateClass, SensorEntityDescription)
from homeassistant.components.energy.data import async_get_manager

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
        super().__init__()
        self.hass = hass
        self.config_entry = entry
        self._attr_should_poll = True
        self._state = 0
        self._last_sum = None

        self.entity_description = SensorEntityDescription(
            key="untracked",
            name="Untracked energy",
            native_unit_of_measurement="kWh",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
        )
        self._attr_unique_id = f"{entry.entry_id}-untracked-energy-tracker-sensor"
        self._attr_state_attributes = {}

    @property
    def native_value(self):
        return self._state

    # this is called once every 30s but no guarantee
    async def async_update(self) -> None:
        await self._list_individual_device()
        await self._update_value()

    async def _list_individual_device(self):
        # TODO: investigate using async_listen_updates on the manager instead of exploring it at each iteration
        energy_manager = await async_get_manager(self.hass)
        individual_device_entities = []
        for device in energy_manager.data["device_consumption"]:
            if device["stat_consumption"] != self.entity_id:
                individual_device_entities.append(device["stat_consumption"])
        self.individual_device_entities = individual_device_entities
        self._attr_state_attributes["individual_devices"] = self.individual_device_entities

    async def _update_value(self) -> None:
        sum_in_kWh = 0
        for entity_id in self.individual_device_entities:
            state = self.hass.states.get(entity_id)
            if state is None:
                return
            value = float(state.state)
            # FIXME: we should not sum all individual devices and then make a difference: we should instead measure the diff for each device (to account for reset)
            if state.attributes["unit_of_measurement"] == "Wh":
                sum_in_kWh += value / 1000
            elif state.attributes["unit_of_measurement"] == "kWh":
                sum_in_kWh += value
            else:
                _LOGGER.warn(f"Unable to deal with unit of measurement of {state}")
        if self._last_sum is not None:
            # FIXME: for now we are simply adding all individual devices but what we want is to substract that sum to the amount of energy consumed by the house
            self._state += sum_in_kWh - self._last_sum
        self._last_sum = sum_in_kWh

    @property
    def state_attributes(self):
        return self._attr_state_attributes

