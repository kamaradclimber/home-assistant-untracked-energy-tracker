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
        self._last_value = {}

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
            diff = self.delta_since_last_run(entity_id)
            if diff is not None:
                sum_in_kWh += diff

        # now update global energy flows
        house_consumption = 0
        energy_manager = await async_get_manager(self.hass)
        for source in energy_manager.data["energy_sources"]:
            if source["type"] == "grid":
                for grid_consumer in source["flow_from"]:
                    diff = self.delta_since_last_run(grid_consumer["stat_energy_from"])
                    if diff is not None:
                        house_consumption += diff
                for grid_consumer in source["flow_to"]:
                    diff = self.delta_since_last_run(grid_consumer["stat_energy_to"])
                    if diff is not None:
                        house_consumption -= diff
            if source["type"] == "solar":
                diff = self.delta_since_last_run(source["stat_energy_from"])
                if diff is not None:
                    house_consumption += diff
            if source["type"] == "battery":
                # stat_energy_to represents energy coming from the battery
                diff = self.delta_since_last_run(source["stat_energy_from"])
                if diff is not None:
                    house_consumption += diff
                # stat_energy_to represents energy going to the battery
                diff = self.delta_since_last_run(source["stat_energy_to"])
                if diff is not None:
                    house_consumption -= diff
        self._state = house_consumption - sum_in_kWh



    def delta_since_last_run(self, entity_id: str) -> float | None:
         state = self.hass.states.get(entity_id)
         if state is None:
             _LOGGER.warn(f"{entity_id} has no known state, this is really weird")
             return
         value = float(state.state)
         if state.attributes["unit_of_measurement"] == "Wh":
             value = value / 1000
         elif state.attributes["unit_of_measurement"] != "kWh":
             _LOGGER.warn(f"Unable to deal with unit of measurement of {state}")
         old_value = self._last_value.get(entity_id, None)
         self._last_value[entity_id] = value
         if old_value is not None:
             if old_value <= value:
                 return value - old_value
             else:
                 _LOGGER.warn(f"{entity_id} seems to have been reset since last read. Current value {value}, last known_value {old_value}")
                 return value



    @property
    def state_attributes(self):
        return self._attr_state_attributes

