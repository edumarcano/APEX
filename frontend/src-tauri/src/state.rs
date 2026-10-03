use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter};

pub const EVENT_NAME: &str = "desktop-backend-state";

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Phase {
    Starting,
    Ready,
    Failed,
    Stopping,
    Stopped,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct RuntimeIdentity {
    pub app_id: String,
    pub app_version: String,
    pub build_id: String,
    pub instance_id: String,
    pub pid: u32,
    pub hosting_mode: String,
    pub launch_id: Option<String>,
    pub data_root_fingerprint: String,
    pub shutdown_timeout_seconds: u32,
}

impl RuntimeIdentity {
    pub fn validate(
        &self,
        launch_id: &str,
        expected_build: &str,
        process_id: u32,
    ) -> Result<(), &'static str> {
        let fingerprint_ok = self.data_root_fingerprint.len() == 64
            && self
                .data_root_fingerprint
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase());
        if self.app_id != "apex"
            || self.app_version != env!("CARGO_PKG_VERSION")
            || self.build_id != expected_build
            || self.hosting_mode != "managed"
            || self.launch_id.as_deref() != Some(launch_id)
            || self.pid != process_id
            || !(1..=3600).contains(&self.shutdown_timeout_seconds)
            || !fingerprint_ok
            || uuid::Uuid::parse_str(&self.instance_id).is_err()
        {
            return Err("identity_mismatch");
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct BackendStatus {
    pub revision: u64,
    pub generation: u64,
    pub phase: Phase,
    pub error_code: Option<String>,
    pub runtime: Option<RuntimeIdentity>,
}

pub fn coalesce_retry(observed_generation: u64, current: &BackendStatus, quitting: bool) -> bool {
    quitting || current.generation != observed_generation
}

impl Default for BackendStatus {
    fn default() -> Self {
        Self {
            revision: 0,
            generation: 0,
            phase: Phase::Starting,
            error_code: None,
            runtime: None,
        }
    }
}

#[derive(Clone)]
pub struct DesktopState(pub Arc<Mutex<BackendStatus>>);

impl DesktopState {
    pub fn new() -> Self {
        Self(Arc::new(Mutex::new(BackendStatus::default())))
    }
    pub fn snapshot(&self) -> BackendStatus {
        self.0.lock().expect("desktop state mutex poisoned").clone()
    }
    pub fn transition(
        &self,
        app: &AppHandle,
        generation: u64,
        phase: Phase,
        error_code: Option<&str>,
        runtime: Option<RuntimeIdentity>,
    ) -> BackendStatus {
        let snapshot = {
            let mut status = self.0.lock().expect("desktop state mutex poisoned");
            apply_transition(&mut status, generation, phase, error_code, runtime)
        };
        let _ = app.emit(EVENT_NAME, &snapshot);
        snapshot
    }
}

fn apply_transition(
    status: &mut BackendStatus,
    generation: u64,
    phase: Phase,
    error_code: Option<&str>,
    runtime: Option<RuntimeIdentity>,
) -> BackendStatus {
    if generation < status.generation {
        return status.clone();
    }
    status.generation = generation;
    status.revision += 1;
    status.phase = phase;
    status.error_code = error_code.map(str::to_owned);
    status.runtime = runtime;
    status.clone()
}

pub fn safe_error_code(code: &str) -> &'static str {
    match code {
        "startup_failed" | "port_in_use" | "profile_in_use" | "protocol_error"
        | "shutdown_timeout" | "shutdown_failed" | "child_failed" | "internal_error"
        | "resource_missing" | "startup_timeout" | "identity_mismatch" | "cors_rejected"
        | "backend_crashed" => match code {
            "startup_failed" => "startup_failed",
            "port_in_use" => "port_in_use",
            "profile_in_use" => "profile_in_use",
            "protocol_error" => "protocol_error",
            "shutdown_timeout" => "shutdown_timeout",
            "shutdown_failed" => "shutdown_failed",
            "child_failed" => "child_failed",
            "resource_missing" => "resource_missing",
            "startup_timeout" => "startup_timeout",
            "identity_mismatch" => "identity_mismatch",
            "cors_rejected" => "cors_rejected",
            "backend_crashed" => "backend_crashed",
            _ => "internal_error",
        },
        _ => "internal_error",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn status_serializes_exact_public_fields() {
        let status = serde_json::to_value(BackendStatus::default()).unwrap();
        let mut keys = status
            .as_object()
            .unwrap()
            .keys()
            .cloned()
            .collect::<Vec<_>>();
        keys.sort();
        assert_eq!(
            keys,
            ["error_code", "generation", "phase", "revision", "runtime"]
        );
        assert_eq!(status["phase"], "starting");
    }
    #[test]
    fn raw_backend_errors_are_never_forwarded() {
        assert_eq!(
            safe_error_code("C:\\Users\\private\\secret"),
            "internal_error"
        );
        assert_eq!(safe_error_code("port_in_use"), "port_in_use");
    }

    #[test]
    fn stale_generations_do_not_overwrite_a_newer_snapshot() {
        let mut state = BackendStatus::default();
        apply_transition(&mut state, 4, Phase::Ready, None, None);
        let current = apply_transition(&mut state, 3, Phase::Failed, Some("port_in_use"), None);
        assert_eq!(current.generation, 4);
        assert_eq!(current.revision, 1);
        assert_eq!(current.phase, Phase::Ready);
    }

    #[test]
    fn retries_queued_behind_an_attempt_return_its_authoritative_snapshot() {
        let mut status = BackendStatus::default();
        apply_transition(&mut status, 1, Phase::Failed, Some("startup_failed"), None);
        assert!(coalesce_retry(0, &status, false));
        assert!(coalesce_retry(1, &status, true));
        assert!(!coalesce_retry(1, &status, false));
    }

    #[test]
    fn runtime_identity_requires_the_managed_child_and_expected_build() {
        let identity = RuntimeIdentity {
            app_id: "apex".into(),
            app_version: env!("CARGO_PKG_VERSION").into(),
            build_id: "test-build".into(),
            instance_id: "581aeb4b-e90e-40d5-9708-1b1fb857fa26".into(),
            pid: 42,
            hosting_mode: "managed".into(),
            launch_id: Some("c60148ac-46b0-4c28-a717-8e2e48c2548b".into()),
            data_root_fingerprint: "a".repeat(64),
            shutdown_timeout_seconds: 60,
        };
        assert!(identity
            .validate("c60148ac-46b0-4c28-a717-8e2e48c2548b", "test-build", 42)
            .is_ok());
        assert_eq!(
            identity.validate("c60148ac-46b0-4c28-a717-8e2e48c2548b", "other", 42),
            Err("identity_mismatch")
        );
        assert_eq!(
            identity.validate("c60148ac-46b0-4c28-a717-8e2e48c2548b", "test-build", 43),
            Err("identity_mismatch")
        );
    }
}
