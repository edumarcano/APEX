use serde::{Deserialize, Serialize};
use std::{
    collections::HashSet,
    sync::{Arc, Mutex},
};
use tauri::{AppHandle, Emitter};

pub const EVENT_NAME: &str = "desktop-services-state";

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum NotificationSetting {
    Enabled,
    DisabledApp,
    DisabledUser,
    DisabledPolicy,
    DisabledManifest,
    Unavailable,
    Unknown,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DesktopServicesStatus {
    pub revision: u64,
    pub generation: u64,
    pub preferences_ready: bool,
    pub requested: RequestedPreferences,
    pub tray_available: bool,
    pub startup: StartupStatus,
    pub notifications: NotificationStatus,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct RequestedPreferences {
    pub launch_on_startup: bool,
    pub completion_notifications: bool,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct StartupStatus {
    pub actual_enabled: Option<bool>,
    pub error_code: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct NotificationStatus {
    pub os_setting: NotificationSetting,
    pub error_code: Option<String>,
}

impl Default for NotificationStatus {
    fn default() -> Self {
        Self {
            os_setting: NotificationSetting::Unknown,
            error_code: None,
        }
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct PreferencesFrame {
    pub instance_id: String,
    pub launch_on_startup: bool,
    pub completion_notifications: bool,
}

#[derive(Clone)]
pub struct DesktopServicesState {
    status: Arc<Mutex<DesktopServicesStatus>>,
    seen_completions: Arc<Mutex<HashSet<(String, String)>>>,
    pub reconcile_lock: Arc<tokio::sync::Mutex<()>>,
    sequence: Arc<Mutex<u64>>,
}

impl DesktopServicesState {
    pub fn new(tray_available: bool, autostart_supported: bool) -> Self {
        Self {
            status: Arc::new(Mutex::new(DesktopServicesStatus {
                revision: 0,
                generation: 0,
                preferences_ready: false,
                requested: RequestedPreferences::default(),
                tray_available,
                startup: StartupStatus {
                    actual_enabled: None,
                    error_code: if autostart_supported {
                        None
                    } else {
                        Some("unsupported".into())
                    },
                },
                notifications: NotificationStatus::default(),
            })),
            seen_completions: Arc::new(Mutex::new(HashSet::new())),
            reconcile_lock: Arc::new(tokio::sync::Mutex::new(())),
            sequence: Arc::new(Mutex::new(0)),
        }
    }

    pub fn snapshot(&self) -> DesktopServicesStatus {
        self.status
            .lock()
            .expect("desktop services mutex poisoned")
            .clone()
    }

    pub fn set_generation(&self, generation: u64) {
        *self
            .sequence
            .lock()
            .expect("desktop service sequence mutex poisoned") = 0;
        let mut status = self.status.lock().expect("desktop services mutex poisoned");
        status.generation = generation;
        status.preferences_ready = false;
        status.requested = RequestedPreferences::default();
        status.revision = status.revision.saturating_add(1);
    }

    pub fn accept_preferences(
        &self,
        request_id: &str,
        payload: serde_json::Value,
        current_instance: &str,
    ) -> Result<DesktopServicesStatus, &'static str> {
        let seq = request_id
            .strip_prefix("desktop:")
            .ok_or("protocol_error")?
            .parse::<u64>()
            .map_err(|_| "protocol_error")?;
        if seq == 0 {
            return Err("protocol_error");
        }
        let preferences: PreferencesFrame =
            serde_json::from_value(payload).map_err(|_| "protocol_error")?;
        if uuid::Uuid::parse_str(&preferences.instance_id).is_err()
            || preferences.instance_id != current_instance
        {
            return Err("identity_mismatch");
        }
        let mut last = self
            .sequence
            .lock()
            .expect("desktop service sequence mutex poisoned");
        if seq <= *last {
            return Err("protocol_error");
        }
        *last = seq;
        let mut status = self.status.lock().expect("desktop services mutex poisoned");
        status.preferences_ready = true;
        status.requested = RequestedPreferences {
            launch_on_startup: preferences.launch_on_startup,
            completion_notifications: preferences.completion_notifications,
        };
        status.revision = status.revision.saturating_add(1);
        Ok(status.clone())
    }

    pub fn publish(&self, app: &AppHandle) {
        let _ = app.emit(EVENT_NAME, self.snapshot());
    }

    pub fn take_completion(&self, instance_id: &str, run_id: &str, current_instance: &str) -> bool {
        if instance_id != current_instance || uuid::Uuid::parse_str(run_id).is_err() {
            return false;
        }
        self.seen_completions
            .lock()
            .expect("desktop completion set poisoned")
            .insert((instance_id.to_owned(), run_id.to_owned()))
    }

    pub fn should_submit_notification(&self) -> bool {
        let status = self.status.lock().expect("desktop services mutex poisoned");
        status.preferences_ready
            && status.requested.completion_notifications
            && status.notifications.os_setting == NotificationSetting::Enabled
    }

    pub fn set_startup(&self, actual: Option<bool>, error: Option<&str>) {
        let mut status = self.status.lock().expect("desktop services mutex poisoned");
        status.startup = StartupStatus {
            actual_enabled: actual,
            error_code: error.map(str::to_owned),
        };
        status.revision = status.revision.saturating_add(1);
    }

    pub fn set_notifications(&self, setting: NotificationSetting, error: Option<&str>) {
        let mut status = self.status.lock().expect("desktop services mutex poisoned");
        status.notifications = NotificationStatus {
            os_setting: setting,
            error_code: error.map(str::to_owned),
        };
        status.revision = status.revision.saturating_add(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const INSTANCE: &str = "581aeb4b-e90e-40d5-9708-1b1fb857fa26";
    const RUN: &str = "c60148ac-46b0-4c28-a717-8e2e48c2548b";

    #[test]
    fn preference_protocol_requires_exact_shape_identity_and_increasing_sequence() {
        let state = DesktopServicesState::new(true, true);
        assert!(!state.snapshot().preferences_ready);
        let payload = json!({"instance_id":INSTANCE,"launch_on_startup":true,"completion_notifications":false});
        assert_eq!(
            state.accept_preferences("desktop:0", payload.clone(), INSTANCE),
            Err("protocol_error")
        );
        assert_eq!(state.accept_preferences("desktop:1", json!({"instance_id":INSTANCE,"launch_on_startup":true,"completion_notifications":false,"extra":1}), INSTANCE), Err("protocol_error"));
        assert_eq!(
            state.accept_preferences("desktop:1", payload.clone(), RUN),
            Err("identity_mismatch")
        );
        let accepted = state
            .accept_preferences("desktop:1", payload.clone(), INSTANCE)
            .unwrap();
        assert!(accepted.preferences_ready);
        assert!(accepted.requested.launch_on_startup);
        assert_eq!(accepted.startup.actual_enabled, None);
        assert_eq!(
            state.accept_preferences("desktop:1", payload, INSTANCE),
            Err("protocol_error")
        );
    }

    #[test]
    fn public_status_serializes_the_fixed_services_contract() {
        let status = DesktopServicesState::new(true, true).snapshot();
        let value = serde_json::to_value(status).unwrap();
        let mut keys = value
            .as_object()
            .unwrap()
            .keys()
            .cloned()
            .collect::<Vec<_>>();
        keys.sort();
        assert_eq!(
            keys,
            [
                "generation",
                "notifications",
                "preferences_ready",
                "requested",
                "revision",
                "startup",
                "tray_available"
            ]
        );
        assert_eq!(
            value["requested"],
            serde_json::json!({"launch_on_startup":false,"completion_notifications":false})
        );
        assert_eq!(value["startup"]["actual_enabled"], serde_json::Value::Null);
    }

    #[test]
    fn completion_dedupe_records_suppressed_events_and_checks_instance() {
        let state = DesktopServicesState::new(true, true);
        assert!(!state.take_completion(INSTANCE, RUN, RUN));
        assert!(state.take_completion(INSTANCE, RUN, INSTANCE));
        assert!(!state.take_completion(INSTANCE, RUN, INSTANCE));
    }

    #[test]
    fn failed_service_reconciliation_preserves_requested_and_actual_mismatch() {
        let state = DesktopServicesState::new(true, true);
        let requested = json!({"instance_id":INSTANCE,"launch_on_startup":true,"completion_notifications":true});
        state
            .accept_preferences("desktop:1", requested, INSTANCE)
            .unwrap();
        state.set_startup(Some(false), Some("autostart_failed"));
        let snapshot = state.snapshot();
        assert!(snapshot.requested.launch_on_startup);
        assert_eq!(snapshot.startup.actual_enabled, Some(false));
        assert_eq!(
            snapshot.startup.error_code.as_deref(),
            Some("autostart_failed")
        );
    }

    #[test]
    fn notification_requires_committed_preference_and_enabled_os_setting() {
        let state = DesktopServicesState::new(true, true);
        assert!(!state.should_submit_notification());
        state.accept_preferences(
            "desktop:1",
            json!({"instance_id":INSTANCE,"launch_on_startup":false,"completion_notifications":true}),
            INSTANCE,
        ).unwrap();
        assert!(!state.should_submit_notification());
        state.set_notifications(NotificationSetting::DisabledUser, None);
        assert!(!state.should_submit_notification());
        state.set_notifications(NotificationSetting::Enabled, None);
        assert!(state.should_submit_notification());
    }
}
