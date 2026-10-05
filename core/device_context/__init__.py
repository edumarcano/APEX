"""Permissioned, on-demand device context for Weather location resolution."""

from core.device_context.service import (
    DeviceContextService,
    DeviceContextStatus,
    WeatherLocation,
    default_weather_available,
    get_device_context_service,
    resolve_weather_location,
    set_device_context_service,
    weather_location_eligible,
    weather_location_revision,
)

__all__ = [
    "DeviceContextService",
    "DeviceContextStatus",
    "WeatherLocation",
    "default_weather_available",
    "get_device_context_service",
    "resolve_weather_location",
    "set_device_context_service",
    "weather_location_eligible",
    "weather_location_revision",
]
