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

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NotificationSettingProbe {
    Known(NotificationSetting),
    IdentityNotFound,
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
    notification_identity_missing: Arc<Mutex<bool>>,
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
            notification_identity_missing: Arc::new(Mutex::new(false)),
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
        *self
            .notification_identity_missing
            .lock()
            .expect("notification probe mutex poisoned") = false;
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
            && (status.notifications.os_setting == NotificationSetting::Enabled
                || (status.notifications.os_setting == NotificationSetting::Unknown
                    && *self
                        .notification_identity_missing
                        .lock()
                        .expect("notification probe mutex poisoned")))
    }

    pub fn record_completion_eligibility(
        &self,
        instance_id: &str,
        run_id: &str,
        current_instance: &str,
        completed: bool,
        hidden_or_minimized: bool,
    ) -> bool {
        let unique = self.take_completion(instance_id, run_id, current_instance);
        unique && completed && hidden_or_minimized && self.should_submit_notification()
    }

    #[cfg_attr(debug_assertions, allow(dead_code))]
    pub fn set_startup(&self, actual: Option<bool>, error: Option<&str>) {
        let mut status = self.status.lock().expect("desktop services mutex poisoned");
        status.startup = StartupStatus {
            actual_enabled: actual,
            error_code: error.map(str::to_owned),
        };
        status.revision = status.revision.saturating_add(1);
    }

    pub fn refresh_startup(&self, actual: Option<bool>, error: Option<&str>) {
        let mut status = self.status.lock().expect("desktop services mutex poisoned");
        let mut changed = status.startup.actual_enabled != actual;
        status.startup.actual_enabled = actual;
        if status.startup.error_code.is_none() {
            if let Some(error) = error {
                status.startup.error_code = Some(error.to_owned());
                changed = true;
            }
        }
        if changed {
            status.revision = status.revision.saturating_add(1);
        }
    }

    pub fn set_notifications(&self, setting: NotificationSetting, error: Option<&str>) {
        self.set_notification_probe(NotificationSettingProbe::Known(setting), error);
    }

    pub fn set_notification_error(&self, error: &str) {
        let mut status = self.status.lock().expect("desktop services mutex poisoned");
        *self
            .notification_identity_missing
            .lock()
            .expect("notification probe mutex poisoned") = false;
        status.notifications.error_code = Some(error.to_owned());
        status.revision = status.revision.saturating_add(1);
    }

    pub fn set_notification_probe(&self, probe: NotificationSettingProbe, error: Option<&str>) {
        let (setting, identity_missing) = notification_probe_status(probe);
        let mut status = self.status.lock().expect("desktop services mutex poisoned");
        *self
            .notification_identity_missing
            .lock()
            .expect("notification probe mutex poisoned") = identity_missing;
        status.notifications = NotificationStatus {
            os_setting: setting,
            error_code: error.map(str::to_owned),
        };
        status.revision = status.revision.saturating_add(1);
    }

    pub fn refresh_notifications(&self, setting: NotificationSetting, error: Option<&str>) {
        self.refresh_notification_probe(NotificationSettingProbe::Known(setting), error);
    }

    pub fn refresh_notification_probe(&self, probe: NotificationSettingProbe, error: Option<&str>) {
        let (setting, identity_missing) = notification_probe_status(probe);
        let mut status = self.status.lock().expect("desktop services mutex poisoned");
        *self
            .notification_identity_missing
            .lock()
            .expect("notification probe mutex poisoned") = identity_missing;
        let mut changed = status.notifications.os_setting != setting;
        status.notifications.os_setting = setting;
        if identity_missing {
            if status.notifications.error_code.is_none() {
                status.notifications.error_code = error.map(str::to_owned);
                changed |= status.notifications.error_code.is_some();
            }
        } else if status.notifications.error_code.as_deref()
            == Some("notification_identity_unregistered")
        {
            status.notifications.error_code = None;
            changed = true;
        } else if status.notifications.error_code.is_none() {
            if let Some(error) = error {
                status.notifications.error_code = Some(error.to_owned());
                changed = true;
            }
        }
        if changed {
            status.revision = status.revision.saturating_add(1);
        }
    }
}

