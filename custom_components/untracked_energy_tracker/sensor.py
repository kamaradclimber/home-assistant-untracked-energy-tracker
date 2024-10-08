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
    sensors.append(ConsumedEnergyTrackerSensor(hass, entry))

    async_add_entities(sensors)

async def compute_house_consumption(obj) -> float:
        house_consumption = 0
        energy_manager = await async_get_manager(obj.hass)
        for source in energy_manager.data["energy_sources"]:
            if source["type"] == "grid":
                for grid_consumer in source["flow_from"]:
                    diff = obj.delta_since_last_run(grid_consumer["stat_energy_from"])
                    if diff is not None:
                        house_consumption += diff
                for grid_consumer in source["flow_to"]:
                    diff = obj.delta_since_last_run(grid_consumer["stat_energy_to"])
                    if diff is not None:
                        house_consumption -= diff
            if source["type"] == "solar":
                diff = obj.delta_since_last_run(source["stat_energy_from"])
                if diff is not None:
                    house_consumption += diff
            if source["type"] == "battery":
                # stat_energy_to represents energy coming from the battery
                diff = obj.delta_since_last_run(source["stat_energy_from"])
                if diff is not None:
                    house_consumption += diff
                # stat_energy_to represents energy going to the battery
                diff = obj.delta_since_last_run(source["stat_energy_to"])
                if diff is not None:
                    house_consumption -= diff
        _LOGGER.debug(f"House consumed {house_consumption}kWh")
        return house_consumption

class ConsumedEnergyTrackerSensor(SensorEntity):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__()
        self.hass = hass
        self.config_entry = entry
        self._attr_should_poll = True
        self._state = 0
        self._last_value = {}

        self.entity_description = SensorEntityDescription(
            key="consumed_energy",
            name="Consumed Energy",
            native_unit_of_measurement="kWh",
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
        )
        self._attr_unique_id = f"{entry.entry_id}-consumed-energy-tracker-sensor"
        self._attr_state_attributes = {}
        self._attr_state_attributes["iterations"] = 0
        self._attr_state_attributes["successful_iterations"] = 0

    @property
    def native_value(self):
        return self._state

    # this is called once every 30s but no guarantee
    async def async_update(self) -> None:
        await self._update_value()

    async def _update_value(self) -> None:
        self._attr_state_attributes["iterations"] += 1
        house_consumption = await compute_house_consumption(self)
        self._attr_state_attributes["successful_iterations"] += 1
        self._state += house_consumption




    def delta_since_last_run(self, entity_id: str) -> float | None:
        """
        Takes an entity_id of an entity exposing energy in Wh or kWh
        Return the consumption/production in kWh since last measurement.
        Return None if we don't have previous measurement or if current state is unknown
        """
        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.warn(f"{entity_id} has no known state, this is really weird")
            return
        if state.state == "unknown" or state.state == "unavailable":
            # temporarily unavailable
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
        self._attr_state_attributes["iterations"] = 0
        self._attr_state_attributes["successful_iterations"] = 0

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
        self._attr_state_attributes["iterations"] += 1
        sum_in_kWh = 0
        for entity_id in self.individual_device_entities:
            diff = self.delta_since_last_run(entity_id)
            if diff is not None:
                sum_in_kWh += diff
        _LOGGER.debug(f"Individually tracked devices consumed {sum_in_kWh}kWh")

        # now update global energy flows
        house_consumption = await compute_house_consumption(self)
        if house_consumption < sum_in_kWh:
            _LOGGER.warn(f"It seems house consumption was negative (even after removing energy sent back to the grid or to a battery). Skipping this iteration")
            return
        self._attr_state_attributes["successful_iterations"] += 1
        self._state += house_consumption - sum_in_kWh

    def delta_since_last_run(self, entity_id: str) -> float | None:
        """
        Takes an entity_id of an entity exposing energy in Wh or kWh
        Return the consumption/production in kWh since last measurement.
        Return None if we don't have previous measurement or if current state is unknown
        """
        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.warn(f"{entity_id} has no known state, this is really weird")
            return
        if state.state == "unknown" or state.state == "unavailable":
            # temporarily unavailable
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

