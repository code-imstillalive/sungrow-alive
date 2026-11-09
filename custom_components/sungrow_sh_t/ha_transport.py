"""Home Assistant's shared Modbus connections (2026.11 and later) as this integration's transport.

`homeassistant.components.modbus.connection.async_get_unit` hands out a unit on
a connection shared by every integration that talks to the same address and
port, serialised behind that connection's lock and listed under Settings >
Connectivity > Modbus. Each Logger port is its own connection there; the
scheduler still keeps one request in flight across all of them, because the
Logger reaches every device over one RS485 bus.

Errors are mapped onto the scheduler's own: a refused register stays a
refusal (the merged-block split depends on it), anything else on the link is
a connection problem.
"""

from __future__ import annotations

try:
    from homeassistant.components.modbus import async_get_unit
except ImportError:  # the public name arrived after the module
    from homeassistant.components.modbus.connection import async_get_unit
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from modbus_connection import (
    ModbusError as LinkError,
)
from modbus_connection import (
    ModbusExceptionError,
    ModbusTcpParams,
)

from .scheduler import ModbusError


class HaTransport:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, host: str, timeout: float) -> None:
        self.hass, self.entry, self.host, self.timeout = hass, entry, host, timeout
        self._units: dict[tuple[int, int], object] = {}

    def _unit(self, port: int, unit: int):
        key = (port, unit)
        if key not in self._units:
            u = async_get_unit(self.hass, self.entry, ModbusTcpParams(host=self.host, port=port), unit)
            u.require_timeout(self.timeout)
            self._units[key] = u
        return self._units[key]

    async def read(self, port: int, unit: int, space: str, address: int, count: int) -> list[int]:
        u = self._unit(port, unit)
        try:
            regs = list(await (u.read_input_registers if space == "input" else u.read_holding_registers)(address, count))
        except ModbusExceptionError as err:
            raise ModbusError(int(err.exception_code or 0)) from err
        except LinkError as err:
            raise ConnectionError(str(err) or type(err).__name__) from err
        if len(regs) != count:  # a short answer: as if lost
            raise ConnectionError(f"port {port} unit {unit}: {len(regs)} registers for {count}")
        return regs

    async def write(self, port: int, unit: int, address: int, values: list[int]) -> None:
        u = self._unit(port, unit)
        try:
            if len(values) == 1:
                await u.write_register(address, values[0])
            else:
                await u.write_registers(address, values)
        except ModbusExceptionError as err:
            raise ModbusError(int(err.exception_code or 0)) from err
        except LinkError as err:
            raise ConnectionError(str(err) or type(err).__name__) from err

    def close(self) -> None:
        """Home Assistant releases each unit when the config entry unloads."""