fn notification_probe_status(probe: NotificationSettingProbe) -> (NotificationSetting, bool) {
    match probe {
        NotificationSettingProbe::Known(setting) => (setting, false),
        NotificationSettingProbe::IdentityNotFound => (NotificationSetting::Unknown, true),
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
    fn read_only_status_refresh_preserves_last_operation_errors() {
        let state = DesktopServicesState::new(true, true);
        state.set_startup(Some(false), Some("autostart_failed"));
        state.set_notifications(NotificationSetting::Unknown, Some("notification_failed"));
        state.refresh_startup(Some(true), None);
        state.refresh_notifications(NotificationSetting::DisabledUser, None);
        let snapshot = state.snapshot();
        assert_eq!(snapshot.startup.actual_enabled, Some(true));
        assert_eq!(
            snapshot.startup.error_code.as_deref(),
            Some("autostart_failed")
        );
        assert_eq!(
            snapshot.notifications.os_setting,
            NotificationSetting::DisabledUser
        );
        assert_eq!(
            snapshot.notifications.error_code.as_deref(),
            Some("notification_failed")
        );
        let revision = snapshot.revision;
        state.refresh_startup(Some(true), Some("autostart_read_failed"));
        state.refresh_notifications(
            NotificationSetting::DisabledUser,
            Some("notification_unavailable"),
        );
        assert_eq!(state.snapshot().revision, revision);
        state.set_startup(Some(true), None);
        state.set_notifications(NotificationSetting::Enabled, None);
        let retried = state.snapshot();
        assert_eq!(retried.startup.error_code, None);
        assert_eq!(retried.notifications.error_code, None);
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

    #[test]
    fn only_missing_identity_allows_the_first_opted_in_submission() {
        let state = DesktopServicesState::new(true, true);
        state
            .accept_preferences(
                "desktop:1",
                json!({"instance_id":INSTANCE,"launch_on_startup":false,"completion_notifications":true}),
                INSTANCE,
            )
            .unwrap();
        state.set_notification_probe(
            NotificationSettingProbe::IdentityNotFound,
            Some("notification_identity_unregistered"),
        );
        assert!(state.should_submit_notification());
        state.set_notification_error("notification_failed");
        assert!(!state.should_submit_notification());
        state.set_notification_probe(
            NotificationSettingProbe::IdentityNotFound,
            Some("notification_identity_unregistered"),
        );
        let first_submission_status = state.snapshot().notifications;
        assert_eq!(
            first_submission_status.os_setting,
            NotificationSetting::Unknown
        );
        assert_eq!(
            first_submission_status.error_code.as_deref(),
            Some("notification_identity_unregistered")
        );

        for setting in [
            NotificationSetting::Unknown,
            NotificationSetting::DisabledApp,
            NotificationSetting::DisabledUser,
            NotificationSetting::DisabledPolicy,
            NotificationSetting::DisabledManifest,
            NotificationSetting::Unavailable,
        ] {
            state.set_notifications(setting, None);
            assert!(!state.should_submit_notification());
        }

        state.set_notification_probe(
            NotificationSettingProbe::IdentityNotFound,
            Some("notification_identity_unregistered"),
        );
        state.refresh_notification_probe(
            NotificationSettingProbe::Known(NotificationSetting::Enabled),
            None,
        );
        assert_eq!(
            state.snapshot().notifications.os_setting,
            NotificationSetting::Enabled
        );
        assert_eq!(state.snapshot().notifications.error_code, None);
        assert!(state.should_submit_notification());
    }

    #[test]
    fn new_generation_cannot_reuse_the_previous_generation_missing_identity_probe() {
        let state = DesktopServicesState::new(true, true);
        let opted_in = json!({"instance_id":INSTANCE,"launch_on_startup":false,"completion_notifications":true});
        state
            .accept_preferences("desktop:1", opted_in.clone(), INSTANCE)
            .unwrap();
        state.set_notification_probe(
            NotificationSettingProbe::IdentityNotFound,
            Some("notification_identity_unregistered"),
        );
        assert!(state.should_submit_notification());

        state.set_generation(2);
        state
            .accept_preferences("desktop:1", opted_in, INSTANCE)
            .unwrap();
        assert!(!state.should_submit_notification());

        state.set_notification_probe(
            NotificationSettingProbe::IdentityNotFound,
            Some("notification_identity_unregistered"),
        );
        assert!(state.should_submit_notification());
    }

    #[test]
    fn receipt_eligibility_is_not_recomputed_after_a_disabled_run_was_suppressed() {
        let state = DesktopServicesState::new(true, true);
        state
            .accept_preferences(
                "desktop:1",
                json!({"instance_id":INSTANCE,"launch_on_startup":false,"completion_notifications":false}),
                INSTANCE,
            )
            .unwrap();
        state.set_notifications(NotificationSetting::Enabled, None);
        assert!(!state.record_completion_eligibility(INSTANCE, RUN, INSTANCE, true, true));
        state
            .accept_preferences(
                "desktop:2",
                json!({"instance_id":INSTANCE,"launch_on_startup":false,"completion_notifications":true}),
                INSTANCE,
            )
            .unwrap();
        assert!(!state.record_completion_eligibility(INSTANCE, RUN, INSTANCE, true, true));
        let second = "651aeb4b-e90e-40d5-9708-1b1fb857fa27";
        assert!(state.record_completion_eligibility(INSTANCE, second, INSTANCE, true, true));
        let third = "751aeb4b-e90e-40d5-9708-1b1fb857fa28";
        assert!(state.record_completion_eligibility(INSTANCE, third, INSTANCE, true, true));
    }
}
