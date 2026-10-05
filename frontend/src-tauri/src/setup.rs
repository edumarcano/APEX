use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter};

pub const EVENT_NAME: &str = "desktop-setup-state";
pub const MAX_FRAME_BYTES: usize = 64 * 1024;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    Checking,
    ChoiceRequired,
    PreviewReady,
    Importing,
    Ready,
    RecoveryRequired,
    Failed,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Progress {
    pub stage: String,
    pub completed_bytes: u64,
    pub total_bytes: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ImportItem {
    pub path: String,
    pub category: String,
    pub disposition: Disposition,
    pub file_count: u64,
    pub total_bytes: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Disposition {
    Copy,
    Missing,
    RetainExternal,
    Reuse,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ImportPreview {
    pub preview_id: String,
    pub can_import: bool,
    pub items: Vec<ImportItem>,
    pub warnings: Vec<String>,
    pub blockers: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DesktopSetupState {
    pub revision: u64,
    pub phase: Phase,
    pub preview: Option<ImportPreview>,
    pub progress: Option<Progress>,
    pub error_code: Option<String>,
}

impl Default for DesktopSetupState {
    fn default() -> Self {
        Self {
            revision: 0,
            phase: Phase::Checking,
            preview: None,
            progress: None,
            error_code: None,
        }
    }
}

#[derive(Clone, Default)]
pub struct SetupState(Arc<Mutex<DesktopSetupState>>);

#[derive(Clone, Default)]
pub struct SetupController(Arc<Mutex<Option<std::path::PathBuf>>>);

impl SetupController {
    pub fn select_source(&self, source: Option<std::path::PathBuf>) {
        *self.0.lock().expect("setup source mutex poisoned") = source;
    }

    pub fn source(&self) -> Option<std::path::PathBuf> {
        self.0.lock().expect("setup source mutex poisoned").clone()
    }
}

pub fn preview_can_commit(
    state: &DesktopSetupState,
    source: Option<&std::path::Path>,
    preview_id: &str,
) -> bool {
    state.phase == Phase::PreviewReady
        && state
            .preview
            .as_ref()
            .is_some_and(|preview| preview.can_import && preview.preview_id == preview_id)
        && source.is_some_and(|source| source.is_absolute())
}

impl SetupState {
    pub fn snapshot(&self) -> DesktopSetupState {
        self.0.lock().expect("setup state mutex poisoned").clone()
    }

    pub fn transition(
        &self,
        app: &AppHandle,
        phase: Phase,
        preview: Option<ImportPreview>,
        progress: Option<Progress>,
        error_code: Option<&str>,
    ) -> DesktopSetupState {
        let snapshot = {
            let mut state = self.0.lock().expect("setup state mutex poisoned");
            apply_transition(&mut state, phase, preview, progress, error_code)
        };
        let _ = app.emit(EVENT_NAME, ());
        snapshot
    }
}

fn apply_transition(
    state: &mut DesktopSetupState,
    phase: Phase,
    preview: Option<ImportPreview>,
    progress: Option<Progress>,
    error_code: Option<&str>,
) -> DesktopSetupState {
    state.revision = state.revision.saturating_add(1);
    state.phase = phase;
    state.preview = preview;
    state.progress = progress;
    state.error_code = error_code.map(safe_error_code).map(str::to_owned);
    state.clone()
}

const ERROR_CODES: &[&str] = &[
    "request_invalid",
    "response_too_large",
    "internal_error",
    "source_invalid",
    "source_active",
    "source_activity_uncertain",
    "source_busy_or_unreadable",
    "source_recovery_required",
    "source_changed",
    "source_database_missing",
    "source_database_unavailable",
    "source_inventory_unavailable",
    "source_inventory_too_large",
    "source_reparse_point",
    "path_reparse_point",
    "destination_active",
    "destination_database_exists",
    "destination_path_exists",
    "destination_setup_marker_exists",
    "import_blocked",
    "preview_stale",
    "import_recovery_required",
    "import_journal_invalid",
    "import_recovery_unproven",
    "database_integrity_failed",
    "database_foreign_key_check_failed",
    "database_schema_invalid",
    "retrieval_schema_unsupported",
    "setup_marker_invalid",
    "invalid_source",
    "stale_preview",
    "recovery_required",
    "helper_unavailable",
    "helper_protocol_error",
    "import_failed",
    "setup_failed",
];

const PREVIEW_NOTICE_CODES: &[&str] = &[
    "source_database_missing",
    "source_database_incompatible",
    "destination_database_exists",
    "destination_path_exists",
    "destination_setup_marker_exists",
    "source_active",
    "source_activity_uncertain",
    "source_busy_or_unreadable",
    "source_recovery_required",
    "retrieval_schema_unsupported",
    "microsoft_cache_path_needs_review",
    "external_path_needs_review",
    "relative_credential_path_needs_review",
    "configuration_needs_review",
];

const ITEM_CATEGORIES: &[&str] = &[
    "database",
    "configuration",
    "credentials",
    "cache",
    "managed_weights",
];

pub fn safe_error_code(code: &str) -> &'static str {
    ERROR_CODES
        .iter()
        .copied()
        .find(|allowed| *allowed == code)
        .unwrap_or("setup_failed")
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Frame {
    pub version: u8,
    pub request_id: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub payload: serde_json::Value,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SetupResult {
    pub phase: HelperPhase,
    pub error_code: Option<String>,
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum HelperPhase {
    ChoiceRequired,
    Ready,
    RecoveryRequired,
}

pub fn parse_frame(bytes: &[u8], request_id: &str) -> Result<Frame, &'static str> {
    if bytes.len() > MAX_FRAME_BYTES
        || !bytes.ends_with(b"\n")
        || bytes[..bytes.len() - 1].contains(&b'\n')
        || bytes.contains(&b'\r')
    {
        return Err("helper_protocol_error");
    }
    let frame: Frame =
        serde_json::from_slice(&bytes[..bytes.len() - 1]).map_err(|_| "helper_protocol_error")?;
    if frame.version != 1 || frame.request_id != request_id || !frame.payload.is_object() {
        return Err("helper_protocol_error");
    }
    match frame.kind.as_str() {
        "progress" => {
            let progress: Progress = serde_json::from_value(frame.payload.clone())
                .map_err(|_| "helper_protocol_error")?;
            if progress.stage.is_empty()
                || progress.stage.len() > 64
                || !progress
                    .stage
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b == b'_')
                || progress.completed_bytes > progress.total_bytes
            {
                return Err("helper_protocol_error");
            }
        }
        "result" => {}
        "error" => {
            let payload = frame.payload.as_object().ok_or("helper_protocol_error")?;
            if payload.len() != 1 || payload.get("code").and_then(|v| v.as_str()).is_none() {
                return Err("helper_protocol_error");
            }
        }
        _ => return Err("helper_protocol_error"),
    }
    Ok(frame)
}

pub fn parse_preview(value: serde_json::Value) -> Result<ImportPreview, &'static str> {
    let preview: ImportPreview =
        serde_json::from_value(value).map_err(|_| "helper_protocol_error")?;
    if (preview.can_import && preview.preview_id.is_empty())
        || preview.preview_id.len() > 256
        || (!preview.preview_id.is_empty()
            && (preview.preview_id.len() != 64
                || !preview
                    .preview_id
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))))
        || !preview
            .preview_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-".contains(&byte))
        || preview.items.len() > 256
        || preview.warnings.len() > 64
        || preview.blockers.len() > 64
        || preview.items.iter().any(|item| {
            item.path.len() > 1024 || !ITEM_CATEGORIES.contains(&item.category.as_str())
        })
        || preview.items.iter().any(|item| {
            item.path.starts_with(['/', '\\'])
                || item.path.contains(':')
                || item.path.split(['/', '\\']).any(|segment| segment == "..")
                || item.path.chars().any(char::is_control)
        })
        || preview
            .warnings
            .iter()
            .chain(&preview.blockers)
            .any(|text| text.len() > 512 || !PREVIEW_NOTICE_CODES.contains(&text.as_str()))
    {
        return Err("helper_protocol_error");
    }
    Ok(preview)
}

pub fn parse_result(value: serde_json::Value) -> Result<SetupResult, &'static str> {
    serde_json::from_value(value).map_err(|_| "helper_protocol_error")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame(kind: &str, request: &str, payload: &str) -> Vec<u8> {
        let mut bytes = format!(
            r#"{{"version":1,"request_id":"{request}","type":"{kind}","payload":{payload}}}"#
        )
        .into_bytes();
        bytes.push(b'\n');
        bytes
    }

    #[test]
    fn helper_frames_are_bounded_strict_and_bound_to_the_current_request() {
        let bytes = frame(
            "progress",
            "setup-1",
            r#"{"stage":"copy","completed_bytes":3,"total_bytes":8}"#,
        );
        assert_eq!(parse_frame(&bytes, "setup-1").unwrap().kind, "progress");
        assert_eq!(
            parse_frame(&bytes, "setup-2").unwrap_err(),
            "helper_protocol_error"
        );
        assert!(parse_frame(&vec![b'x'; MAX_FRAME_BYTES + 1], "setup-1").is_err());
        assert!(parse_frame(b"{\"version\":1}\n", "setup-1").is_err());
    }

    #[test]
    fn previews_reject_unbounded_and_unknown_fields() {
        let valid = serde_json::json!({"preview_id":"a".repeat(64),"can_import":true,"items":[],"warnings":[],"blockers":[]});
        assert!(parse_preview(valid).is_ok());
        let valid_item = serde_json::json!({"preview_id":"a".repeat(64),"can_import":true,"items":[{"path":"database/apex.db","category":"database","disposition":"copy","file_count":1,"total_bytes":12}],"warnings":[],"blockers":[]});
        assert!(parse_preview(valid_item).is_ok());
        let blocked_without_id = serde_json::json!({"preview_id":"","can_import":false,"items":[],"warnings":[],"blockers":["source_active"]});
        assert!(parse_preview(blocked_without_id).is_ok());
        let extra = serde_json::json!({"preview_id":"a".repeat(64),"can_import":true,"items":[],"warnings":[],"blockers":[],"source":"C:\\secret"});
        assert_eq!(parse_preview(extra).unwrap_err(), "helper_protocol_error");
        let invalid_item = serde_json::json!({"preview_id":"a".repeat(64),"can_import":true,"items":[{"path":"x","category":"database","disposition":"remove","file_count":0,"total_bytes":0}],"warnings":[],"blockers":[]});
        assert!(parse_preview(invalid_item).is_err());
    }

    #[test]
    fn unknown_helper_errors_are_sanitized() {
        assert_eq!(safe_error_code(r#"C:\Users\person\source"#), "setup_failed");
        assert_eq!(safe_error_code("stale_preview"), "stale_preview");
        assert_eq!(
            safe_error_code("database_schema_invalid"),
            "database_schema_invalid"
        );
        assert_eq!(safe_error_code("unknown_token"), "setup_failed");
        let error = frame("error", "setup-3", r#"{"code":"C:\\private"}"#);
        let parsed = parse_frame(&error, "setup-3").unwrap();
        assert_eq!(
            safe_error_code(parsed.payload["code"].as_str().unwrap()),
            "setup_failed"
        );
        let malformed = frame(
            "error",
            "setup-3",
            r#"{"code":"request_invalid","detail":"C:\\private"}"#,
        );
        assert_eq!(
            parse_frame(&malformed, "setup-3").unwrap_err(),
            "helper_protocol_error"
        );
    }

    #[test]
    fn commit_requires_the_current_preview_and_cached_absolute_source() {
        let state = DesktopSetupState {
            revision: 1,
            phase: Phase::PreviewReady,
            preview: Some(ImportPreview {
                preview_id: "current".into(),
                can_import: true,
                items: vec![],
                warnings: vec![],
                blockers: vec![],
            }),
            progress: None,
            error_code: None,
        };
        let source = std::path::Path::new("C:\\source");
        assert!(preview_can_commit(&state, Some(source), "current"));
        assert!(!preview_can_commit(&state, Some(source), "stale"));
        assert!(!preview_can_commit(&state, None, "current"));
        assert!(!preview_can_commit(
            &state,
            Some(std::path::Path::new("relative")),
            "current"
        ));
    }

    #[test]
    fn setup_snapshots_advance_revisions_and_sanitize_failures() {
        let mut state = DesktopSetupState::default();
        let preview = ImportPreview {
            preview_id: "p1".into(),
            can_import: true,
            items: vec![],
            warnings: vec![],
            blockers: vec![],
        };
        let ready = apply_transition(&mut state, Phase::PreviewReady, Some(preview), None, None);
        assert_eq!(ready.revision, 1);
        assert_eq!(ready.phase, Phase::PreviewReady);
        assert_eq!(ready.preview.unwrap().preview_id, "p1");
        let failed = apply_transition(
            &mut state,
            Phase::Failed,
            None,
            None,
            Some(r#"C:\private\path"#),
        );
        assert_eq!(failed.revision, 2);
        assert_eq!(failed.error_code.as_deref(), Some("setup_failed"));
    }

    #[test]
    fn setup_status_snapshot_reads_are_observational() {
        let state = SetupState::default();
        let first = state.snapshot();
        let second = state.snapshot();
        assert_eq!(first, second);
        assert_eq!(first.revision, 0);
        assert_eq!(first.phase, Phase::Checking);
    }
}
