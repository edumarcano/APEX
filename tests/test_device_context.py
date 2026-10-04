"""Focused tests for permissioned device context location handling."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from pydantic import ValidationError

from core.device_context.service import (
    DeviceContextService,
    LOCATION_FIX_MAX_AGE_SECONDS,
    default_weather_available,
    resolve_weather_location,
    set_device_context_service,
    weather_location_eligible,
)
from core.api.routers.system import get_device_context_status
from core.host.protocol import ControlProtocolError, validate_envelope
from core.settings.models import SettingsPatch
from core.settings.store import RuntimeSettingsStore, SettingsPersistenceError


INSTANCE_ID = str(uuid.UUID("e783bad3-cd83-4c26-9edc-91f8f67d23e4"))


class DeviceContextServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1_800_000_000.0
        self.monotonic = 100.0
        self.requests: list[tuple[dict[str, object], str]] = []
        self.service = self._service()
        set_device_context_service(self.service)
        self.addCleanup(set_device_context_service, None)

    def _service(self, sink=None) -> DeviceContextService:
        return DeviceContextService(
            instance_id=INSTANCE_ID,
            enabled=True,
            supported=True,
            request_sink=sink or self._send,
            wall_clock=lambda: self.now,
            monotonic_clock=lambda: self.monotonic,
        )

    def _send(self, payload: dict[str, object], request_id: str) -> bool:
        self.requests.append((payload, request_id))
        return True

    def _grant(self, service: DeviceContextService | None = None) -> None:
        (service or self.service).handle_state(
            {
                "instance_id": INSTANCE_ID,
                "revision": 1,
                "permission": "granted",
                "availability": "available",
            },
            "device-state:1",
        )

    def _reply(
        self,
        service: DeviceContextService,
        request_id: str,
        *,
        outcome: str = "ok",
        latitude: float = 42.3,
        longitude: float = -71.1,
        observed_at: float | None = None,
    ) -> bool:
        return service.handle_result(
            {
                "instance_id": INSTANCE_ID,
                "revision": 1,
                "outcome": outcome,
                "fix": (
                    {
                        "latitude": latitude,
                        "longitude": longitude,
                        "observed_at": self.now if observed_at is None else observed_at,
                    }
                    if outcome == "ok"
                    else None
                ),
            },
            request_id,
        )

    def test_precedence_and_headless_fallback_are_dynamic(self) -> None:
        with mock.patch.dict(os.environ, {"TARGET_LOCATION": "Boston"}, clear=False):
            self.assertEqual(resolve_weather_location().location, "Boston")
            self.assertTrue(default_weather_available())
        with mock.patch.dict(os.environ, {"TARGET_LOCATION": ""}, clear=False):
            self.assertFalse(default_weather_available())
            self.assertEqual(resolve_weather_location().source, "none")
        self.assertEqual(self.service.resolve("  Tokyo ").location, "Tokyo")
        self.assertEqual(self.service.resolve(" Tokyo ").source, "explicit")

    def test_permission_state_is_passive_and_device_fix_is_private(self) -> None:
        self.assertFalse(weather_location_eligible())
        before = self.service.status()
        self.assertEqual(before.permission, "unknown")
        self.assertEqual(self.requests, [])
        self.assertEqual(get_device_context_status().permission, "unknown")
        self.assertEqual(self.requests, [])

        self._grant()
        self.assertTrue(weather_location_eligible())
        resolved: list[object] = []
        worker = threading.Thread(target=lambda: resolved.append(self.service.resolve()))
        worker.start()
        self.assertTrue(self._wait_for_request())
        self.assertTrue(self._reply(self.service, "device:1"))
        worker.join(2)

        self.assertFalse(worker.is_alive())
        location = resolved[0]
        self.assertEqual(location.source, "device")
        self.assertEqual(location.location, "Current area")
        self.assertEqual(location.coordinates, (42.3, -71.1))
        self.assertNotIn("latitude", self.service.status().as_dict())
        self.assertEqual(self.service.status().freshness, "fresh")

    def test_concurrent_reads_share_one_native_request_and_result(self) -> None:
        self._grant()
        values: list[object] = []
        first = threading.Thread(target=lambda: values.append(self.service.resolve()))
        second = threading.Thread(target=lambda: values.append(self.service.resolve()))
        first.start()
        self.assertTrue(self._wait_for_request())
        second.start()
        with self.service._condition:
            self.assertTrue(self.service._condition.wait_for(lambda: self.service._pending_readers == 2, 2))
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self._reply(self.service, "device:1"))
        first.join(2)
        second.join(2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual([value.coordinates for value in values], [(42.3, -71.1), (42.3, -71.1)])

    def test_state_before_result_keeps_waiter_and_timeout_can_retry(self) -> None:
        self._grant()
        completed: list[object] = []
        worker = threading.Thread(target=lambda: completed.append(self.service.resolve()))
        worker.start()
        self.assertTrue(self._wait_for_request())
        self.service.handle_state(
            {
                "instance_id": INSTANCE_ID,
                "revision": 1,
                "permission": "granted",
                "availability": "timed_out",
            },
            "device-state:2",
        )
        self.assertTrue(self._reply(self.service, "device:1"))
        worker.join(2)
        self.assertEqual(completed[0].source, "device")

        retry_requests: list[str] = []
        service: DeviceContextService

        def sink(payload: dict[str, object], request_id: str) -> bool:
            retry_requests.append(request_id)
            if len(retry_requests) == 2:
                service.handle_result(
                    {
                        "instance_id": INSTANCE_ID,
                        "revision": 1,
                        "outcome": "ok",
                        "fix": {"latitude": 1, "longitude": 2, "observed_at": self.now},
                    },
                    request_id,
                )
            return True

        service = DeviceContextService(
            instance_id=INSTANCE_ID,
            enabled=True,
            supported=True,
            request_sink=sink,
            wall_clock=lambda: self.now,
            monotonic_clock=time.monotonic,
        )
        set_device_context_service(service)
        self._grant(service)
        with mock.patch("core.device_context.service.LOCATION_REQUEST_TIMEOUT_SECONDS", 0.01):
            self.assertEqual(service.resolve().source, "none")
            self.assertTrue(weather_location_eligible())
            self.assertEqual(service.resolve().source, "device")
        self.assertEqual(retry_requests, ["device:1", "device:2"])

    def test_disable_and_late_reply_clear_generation_without_using_coordinates(self) -> None:
        self._grant()
        results: list[object] = []
        worker = threading.Thread(target=lambda: results.append(self.service.resolve()))
        worker.start()
        self.assertTrue(self._wait_for_request())
        self.assertTrue(self.service.set_enabled(False))
        self.assertFalse(self._reply(self.service, "device:1"))
        worker.join(2)
        self.assertEqual(results[0].source, "none")
        self.assertEqual(self.service.preference_payload()["revision"], 2)
        self.assertIsNone(self.service.status().fix_age_seconds)

    def test_shutdown_cancels_waiting_native_read_and_clears_fix(self) -> None:
        self._grant()
        returned: list[object] = []
        worker = threading.Thread(target=lambda: returned.append(self.service.resolve()))
        worker.start()
        self.assertTrue(self._wait_for_request())
        self.service.close()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(returned[0].source, "none")
        self.assertEqual(self.service.status().availability, "unavailable")
        self.assertFalse(self._reply(self.service, "device:1"))

    def test_invalid_expired_future_and_rollback_extended_fixes_are_rejected(self) -> None:
        self._grant()
        results: list[object] = []
        worker = threading.Thread(target=lambda: results.append(self.service.resolve()))
        worker.start()
        self.assertTrue(self._wait_for_request())
        self.assertTrue(self._reply(self.service, "device:1", latitude=91))
        worker.join(2)
        self.assertEqual(results[0].source, "none")

        for observed_at in (self.now + 1, self.now - LOCATION_FIX_MAX_AGE_SECONDS - 1):
            service = self._service()
            self._grant(service)
            done: list[object] = []
            worker = threading.Thread(target=lambda: done.append(service.resolve()))
            worker.start()
            with service._condition:
                self.assertTrue(service._condition.wait_for(lambda: service._pending_id is not None, 2))
                request_id = service._pending_id
            self.assertTrue(self._reply(service, request_id, observed_at=observed_at))
            worker.join(2)
            self.assertEqual(done[0].source, "none")

        service = self._service()
        self._grant(service)
        done = []
        worker = threading.Thread(target=lambda: done.append(service.resolve()))
        worker.start()
        with service._condition:
            self.assertTrue(service._condition.wait_for(lambda: service._pending_id is not None, 2))
            request_id = service._pending_id
        self.assertTrue(self._reply(service, request_id, observed_at=10 ** 400))
        worker.join(2)
        self.assertEqual(done[0].source, "none")

        self.now = 1_000.0
        service = self._service()
        self._grant(service)
        done = []
        worker = threading.Thread(target=lambda: done.append(service.resolve()))
        worker.start()
        with service._condition:
            self.assertTrue(service._condition.wait_for(lambda: service._pending_id is not None, 2))
            request_id = service._pending_id
        self.assertTrue(self._reply(service, request_id, observed_at=200.0))
        worker.join(2)
        self.monotonic += LOCATION_FIX_MAX_AGE_SECONDS - 199
        self.now = 1_000.0
        self.assertEqual(service.status().freshness, "expired")

    def test_all_native_failure_outcomes_preserve_configured_fallback_and_status(self) -> None:
        for outcome, permission in (
            ("permission_required", "unknown"),
            ("denied", "denied"),
            ("revoked", "revoked"),
            ("unavailable", "granted"),
            ("timed_out", "granted"),
            ("expired", "granted"),
            ("unsupported", "unsupported"),
        ):
            with self.subTest(outcome=outcome), mock.patch.dict(os.environ, {"TARGET_LOCATION": "Boston"}):
                service = self._service()
                self._grant(service)
                location: list[object] = []
                worker = threading.Thread(target=lambda: location.append(service.resolve()))
                worker.start()
                with service._condition:
                    self.assertTrue(service._condition.wait_for(lambda: service._pending_id is not None, 2))
                    request_id = service._pending_id
                self.assertTrue(self._reply(service, request_id, outcome=outcome))
                worker.join(2)
                self.assertEqual(location[0].source, "configured")
                self.assertEqual(service.status().permission, permission)

    def test_completed_coalesced_result_keeps_its_own_fix_while_next_request_runs(self) -> None:
        self._grant()
        with self.service._condition:
            self.service._pending_id = "device:99"
            self.service._pending_revision = self.service._revision
            self.service._pending_readers = 2
            self.service._fix = (1.0, 2.0, self.now, self.monotonic, 0.0)
            self.service._finish_pending_locked("ok", self.service._fix)
            first_completion = self.service._completed["device:99"]
            self.service._pending_id = "device:100"
            self.service._pending_revision = self.service._revision
            self.service._pending_readers = 1
            self.service._fix = None
            self.service._finish_pending_locked("unavailable")
            self.assertEqual(self.service._completed["device:99"], first_completion)
            self.assertIsNone(self.service._completed["device:100"][3])

    def _wait_for_request(self) -> bool:
        with self.service._condition:
            return self.service._condition.wait_for(lambda: self.service._pending_id is not None, 2)


class DeviceContextSettingsAndProtocolTests(unittest.TestCase):
    def test_preference_defaults_round_trips_strictly_and_failed_write_keeps_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex_device_context_") as temp:
            root = Path(temp)
            config = root / "config.json"
            local = root / "config.local.json"
            config.write_text("{}\n", encoding="utf-8")
            store = RuntimeSettingsStore(config_path=config, local_config_path=local)
            self.assertFalse(store.get_snapshot().device_context.location_enabled)
            updated = store.apply_patch(SettingsPatch.model_validate({
                "device_context": {"location_enabled": True}
            }))
            self.assertTrue(updated.device_context.location_enabled)
            self.assertEqual(json.loads(local.read_text(encoding="utf-8"))["device_context"], {"location_enabled": True})
            self.assertTrue(RuntimeSettingsStore(config_path=config, local_config_path=local).get_snapshot().device_context.location_enabled)

            before = store.get_snapshot()
            with mock.patch.object(store, "_atomic_write_local", side_effect=SettingsPersistenceError("blocked")):
                with self.assertRaises(SettingsPersistenceError):
                    store.apply_patch(SettingsPatch.model_validate({
                        "device_context": {"location_enabled": False}
                    }))
            self.assertIs(store.get_snapshot(), before)

        for payload in (
            {"device_context": {"location_enabled": 1}},
            {"device_context": {"location_enabled": "true"}},
            {"device_context": {"unknown": True}},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                SettingsPatch.model_validate(payload)

    def test_frozen_v1_device_frames_accept_exact_contract_and_reject_bad_shapes(self) -> None:
        instance_id = INSTANCE_ID
        preferences = {
            "version": 1,
            "type": "device_preferences",
            "request_id": "device-prefs:3",
            "payload": {"instance_id": instance_id, "revision": 3, "location_enabled": True},
        }
        result = {
            "version": 1,
            "type": "device_result",
            "request_id": "device:7",
            "payload": {
                "instance_id": instance_id,
                "revision": 3,
                "outcome": "ok",
                "fix": {"latitude": 10.0, "longitude": 20.0, "observed_at": 1_800_000_000.0},
            },
        }
        state = {
            "version": 1,
            "type": "device_state",
            "request_id": "device-state:2",
            "payload": {"instance_id": instance_id, "revision": 3, "permission": "granted", "availability": "available"},
        }
        request = {
            "version": 1,
            "type": "device_request",
            "request_id": "device:7",
            "payload": {"instance_id": instance_id, "revision": 3},
        }
        for envelope in (preferences, result, state, request):
            with self.subTest(message=envelope["type"]):
                validate_envelope(envelope)
        invalids = (
            {**preferences, "payload": {**preferences["payload"], "location_enabled": 1}},
            {**preferences, "payload": {**preferences["payload"], "extra": False}},
            {**preferences, "request_id": "device-prefs:2"},
            {**request, "request_id": "device:01"},
            {**result, "payload": {**result["payload"], "fix": {**result["payload"]["fix"], "latitude": True}}},
            {**result, "payload": {**result["payload"], "outcome": "denied"}},
            {**result, "payload": {**result["payload"], "outcome": []}},
            {**result, "payload": {**result["payload"], "fix": {**result["payload"]["fix"], "observed_at": 10 ** 400}}},
            {**result, "payload": {**result["payload"], "revision": 2 ** 64}},
            {**state, "payload": {**state["payload"], "permission": "granted" , "extra": "private"}},
            {**state, "payload": {**state["payload"], "permission": {"granted": True}}},
        )
        for envelope in invalids:
            with self.subTest(envelope=envelope), self.assertRaises(ControlProtocolError):
                validate_envelope(envelope)
