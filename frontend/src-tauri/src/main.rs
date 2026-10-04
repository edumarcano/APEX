#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod autostart;
mod external;
mod location;
mod notifications;
mod protocol;
mod security;
mod services;
mod state;
mod window_geometry;
#[cfg(windows)]
mod windows_job;

use futures_util::StreamExt;
use serde_json::{json, Value};
use services::{
    DesktopServicesState, DesktopServicesStatus, NotificationSetting, NotificationSettingProbe,
};
use state::{BackendStatus, DesktopState, Phase, RuntimeIdentity};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Duration,
};
use tauri::{Emitter, Manager, State, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_clipboard_manager::ClipboardExt;
use tauri_plugin_opener::OpenerExt;
use tokio::{
    io::{AsyncBufReadExt, AsyncRead, AsyncReadExt, AsyncWriteExt, BufReader},
    sync::{mpsc, Mutex},
    time::{timeout, Instant},
};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

const API_RUNTIME: &str = "http://127.0.0.1:8000/api/v1/runtime";
const API_HEALTH: &str = "http://127.0.0.1:8000/api/v1/health/ready";
const NATIVE_ORIGIN: &str = "http://tauri.localhost";
const STARTUP_LIMIT: Duration = Duration::from_secs(180);
const MAX_HTTP_BYTES: usize = 64 * 1024;
const EXIT_FRAME_GRACE: Duration = Duration::from_millis(250);

enum StartupReceive {
    Frame(Result<protocol::Envelope, &'static str>),
    Closed,
    Exited,
    TimedOut,
}

async fn receive_startup_frame(
    receiver: &mut mpsc::Receiver<Result<protocol::Envelope, &'static str>>,
    wait: Duration,
    child_exited: bool,
) -> StartupReceive {
    match timeout(wait, receiver.recv()).await {
        Ok(Some(frame)) => StartupReceive::Frame(frame),
        Ok(None) => StartupReceive::Closed,
        Err(_) if child_exited => StartupReceive::Exited,
        Err(_) => StartupReceive::TimedOut,
    }
}

fn start_stdout_reader<R>(stdout: R, sender: mpsc::Sender<Result<protocol::Envelope, &'static str>>)
where
    R: AsyncRead + Unpin + Send + 'static,
{
    tauri::async_runtime::spawn(async move {
        let mut reader = BufReader::new(stdout);
        loop {
            let mut bytes = Vec::new();
            let read = (&mut reader)
                .take((protocol::MAX_FRAME_BYTES + 1) as u64)
                .read_until(b'\n', &mut bytes)
                .await;
            match read {
                Ok(0) => {
                    let _ = sender.send(Err("backend_crashed")).await;
                    break;
                }
                Ok(_) => {
                    if bytes.len() > protocol::MAX_FRAME_BYTES {
                        let _ = sender.send(Err("protocol_error")).await;
                        break;
                    }
                    let parsed = protocol::decode(&bytes);
                    if sender.send(parsed).await.is_err() {
                        break;
                    }
                }
                Err(_) => {
                    let _ = sender.send(Err("protocol_error")).await;
                    break;
                }
            }
        }
    });
}

#[cfg(windows)]
type OwnedChild = windows_job::OwnedChild;
#[cfg(windows)]
type ChildInput = windows_job::ChildInput;
#[cfg(not(windows))]
type OwnedChild = Child;
#[cfg(not(windows))]
type ChildInput = tokio::process::ChildStdin;

struct ChildSession {
    child: OwnedChild,
    stdin: ChildInput,
    rx: mpsc::Receiver<Result<protocol::Envelope, &'static str>>,
}
#[derive(Clone)]
struct Supervisor {
    session: Arc<Mutex<Option<ChildSession>>>,
    operation: Arc<Mutex<()>>,
    cancellation: Arc<Mutex<Option<CancellationToken>>>,
    quitting: Arc<AtomicBool>,
}

#[tauri::command]
async fn desktop_services_status(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    services: State<'_, DesktopServicesState>,
) -> Result<DesktopServicesStatus, &'static str> {
    validate_caller(&window)?;
    let generation = app.state::<DesktopState>().snapshot().generation;
    refresh_services_status(app, services.inner().clone(), generation, false).await;
    Ok(services.snapshot())
}

#[tauri::command]
async fn desktop_services_retry(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    services: State<'_, DesktopServicesState>,
) -> Result<DesktopServicesStatus, &'static str> {
    validate_caller(&window)?;
    let generation = app.state::<DesktopState>().snapshot().generation;
    reconcile_services(app, services.inner().clone(), generation, true).await;
    Ok(services.snapshot())
}

#[tauri::command]
fn desktop_open_external(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    url: String,
) -> Result<(), &'static str> {
    validate_caller(&window)?;
    let url = external::validate_external_url(&url)?;
    app.opener()
        .open_url(url.as_str(), None::<&str>)
        .map_err(|_| "open_failed")
}

#[tauri::command]
fn desktop_write_clipboard(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    text: String,
) -> Result<(), &'static str> {
    validate_caller(&window)?;
    if text.len() > 1_048_576 {
        return Err("clipboard_failed");
    }
    app.clipboard()
        .write_text(text)
        .map_err(|_| "clipboard_failed")
}

#[tauri::command]
fn desktop_backend_status(
    window: tauri::WebviewWindow,
    status: State<'_, DesktopState>,
) -> Result<BackendStatus, &'static str> {
    validate_caller(&window)?;
    Ok(status.snapshot())
}

#[tauri::command]
async fn desktop_check_location_permission(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    status: State<'_, DesktopState>,
    location: State<'_, location::LocationState>,
    supervisor: State<'_, Supervisor>,
) -> Result<location::PublicStatus, &'static str> {
    validate_caller(&window)?;
    if !location::foreground_eligible(
        window.is_visible().unwrap_or(false),
        window.is_minimized().unwrap_or(true),
        window.is_focused().unwrap_or(false),
    ) {
        return Err("foreground_required");
    }
    let backend = status.snapshot();
    if backend.phase != Phase::Ready || supervisor.quitting.load(Ordering::Acquire) {
        return Err("backend_unavailable");
    }
    let context = location.context().ok_or("preferences_unavailable")?;
    if context.generation != backend.generation || !context.enabled {
        return Err("location_disabled");
    }
    let permission_check = app.state::<LocationCheckLock>();
    let _permission_check = permission_check.0.lock().await;
    if status.snapshot().generation != context.generation
        || supervisor.quitting.load(Ordering::Acquire)
        || !location.is_current(&context)
        || !location::foreground_eligible(
            window.is_visible().unwrap_or(false),
            window.is_minimized().unwrap_or(true),
            window.is_focused().unwrap_or(false),
        )
    {
        return Err("stale_request");
    }
    let request_cancellation = location.cancellation_token().child_token();
    let result = location::request_access(&window, request_cancellation).await?;
    if !location.is_current(&context)
        || status.snapshot().generation != context.generation
        || supervisor.quitting.load(Ordering::Acquire)
    {
        return Err("stale_request");
    }
    if !location.set_status(&context, result) {
        return Err("stale_request");
    }
    send_location_state(&app, &status, &supervisor, &location, &context).await?;
    let observer = app.state::<location::LocationObserver>();
    if result.permission == location::Permission::Granted {
        observer.observe(app.clone(), context.clone());
    } else {
        observer.remove();
    }
    let _ = app.emit("desktop-device-state", json!({}));
    Ok(result)
}

async fn send_location_state(
    app: &tauri::AppHandle,
    backend: &DesktopState,
    supervisor: &Supervisor,
    location: &location::LocationState,
    context: &location::RequestContext,
) -> Result<(), &'static str> {
    if !location.is_current(context) || backend.snapshot().generation != context.generation {
        return Err("stale_request");
    }
    let mut session = supervisor.session.lock().await;
    if !location.is_current(context) || backend.snapshot().generation != context.generation {
        return Err("stale_request");
    }
    let session = session.as_mut().ok_or("backend_unavailable")?;
    let seq = app.state::<LocationSequence>().next();
    send_device_control(
        &mut session.stdin,
        "device_state",
        format!("device-state:{seq}"),
        json!({
            "instance_id": context.instance_id,
            "revision": context.revision,
            "permission": location.status().permission,
            "availability": location.status().availability,
        }),
    )
    .await
    .map_err(|_| "backend_unavailable")
}

async fn send_device_control(
    stdin: &mut ChildInput,
    kind: &str,
    request_id: String,
    payload: Value,
) -> Result<(), ()> {
    let envelope =
        json!({"version": 1, "type": kind, "request_id": request_id, "payload": payload});
    let mut bytes = serde_json::to_vec(&envelope).map_err(|_| ())?;
    bytes.push(b'\n');
    protocol::decode(&bytes).map_err(|_| ())?;
    let kind = envelope.get("type").and_then(Value::as_str).ok_or(())?;
    let request_id = envelope
        .get("request_id")
        .and_then(Value::as_str)
        .ok_or(())?
        .to_owned();
    let payload = envelope.get("payload").cloned().ok_or(())?;
    send_control(stdin, kind, request_id, payload).await
}

fn accept_location_preferences(
    app: &tauri::AppHandle,
    generation: u64,
    frame: &protocol::Envelope,
    expected_instance: &str,
) -> Result<bool, &'static str> {
    let payload = &frame.payload;
    let instance = payload
        .get("instance_id")
        .and_then(Value::as_str)
        .ok_or("protocol_error")?;
    if instance != expected_instance {
        return Ok(false);
    }
    let revision = payload
        .get("revision")
        .and_then(Value::as_u64)
        .ok_or("protocol_error")?;
    let enabled = payload
        .get("location_enabled")
        .and_then(Value::as_bool)
        .ok_or("protocol_error")?;
    let location = app.state::<location::LocationState>();
    let before = location.context();
    if let Some(before) = &before {
        if before.instance_id != instance {
            return Ok(false);
        }
        if revision == before.revision && enabled != before.enabled {
            return Err("protocol_error");
        }
    }
    if !location.accept_preferences(generation, instance, revision, enabled) {
        return Ok(false);
    }
    let after = location.context();
    Ok(before != after)
}

async fn handle_device_request(
    app: tauri::AppHandle,
    backend: DesktopState,
    supervisor: Supervisor,
    context: location::RequestContext,
    request_id: String,
) {
    let location = app.state::<location::LocationState>().inner().clone();
    let mut read_cancellation = None;
    let result = if !context.enabled {
        Err(location::ReadOutcome::PermissionRequired)
    } else {
        match location.status().permission {
            location::Permission::Unknown => Err(location::ReadOutcome::PermissionRequired),
            location::Permission::Denied => Err(location::ReadOutcome::Denied),
            location::Permission::Revoked => Err(location::ReadOutcome::Revoked),
            location::Permission::Unsupported => Err(location::ReadOutcome::Unsupported),
            location::Permission::Granted => {
                let cancellation = location.cancellation_token().child_token();
                read_cancellation = Some(cancellation.clone());
                location::read_current(cancellation).await
            }
        }
    };
    let result = if location.status().permission == location::Permission::Revoked && result.is_err()
    {
        Err(location::ReadOutcome::Revoked)
    } else {
        result
    };
    if !location.is_current(&context)
        || backend.snapshot().generation != context.generation
        || supervisor.quitting.load(Ordering::Acquire)
        || (result.is_ok()
            && (location.status().permission != location::Permission::Granted
                || read_cancellation
                    .as_ref()
                    .is_some_and(tokio_util::sync::CancellationToken::is_cancelled)))
    {
        return;
    }
    let next_status = match &result {
        Ok(_) => location::PublicStatus {
            permission: location::Permission::Granted,
            availability: location::Availability::Available,
        },
        Err(location::ReadOutcome::PermissionRequired) => location::PublicStatus {
            permission: location::Permission::Unknown,
            availability: location::Availability::Unknown,
        },
        Err(location::ReadOutcome::Denied) => location::PublicStatus {
            permission: location::Permission::Denied,
            availability: location::Availability::Unavailable,
        },
        Err(location::ReadOutcome::Revoked) => location::PublicStatus {
            permission: location::Permission::Revoked,
            availability: location::Availability::Unavailable,
        },
        Err(location::ReadOutcome::TimedOut) => location::PublicStatus {
            permission: location::Permission::Granted,
            availability: location::Availability::TimedOut,
        },
        Err(location::ReadOutcome::Unsupported) => location::PublicStatus {
            permission: location::Permission::Unsupported,
            availability: location::Availability::Unsupported,
        },
        Err(location::ReadOutcome::Unavailable) => location::PublicStatus {
            permission: location::Permission::Granted,
            availability: location::Availability::Unavailable,
        },
        Err(location::ReadOutcome::Expired) => location::PublicStatus {
            permission: location::Permission::Granted,
            availability: location::Availability::Available,
        },
    };
    let status_changed =
        next_status != location.status() && location.set_status(&context, next_status);
    if status_changed {
        let _ = send_location_state(&app, &backend, &supervisor, &location, &context).await;
    }
    let (outcome, fix) = match result {
        Ok(fix) => ("ok", Some(fix)),
        Err(location::ReadOutcome::PermissionRequired) => ("permission_required", None),
        Err(location::ReadOutcome::Denied) => ("denied", None),
        Err(location::ReadOutcome::Revoked) => {
            app.state::<location::LocationObserver>().remove();
            ("revoked", None)
        }
        Err(location::ReadOutcome::Unavailable) => ("unavailable", None),
        Err(location::ReadOutcome::TimedOut) => ("timed_out", None),
        Err(location::ReadOutcome::Expired) => ("expired", None),
        Err(location::ReadOutcome::Unsupported) => ("unsupported", None),
    };
    if !location.is_current(&context) || backend.snapshot().generation != context.generation {
        return;
    }
    let mut session = supervisor.session.lock().await;
    if !location.is_current(&context)
        || backend.snapshot().generation != context.generation
        || supervisor.quitting.load(Ordering::Acquire)
        || (outcome == "ok"
            && (location.status().permission != location::Permission::Granted
                || read_cancellation
                    .as_ref()
                    .is_some_and(tokio_util::sync::CancellationToken::is_cancelled)))
    {
        return;
    }
    let Some(session) = session.as_mut() else {
        return;
    };
    if send_device_control(
        &mut session.stdin,
        "device_result",
        request_id,
        json!({
            "instance_id": context.instance_id,
            "revision": context.revision,
            "outcome": outcome,
            "fix": fix,
        }),
    )
    .await
    .is_ok()
    {
        let _ = app.emit("desktop-device-state", json!({}));
    }
}

#[derive(Clone, Default)]
struct LocationSequence(Arc<std::sync::atomic::AtomicU64>);

impl LocationSequence {
    fn next(&self) -> u64 {
        self.0.fetch_add(1, Ordering::AcqRel).saturating_add(1)
    }
}

#[derive(Clone, Default)]
struct LocationCheckLock(Arc<Mutex<()>>);

#[tauri::command]
async fn desktop_backend_retry(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    status: State<'_, DesktopState>,
    supervisor: State<'_, Supervisor>,
) -> Result<BackendStatus, &'static str> {
    validate_caller(&window)?;
    Ok(run_start(app, status.inner().clone(), supervisor.inner().clone()).await)
}

#[tauri::command]
async fn desktop_quit(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    status: State<'_, DesktopState>,
    supervisor: State<'_, Supervisor>,
) -> Result<(), &'static str> {
    validate_caller(&window)?;
    quit_app(app, status.inner().clone(), supervisor.inner().clone()).await;
    Ok(())
}

async fn quit_app(app: tauri::AppHandle, status: DesktopState, supervisor: Supervisor) {
    if supervisor.quitting.swap(true, Ordering::AcqRel) {
        return;
    }
    cancel_start(&supervisor).await;
    run_shutdown(app.clone(), status, supervisor).await;
    app.exit(0);
}

fn validate_caller(window: &tauri::WebviewWindow) -> Result<(), &'static str> {
    let url = window.url().map_err(|_| "unauthorized")?;
    if security::is_trusted_caller(window.label(), url.as_str(), cfg!(debug_assertions)) {
        Ok(())
    } else {
        Err("unauthorized")
    }
}

fn safe_event(
    app: &tauri::AppHandle,
    status: &DesktopState,
    generation: u64,
    phase: Phase,
    error: Option<&str>,
    identity: Option<RuntimeIdentity>,
) -> BackendStatus {
    let failed = phase == Phase::Failed;
    let snapshot = status.transition(
        app,
        generation,
        phase,
        error.map(state::safe_error_code),
        identity,
    );
    if failed {
        show_main(app);
    }
    snapshot
}

async fn reconcile_services(
    app: tauri::AppHandle,
    services: DesktopServicesState,
    generation: u64,
    clear_notification_errors: bool,
) {
    let _guard = services.reconcile_lock.lock().await;
    if app
        .state::<Supervisor>()
        .inner()
        .quitting
        .load(Ordering::Acquire)
        || app.state::<DesktopState>().snapshot().generation != generation
        || services.snapshot().generation != generation
    {
        return;
    }
    #[cfg(all(windows, not(debug_assertions)))]
    {
        let snapshot = services.snapshot();
        let wanted = snapshot
            .preferences_ready
            .then_some(snapshot.requested.launch_on_startup);
        let result = tokio::task::spawn_blocking(move || autostart::reconcile(wanted)).await;
        if app
            .state::<Supervisor>()
            .inner()
            .quitting
            .load(Ordering::Acquire)
            || app.state::<DesktopState>().snapshot().generation != generation
            || services.snapshot().generation != generation
        {
            return;
        }
        match result {
            Ok(result) => {
                if wanted.is_some() {
                    services.set_startup(result.actual_enabled, result.error_code);
                } else {
                    services.refresh_startup(result.actual_enabled, result.error_code);
                }
                if result.error_code.is_some() && window_is_hidden_or_minimized(&app) {
                    show_main(&app);
                }
            }
            Err(_) => {
                if wanted.is_some() {
                    services.set_startup(None, Some("autostart_failed"));
                } else {
                    services.refresh_startup(None, Some("autostart_failed"));
                }
                if window_is_hidden_or_minimized(&app) {
                    show_main(&app);
                }
            }
        }
    }
    #[cfg(any(debug_assertions, not(windows)))]
    services.refresh_startup(None, Some("unsupported"));

    let notification_result = tokio::task::spawn_blocking(notifications::query_setting).await;
    if app
        .state::<Supervisor>()
        .inner()
        .quitting
        .load(Ordering::Acquire)
        || app.state::<DesktopState>().snapshot().generation != generation
        || services.snapshot().generation != generation
    {
        return;
    }
    match notification_result {
        Ok(Ok(probe)) if clear_notification_errors => {
            let error = notification_probe_error(&probe);
            services.set_notification_probe(probe, error);
        }
        Ok(Ok(probe)) => {
            let error = notification_probe_error(&probe);
            services.refresh_notification_probe(probe, error);
        }
        Err(_) if clear_notification_errors => services.set_notifications(
            NotificationSetting::Unavailable,
            Some("notification_unavailable"),
        ),
        Ok(Err(_)) if clear_notification_errors => services.set_notifications(
            NotificationSetting::Unavailable,
            Some("notification_unavailable"),
        ),
        _ => services.refresh_notifications(
            NotificationSetting::Unavailable,
            Some("notification_unavailable"),
        ),
    }
    if app
        .state::<Supervisor>()
        .inner()
        .quitting
        .load(Ordering::Acquire)
        || app.state::<DesktopState>().snapshot().generation != generation
        || services.snapshot().generation != generation
    {
        return;
    }
    services.publish(&app);
}

async fn refresh_services_status(
    app: tauri::AppHandle,
    services: DesktopServicesState,
    generation: u64,
    publish: bool,
) {
    let _guard = services.reconcile_lock.lock().await;
    if app
        .state::<Supervisor>()
        .inner()
        .quitting
        .load(Ordering::Acquire)
        || app.state::<DesktopState>().snapshot().generation != generation
        || services.snapshot().generation != generation
    {
        return;
    }

    #[cfg(all(windows, not(debug_assertions)))]
    {
        let startup = tokio::task::spawn_blocking(|| autostart::reconcile(None)).await;
        if app
            .state::<Supervisor>()
            .inner()
            .quitting
            .load(Ordering::Acquire)
            || app.state::<DesktopState>().snapshot().generation != generation
            || services.snapshot().generation != generation
        {
            return;
        }
        match startup {
            Ok(result) => services.refresh_startup(result.actual_enabled, result.error_code),
            Err(_) => services.refresh_startup(None, Some("autostart_read_failed")),
        }
    }
    #[cfg(any(debug_assertions, not(windows)))]
    services.refresh_startup(None, Some("unsupported"));

    let notification = tokio::task::spawn_blocking(notifications::query_setting).await;
    if app
        .state::<Supervisor>()
        .inner()
        .quitting
        .load(Ordering::Acquire)
        || app.state::<DesktopState>().snapshot().generation != generation
        || services.snapshot().generation != generation
    {
        return;
    }
    match notification {
        Ok(Ok(probe)) => {
            let error = notification_probe_error(&probe);
            services.refresh_notification_probe(probe, error);
        }
        _ => services.refresh_notifications(
            NotificationSetting::Unavailable,
            Some("notification_unavailable"),
        ),
    }
    if publish {
        services.publish(&app);
    }
}

async fn submit_completion_notification(
    app: tauri::AppHandle,
    services: DesktopServicesState,
    supervisor: Supervisor,
    generation: u64,
) {
    if supervisor.quitting.load(Ordering::Acquire)
        || app.state::<DesktopState>().snapshot().generation != generation
        || services.snapshot().generation != generation
        || !services.should_submit_notification()
        || !window_is_hidden_or_minimized(&app)
    {
        return;
    }
    let result = tokio::task::spawn_blocking(notifications::show_completion).await;
    if supervisor.quitting.load(Ordering::Acquire)
        || app.state::<DesktopState>().snapshot().generation != generation
        || services.snapshot().generation != generation
    {
        return;
    }
    match result {
        Ok(Ok(attempt)) => {
            let error = notification_probe_error(&attempt.probe);
            services.refresh_notification_probe(attempt.probe, error);
        }
        Ok(Err(code)) => services.set_notification_error(code),
        Err(_) => services.set_notification_error("notification_failed"),
    }
    services.publish(&app);
}

fn notification_probe_error(probe: &NotificationSettingProbe) -> Option<&'static str> {
    match probe {
        NotificationSettingProbe::Known(_) => None,
        NotificationSettingProbe::IdentityNotFound => Some("notification_identity_unregistered"),
    }
}

async fn stop_previous(
    app: &tauri::AppHandle,
    state: &DesktopState,
    generation: u64,
    supervisor: &Supervisor,
) {
    let mut session = supervisor.session.lock().await;
    if let Some(mut previous) = session.take() {
        let budget = state
            .snapshot()
            .runtime
            .map(|identity| identity.shutdown_timeout_seconds)
            .unwrap_or(60);
        safe_event(app, state, generation, Phase::Stopping, None, None);
        let _ = generation;
        cleanup_owned(&mut previous, budget).await;
    }
}

async fn run_start(
    app: tauri::AppHandle,
    state: DesktopState,
    supervisor: Supervisor,
) -> BackendStatus {
    let observed_generation = state.snapshot().generation;
    let _operation = supervisor.operation.lock().await;
    if supervisor.quitting.load(Ordering::Acquire) {
        return state.snapshot();
    }
    let cancellation = CancellationToken::new();
    {
        let mut active = supervisor.cancellation.lock().await;
        if supervisor.quitting.load(Ordering::Acquire) {
            return state.snapshot();
        }
        *active = Some(cancellation.clone());
    }
    let current = state.snapshot();
    if state::coalesce_retry(
        observed_generation,
        &current,
        supervisor.quitting.load(Ordering::Acquire),
    ) {
        *supervisor.cancellation.lock().await = None;
        return current;
    }
    let generation = current.generation.saturating_add(1);
    app.state::<location::LocationState>().reset(generation);
    app.state::<location::LocationObserver>().remove();
    if current.runtime.is_some() {
        safe_event(
            &app,
            &state,
            generation,
            Phase::Stopping,
            None,
            current.runtime.clone(),
        );
    }
    stop_previous(&app, &state, generation, &supervisor).await;
    safe_event(&app, &state, generation, Phase::Starting, None, None);
    let services = app.state::<DesktopServicesState>().inner().clone();
    services.set_generation(generation);
    services.publish(&app);
    let spawned = tokio::select! {
        biased;
        value = spawn_backend(&app) => value,
        _ = cancellation.cancelled() => {
            *supervisor.cancellation.lock().await = None;
            safe_event(&app, &state, generation, Phase::Stopped, None, None);
            return state.snapshot();
        }
    };
    let (session, expected_build, launch_id) = match spawned {
        Ok(value) => value,
        Err(code) => return safe_event(&app, &state, generation, Phase::Failed, Some(code), None),
    };
    let mut session = session;
    let sent = tokio::select! {
        _ = cancellation.cancelled() => {
            cleanup_owned(&mut session, 60).await;
            *supervisor.cancellation.lock().await = None;
            safe_event(&app, &state, generation, Phase::Stopped, None, None);
            return state.snapshot();
        }
        result = timeout(Duration::from_secs(2), send_control(&mut session.stdin, "start", format!("start:{generation}"), json!({"launch_id":launch_id})) ) => result,
    };
    if !matches!(sent, Ok(Ok(()))) {
        return fail_start(&app, &state, generation, session, "protocol_error", None).await;
    }
    let deadline = Instant::now() + STARTUP_LIMIT;
    let mut identity: Option<RuntimeIdentity> = None;
    let request_id = format!("start:{generation}");
    let client = reqwest::Client::builder()
        .no_proxy()
        .connect_timeout(Duration::from_secs(2))
        .timeout(Duration::from_secs(3))
        .build();
    let client = match client {
        Ok(client) => client,
        Err(_) => {
            return fail_start(&app, &state, generation, session, "internal_error", None).await;
        }
    };
    loop {
        let now = Instant::now();
        if now >= deadline {
            return fail_start(
                &app,
                &state,
                generation,
                session,
                "startup_timeout",
                identity.as_ref(),
            )
            .await;
        }
        let child_exited = match session.child.try_wait() {
            Ok(Some(_)) | Err(_) => true,
            Ok(None) => false,
        };
        let receive_wait = (deadline - now).min(if child_exited {
            EXIT_FRAME_GRACE
        } else {
            Duration::from_millis(250)
        });
        let receive = tokio::select! {
            _ = cancellation.cancelled() => {
                cleanup_owned(&mut session, identity.as_ref().map(|id| id.shutdown_timeout_seconds).unwrap_or(60)).await;
                *supervisor.cancellation.lock().await = None;
                safe_event(&app, &state, generation, Phase::Stopped, None, None);
                return state.snapshot();
            }
            received = receive_startup_frame(&mut session.rx, receive_wait, child_exited) => received,
        };
        let frame = match receive {
            StartupReceive::Frame(Ok(frame)) => frame,
            StartupReceive::Frame(Err(code)) => {
                return fail_start(&app, &state, generation, session, code, identity.as_ref())
                    .await;
            }
            StartupReceive::Closed => {
                return fail_start(
                    &app,
                    &state,
                    generation,
                    session,
                    "backend_crashed",
                    identity.as_ref(),
                )
                .await;
            }
            StartupReceive::Exited => {
                return fail_start(
                    &app,
                    &state,
                    generation,
                    session,
                    "backend_crashed",
                    identity.as_ref(),
                )
                .await;
            }
            StartupReceive::TimedOut => {
                // The host deadline is for receiving the start request, which was
                // sent immediately above. Startup may continue while API imports run.
                continue;
            }
        };
        if frame.kind == "completion" {
            let run_id = frame.payload.get("run_id").and_then(Value::as_str);
            let instance_id = frame.payload.get("instance_id").and_then(Value::as_str);
            if run_id != Some(frame.request_id.as_str())
                || identity
                    .as_ref()
                    .is_none_or(|item| Some(item.instance_id.as_str()) != instance_id)
            {
                return fail_start(
                    &app,
                    &state,
                    generation,
                    session,
                    "protocol_error",
                    identity.as_ref(),
                )
                .await;
            }
            let services = app.state::<DesktopServicesState>().inner().clone();
            let _ = services.take_completion(
                instance_id.unwrap_or(""),
                run_id.unwrap_or(""),
                identity
                    .as_ref()
                    .map(|item| item.instance_id.as_str())
                    .unwrap_or(""),
            );
            continue;
        }
        if frame.kind == "desktop_preferences" {
            let Some(instance) = identity.as_ref().map(|item| item.instance_id.as_str()) else {
                return fail_start(
                    &app,
                    &state,
                    generation,
                    session,
                    "protocol_error",
                    identity.as_ref(),
                )
                .await;
            };
            let services = app.state::<DesktopServicesState>().inner().clone();
            if let Err(code) =
                services.accept_preferences(&frame.request_id, frame.payload, instance)
            {
                return fail_start(&app, &state, generation, session, code, identity.as_ref())
                    .await;
            }
            services.publish(&app);
            continue;
        }
        if frame.kind == "device_preferences" {
            let Some(instance) = identity.as_ref().map(|item| item.instance_id.as_str()) else {
                return fail_start(
                    &app,
                    &state,
                    generation,
                    session,
                    "protocol_error",
                    identity.as_ref(),
                )
                .await;
            };
            if let Err(code) = accept_location_preferences(&app, generation, &frame, instance) {
                return fail_start(&app, &state, generation, session, code, identity.as_ref())
                    .await;
            }
            continue;
        }
        if frame.kind == "device_request" {
            let Some(identity) = identity.as_ref() else {
                return fail_start(&app, &state, generation, session, "protocol_error", None).await;
            };
            let location = app.state::<location::LocationState>();
            let context = location.context();
            let request_matches = frame.payload.get("instance_id").and_then(Value::as_str)
                == Some(identity.instance_id.as_str())
                && context.as_ref().is_some_and(|context| {
                    context.generation == generation
                        && context.instance_id == identity.instance_id
                        && frame.payload.get("revision").and_then(Value::as_u64)
                            == Some(context.revision)
                });
            if request_matches
                && send_device_control(
                    &mut session.stdin,
                    "device_result",
                    frame.request_id,
                    json!({
                        "instance_id": identity.instance_id,
                        "revision": context.as_ref().map(|context| context.revision).unwrap_or(1),
                        "outcome": "permission_required",
                        "fix": null,
                    }),
                )
                .await
                .is_err()
            {
                return fail_start(
                    &app,
                    &state,
                    generation,
                    session,
                    "backend_crashed",
                    Some(identity),
                )
                .await;
            }
            continue;
        }
        if frame.request_id != request_id {
            return fail_start(
                &app,
                &state,
                generation,
                session,
                "protocol_error",
                identity.as_ref(),
            )
            .await;
        }
        match frame.kind.as_str() {
            "starting" => {
                if identity.is_some() {
                    return fail_start(
                        &app,
                        &state,
                        generation,
                        session,
                        "protocol_error",
                        identity.as_ref(),
                    )
                    .await;
                }
                let parsed = match serde_json::from_value::<RuntimeIdentity>(frame.payload) {
                    Ok(value) => value,
                    Err(_) => {
                        return fail_start(
                            &app,
                            &state,
                            generation,
                            session,
                            "protocol_error",
                            identity.as_ref(),
                        )
                        .await;
                    }
                };
                if parsed
                    .validate(&launch_id, &expected_build, child_pid(&session.child))
                    .is_err()
                {
                    return fail_start(
                        &app,
                        &state,
                        generation,
                        session,
                        "identity_mismatch",
                        identity.as_ref(),
                    )
                    .await;
                }
                identity = Some(parsed);
                safe_event(
                    &app,
                    &state,
                    generation,
                    Phase::Starting,
                    None,
                    identity.clone(),
                );
            }
            "ready" => {
                let ready = match serde_json::from_value::<RuntimeIdentity>(frame.payload) {
                    Ok(value) => value,
                    Err(_) => {
                        return fail_start(
                            &app,
                            &state,
                            generation,
                            session,
                            "protocol_error",
                            identity.as_ref(),
                        )
                        .await;
                    }
                };
                if ready
                    .validate(&launch_id, &expected_build, child_pid(&session.child))
                    .is_err()
                    || identity.as_ref() != Some(&ready)
                {
                    return fail_start(
                        &app,
                        &state,
                        generation,
                        session,
                        "identity_mismatch",
                        identity.as_ref(),
                    )
                    .await;
                }
                let verification = tokio::select! {
                    _ = cancellation.cancelled() => {
                        cleanup_owned(&mut session, ready.shutdown_timeout_seconds).await;
                        *supervisor.cancellation.lock().await = None;
                        safe_event(&app, &state, generation, Phase::Stopped, None, None);
                        return state.snapshot();
                    }
                    result = verify_runtime(&client, &ready) => result,
                };
                match verification {
                    Ok(()) => {
                        let result =
                            safe_event(&app, &state, generation, Phase::Ready, None, Some(ready));
                        let services = app.state::<DesktopServicesState>().inner().clone();
                        *supervisor.session.lock().await = Some(session);
                        *supervisor.cancellation.lock().await = None;
                        let service_app = app.clone();
                        tauri::async_runtime::spawn(reconcile_services(
                            service_app,
                            services,
                            generation,
                            false,
                        ));
                        tauri::async_runtime::spawn(monitor_backend(
                            app.clone(),
                            state.clone(),
                            supervisor.clone(),
                            generation,
                        ));
                        return result;
                    }
                    Err(code) => {
                        return fail_start(
                            &app,
                            &state,
                            generation,
                            session,
                            code,
                            identity.as_ref(),
                        )
                        .await
                    }
                }
            }
            "error" => {
                let code = frame
                    .payload
                    .get("code")
                    .and_then(Value::as_str)
                    .map(state::safe_error_code)
                    .unwrap_or("internal_error");
                return fail_start(&app, &state, generation, session, code, identity.as_ref())
                    .await;
            }
            "completion" | "stopping" | "stopped" => {}
            _ => {
                return fail_start(
                    &app,
                    &state,
                    generation,
                    session,
                    "protocol_error",
                    identity.as_ref(),
                )
                .await;
            }
        }
    }
}

async fn run_shutdown(app: tauri::AppHandle, state: DesktopState, supervisor: Supervisor) {
    supervisor.quitting.store(true, Ordering::Release);
    app.state::<location::LocationState>().cancel_pending();
    app.state::<location::LocationObserver>().remove();
    cancel_start(&supervisor).await;
    let _operation = supervisor.operation.lock().await;
    let generation = state.snapshot().generation;
    let mut guard = supervisor.session.lock().await;
    let Some(mut session) = guard.take() else {
        safe_event(&app, &state, generation, Phase::Stopped, None, None);
        return;
    };
    let current = state.snapshot();
    let budget = current
        .runtime
        .as_ref()
        .map(|id| id.shutdown_timeout_seconds)
        .unwrap_or(60)
        .min(3600);
    safe_event(
        &app,
        &state,
        generation,
        Phase::Stopping,
        None,
        current.runtime,
    );
    cleanup_owned(&mut session, budget).await;
    safe_event(&app, &state, generation, Phase::Stopped, None, None);
}

async fn cancel_start(supervisor: &Supervisor) {
    if let Some(token) = supervisor.cancellation.lock().await.as_ref() {
        token.cancel();
    }
}

async fn monitor_backend(
    app: tauri::AppHandle,
    state: DesktopState,
    supervisor: Supervisor,
    generation: u64,
) {
    loop {
        tokio::time::sleep(Duration::from_millis(250)).await;
        if state.snapshot().generation != generation {
            return;
        }
        let snapshot = state.snapshot();
        let expected_instance = snapshot
            .runtime
            .as_ref()
            .map(|id| id.instance_id.as_str())
            .unwrap_or("");
        let services = app.state::<DesktopServicesState>().inner().clone();
        let mut owned = supervisor.session.lock().await;
        let Some(session) = owned.as_mut() else {
            return;
        };
        let mut outcome: Option<(bool, &'static str)> = None;
        let mut preferences_changed = false;
        let mut location_preferences_changed = false;
        let mut pending_device_requests = Vec::new();
        let mut eligible_completions = 0usize;
        match session.child.try_wait() {
            Ok(Some(_)) | Err(_) => outcome = Some((false, "backend_crashed")),
            Ok(None) => {}
        }
        if outcome.is_none() {
            loop {
                match session.rx.try_recv() {
                    Ok(Ok(frame)) if frame.kind == "completion" => {
                        let run_id = frame
                            .payload
                            .get("run_id")
                            .and_then(Value::as_str)
                            .unwrap_or("");
                        let frame_instance = frame
                            .payload
                            .get("instance_id")
                            .and_then(Value::as_str)
                            .unwrap_or("");
                        if frame.request_id != run_id || frame_instance != expected_instance {
                            outcome = Some((false, "protocol_error"));
                        } else {
                            let completed = frame.payload.get("status").and_then(Value::as_str)
                                == Some("completed");
                            let hidden = completed && window_is_hidden_or_minimized(&app);
                            if services.record_completion_eligibility(
                                frame_instance,
                                run_id,
                                expected_instance,
                                completed,
                                hidden,
                            ) {
                                eligible_completions = eligible_completions.saturating_add(1);
                            }
                        }
                    }
                    Ok(Ok(frame)) if frame.kind == "desktop_preferences" => {
                        match services.accept_preferences(
                            &frame.request_id,
                            frame.payload,
                            expected_instance,
                        ) {
                            Ok(_) => preferences_changed = true,
                            Err(code) => outcome = Some((false, code)),
                        }
                    }
                    Ok(Ok(frame)) if frame.kind == "device_preferences" => {
                        match accept_location_preferences(
                            &app,
                            generation,
                            &frame,
                            expected_instance,
                        ) {
                            Ok(changed) => location_preferences_changed |= changed,
                            Err(code) => outcome = Some((false, code)),
                        }
                    }
                    Ok(Ok(frame)) if frame.kind == "device_request" => {
                        let location = app.state::<location::LocationState>();
                        let sequence = frame
                            .request_id
                            .strip_prefix("device:")
                            .and_then(|value| value.parse::<u64>().ok())
                            .unwrap_or(0);
                        if frame.payload.get("instance_id").and_then(Value::as_str)
                            == Some(expected_instance)
                        {
                            if let Some(context) = location.context() {
                                if context.generation == generation
                                    && context.instance_id == expected_instance
                                    && frame.payload.get("revision").and_then(Value::as_u64)
                                        == Some(context.revision)
                                    && location.accept_request_sequence(&context, sequence)
                                {
                                    pending_device_requests.push((context, frame.request_id));
                                }
                            }
                        }
                    }
                    Ok(Ok(frame))
                        if frame.kind == "stopping"
                            && (frame.request_id == format!("start:{generation}")
                                || frame.request_id == format!("shutdown:{generation}")
                                || frame.request_id == "shutdown:cleanup") =>
                    {
                        continue
                    }
                    Ok(Ok(frame))
                        if frame.kind == "stopped"
                            && (frame.request_id == format!("start:{generation}")
                                || frame.request_id == format!("shutdown:{generation}")
                                || frame.request_id == "shutdown:cleanup") =>
                    {
                        outcome = Some((true, "shutdown_failed"))
                    }
                    Ok(Ok(frame))
                        if frame.kind == "error"
                            && (frame.request_id == format!("start:{generation}")
                                || frame.request_id == format!("shutdown:{generation}")
                                || frame.request_id == "shutdown:cleanup") =>
                    {
                        outcome = Some((
                            false,
                            frame
                                .payload
                                .get("code")
                                .and_then(Value::as_str)
                                .map(state::safe_error_code)
                                .unwrap_or("internal_error"),
                        ))
                    }
                    Ok(Err(code)) => outcome = Some((false, code)),
                    Ok(Ok(_)) => outcome = Some((false, "protocol_error")),
                    Err(mpsc::error::TryRecvError::Empty) => break,
                    Err(mpsc::error::TryRecvError::Disconnected) => {
                        outcome = Some((false, "backend_crashed"))
                    }
                }
                if outcome.is_some() {
                    break;
                }
            }
        }
        if outcome.is_none() && matches!(session.child.try_wait(), Ok(Some(_)) | Err(_)) {
            outcome = Some((false, "backend_crashed"));
        }
        drop(owned);
        if app
            .state::<Supervisor>()
            .inner()
            .quitting
            .load(Ordering::Acquire)
        {
            return;
        }
        if preferences_changed {
            services.publish(&app);
            reconcile_services(app.clone(), services.clone(), generation, false).await;
        }
        if location_preferences_changed {
            app.state::<location::LocationObserver>().remove();
            let location = app.state::<location::LocationState>();
            if let Some(context) = location.context() {
                let _ = send_location_state(&app, &state, &supervisor, &location, &context).await;
                let _ = app.emit("desktop-device-state", json!({}));
            }
        }
        for (context, request_id) in pending_device_requests {
            let app = app.clone();
            let state = state.clone();
            let supervisor = supervisor.clone();
            tauri::async_runtime::spawn(async move {
                handle_device_request(app, state, supervisor, context, request_id).await;
            });
        }
        if outcome.is_none() {
            for _ in 0..eligible_completions {
                if supervisor.quitting.load(Ordering::Acquire)
                    || state.snapshot().generation != generation
                {
                    return;
                }
                if services.should_submit_notification() && window_is_hidden_or_minimized(&app) {
                    tauri::async_runtime::spawn(submit_completion_notification(
                        app.clone(),
                        services.clone(),
                        supervisor.clone(),
                        generation,
                    ));
                }
            }
        }
        let Some((stopped_frame, code)) = outcome else {
            continue;
        };
        let _operation = supervisor.operation.lock().await;
        if state.snapshot().generation != generation {
            return;
        }
        let mut owned = supervisor.session.lock().await;
        let Some(mut session) = owned.take() else {
            return;
        };
        let snapshot = state.snapshot();
        app.state::<location::LocationState>().cancel_pending();
        app.state::<location::LocationObserver>().remove();
        safe_event(
            &app,
            &state,
            generation,
            Phase::Stopping,
            None,
            snapshot.runtime.clone(),
        );
        drop(owned);
        let budget = snapshot
            .runtime
            .as_ref()
            .map(|id| id.shutdown_timeout_seconds)
            .unwrap_or(60);
        cleanup_owned(&mut session, budget).await;
        let failure = if stopped_frame {
            "backend_crashed"
        } else {
            code
        };
        safe_event(&app, &state, generation, Phase::Failed, Some(failure), None);
        return;
    }
}

async fn cleanup_owned(session: &mut ChildSession, budget_seconds: u32) {
    let _ = timeout(
        Duration::from_secs(2),
        send_control(
            &mut session.stdin,
            "shutdown",
            "shutdown:cleanup".to_owned(),
            json!({}),
        ),
    )
    .await;
    let budget = budget_seconds.clamp(1, 3600);
    let mut channel_open = true;
    let exited = timeout(Duration::from_secs(budget as u64 + 5), async {
        loop {
            tokio::select! {
                result = session.child.wait() => break result.is_ok(),
                message = session.rx.recv(), if channel_open => {
                    if message.is_none() { channel_open = false; }
                }
            }
        }
    })
    .await
    .unwrap_or(false);
    if !exited {
        let _ = session.child.kill().await;
        let _ = session.child.wait().await;
    }
}

async fn fail_start(
    app: &tauri::AppHandle,
    state: &DesktopState,
    generation: u64,
    mut session: ChildSession,
    error: &'static str,
    identity: Option<&RuntimeIdentity>,
) -> BackendStatus {
    cleanup_owned(
        &mut session,
        identity
            .map(|value| value.shutdown_timeout_seconds)
            .unwrap_or(60),
    )
    .await;
    safe_event(app, state, generation, Phase::Failed, Some(error), None)
}

async fn spawn_backend(
    app: &tauri::AppHandle,
) -> Result<(ChildSession, String, String), &'static str> {
    let bundle = app
        .path()
        .resource_dir()
        .map_err(|_| "resource_missing")?
        .join("backend-bundle");
    let exe = bundle.join("apex-backend.exe");
    if !exe.is_file() {
        return Err("resource_missing");
    }
    let manifest: Value = serde_json::from_slice(
        &tokio::fs::read(bundle.join("bundle-manifest.json"))
            .await
            .map_err(|_| "resource_missing")?,
    )
    .map_err(|_| "resource_missing")?;
    let expected_build = manifest
        .get("build_id")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or("resource_missing")?
        .to_owned();
    #[cfg(windows)]
    let resource_path_reserve = manifest
        .get("files")
        .and_then(Value::as_array)
        .and_then(|files| {
            files
                .iter()
                .filter_map(|file| file.get("path").and_then(Value::as_str))
                .map(|path| path.encode_utf16().count().saturating_add(1))
                .max()
        })
        .ok_or("resource_missing")?;
    let build_info: Value = serde_json::from_slice(
        &tokio::fs::read(bundle.join("_internal").join("build-info.json"))
            .await
            .map_err(|_| "resource_missing")?,
    )
    .map_err(|_| "resource_missing")?;
    if build_info.get("build_id").and_then(Value::as_str) != Some(&expected_build) {
        return Err("identity_mismatch");
    }
    let launch_id = Uuid::new_v4().to_string();
    #[cfg(windows)]
    let (child, stdin, stdout, stderr) =
        windows_job::spawn(&exe, &bundle, &launch_id, resource_path_reserve)
            .map_err(|_| "startup_failed")?;
    #[cfg(not(windows))]
    let (child, stdin, stdout, stderr) = {
        let mut command = tokio::process::Command::new(exe);
        command
            .args(["serve", "--managed", "--launch-id", &launch_id])
            .current_dir(&bundle)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .kill_on_drop(true);
        let mut child = command.spawn().map_err(|_| "startup_failed")?;
        let stdin = child.stdin.take().ok_or("internal_error")?;
        let stdout = child.stdout.take().ok_or("internal_error")?;
        let stderr = child.stderr.take().ok_or("internal_error")?;
        (child, stdin, stdout, stderr)
    };
    let (tx, rx) = mpsc::channel(32);
    start_stdout_reader(stdout, tx);
    tauri::async_runtime::spawn(async move {
        let mut drain = BufReader::new(stderr);
        let mut sink = tokio::io::sink();
        let _ = tokio::io::copy(&mut drain, &mut sink).await;
    });
    Ok((ChildSession { child, stdin, rx }, expected_build, launch_id))
}

async fn send_control(
    stdin: &mut ChildInput,
    kind: &str,
    request_id: String,
    payload: Value,
) -> Result<(), ()> {
    let frame = json!({"version":1,"type":kind,"request_id":request_id,"payload":payload});
    let mut bytes = serde_json::to_vec(&frame).map_err(|_| ())?;
    bytes.push(b'\n');
    #[cfg(windows)]
    let ChildInput::Pipe(writer) = stdin;
    #[cfg(not(windows))]
    let writer = stdin;
    writer.write_all(&bytes).await.map_err(|_| ())?;
    writer.flush().await.map_err(|_| ())
}

#[cfg(windows)]
fn child_pid(child: &OwnedChild) -> u32 {
    child.id()
}
#[cfg(not(windows))]
fn child_pid(child: &OwnedChild) -> u32 {
    child.id().unwrap_or_default()
}

async fn verify_runtime(
    client: &reqwest::Client,
    identity: &RuntimeIdentity,
) -> Result<(), &'static str> {
    let response = client
        .get(API_RUNTIME)
        .header("Origin", NATIVE_ORIGIN)
        .send()
        .await
        .map_err(|_| "identity_mismatch")?;
    if response.status() != reqwest::StatusCode::OK {
        return Err("identity_mismatch");
    }
    let allowed = response
        .headers()
        .get("access-control-allow-origin")
        .and_then(|value| value.to_str().ok());
    if allowed != Some(NATIVE_ORIGIN) && allowed != Some("*") {
        return Err("cors_rejected");
    }
    let mut stream = response.bytes_stream();
    let mut body = Vec::with_capacity(1024);
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|_| "identity_mismatch")?;
        if body.len().saturating_add(chunk.len()) > MAX_HTTP_BYTES {
            return Err("identity_mismatch");
        }
        body.extend_from_slice(&chunk);
    }
    let api: RuntimeIdentity = serde_json::from_slice(&body).map_err(|_| "identity_mismatch")?;
    if &api != identity {
        return Err("identity_mismatch");
    }
    let health = client
        .get(API_HEALTH)
        .header("Origin", NATIVE_ORIGIN)
        .send()
        .await
        .map_err(|_| "identity_mismatch")?;
    if health.status() != reqwest::StatusCode::OK {
        return Err("identity_mismatch");
    }
    let health_origin = health
        .headers()
        .get("access-control-allow-origin")
        .and_then(|value| value.to_str().ok());
    if health_origin != Some(NATIVE_ORIGIN) && health_origin != Some("*") {
        return Err("cors_rejected");
    }
    let mut health_stream = health.bytes_stream();
    let mut health_body = Vec::with_capacity(128);
    while let Some(chunk) = health_stream.next().await {
        let chunk = chunk.map_err(|_| "identity_mismatch")?;
        if health_body.len().saturating_add(chunk.len()) > 1024 {
            return Err("identity_mismatch");
        }
        health_body.extend_from_slice(&chunk);
    }
    let readiness: Value = serde_json::from_slice(&health_body).map_err(|_| "identity_mismatch")?;
    if readiness != json!({"status":"ready","config":"ok","database":"ok"}) {
        return Err("identity_mismatch");
    }
    Ok(())
}

fn main() {
    let status = DesktopState::new();
    let supervisor = Supervisor {
        session: Arc::new(Mutex::new(None)),
        operation: Arc::new(Mutex::new(())),
        cancellation: Arc::new(Mutex::new(None)),
        quitting: Arc::new(AtomicBool::new(false)),
    };
    tauri::Builder::default()
        .manage(status.clone())
        .manage(supervisor.clone())
        .manage(location::LocationState::default())
        .manage(location::LocationObserver)
        .manage(LocationSequence::default())
        .manage(LocationCheckLock::default())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_main(app);
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(
                    tauri_plugin_window_state::StateFlags::SIZE
                        | tauri_plugin_window_state::StateFlags::POSITION
                        | tauri_plugin_window_state::StateFlags::MAXIMIZED,
                )
                .build(),
        )
        .plugin(
            tauri_plugin_autostart::Builder::new()
                .app_name("APEX")
                .args(["--autostart"])
                .build(),
        )
        .setup(move |app| {
            let handle = app.handle().clone();
            let window =
                WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                    .title("APEX")
                    .inner_size(1440.0, 900.0)
                    .min_inner_size(320.0, 240.0)
                    .use_https_scheme(false)
                    .on_navigation(|url| {
                        security::is_trusted_url(url.as_str(), cfg!(debug_assertions))
                    })
                    .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
                    .build()?;
            let tray_available = create_tray(app);
            let services = DesktopServicesState::new(
                tray_available,
                cfg!(all(windows, not(debug_assertions))),
            );
            app.manage(services);
            if cfg!(not(debug_assertions))
                && tray_available
                && std::env::args().any(|argument| argument == "--autostart")
            {
                let _ = window.hide();
            } else {
                let _ = window.show();
            }
            let restore_window = window.clone();
            tauri::async_runtime::spawn(async move {
                tokio::time::sleep(Duration::from_millis(300)).await;
                ensure_usable_geometry(&restore_window);
            });
            let initial_status = app.state::<DesktopState>().inner().clone();
            let initial_supervisor = app.state::<Supervisor>().inner().clone();
            tauri::async_runtime::spawn(async move {
                let _ = run_start(handle, initial_status, initial_supervisor).await;
            });
            let app_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let generation = app_handle.state::<DesktopState>().snapshot().generation;
                reconcile_services(
                    app_handle.clone(),
                    app_handle.state::<DesktopServicesState>().inner().clone(),
                    generation,
                    false,
                )
                .await;
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let app = window.app_handle().clone();
                let has_tray = app
                    .state::<DesktopServicesState>()
                    .snapshot()
                    .tray_available;
                match close_action(has_tray) {
                    CloseAction::Hide => {
                        let _ = window.hide();
                    }
                    CloseAction::Quit => {
                        let status = app.state::<DesktopState>().inner().clone();
                        let supervisor = app.state::<Supervisor>().inner().clone();
                        tauri::async_runtime::spawn(quit_app(app, status, supervisor));
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            desktop_backend_status,
            desktop_backend_retry,
            desktop_quit,
            desktop_services_status,
            desktop_services_retry,
            desktop_open_external,
            desktop_write_clipboard,
            desktop_check_location_permission
        ])
        .run(tauri::generate_context!())
        .expect("failed to run APEX desktop shell");
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum CloseAction {
    Hide,
    Quit,
}

fn close_action(tray_available: bool) -> CloseAction {
    if tray_available {
        CloseAction::Hide
    } else {
        CloseAction::Quit
    }
}

fn show_main(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        ensure_usable_geometry(&window);
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
        let app = app.clone();
        tauri::async_runtime::spawn(async move {
            let generation = app.state::<DesktopState>().snapshot().generation;
            refresh_services_status(
                app.clone(),
                app.state::<DesktopServicesState>().inner().clone(),
                generation,
                true,
            )
            .await;
        });
    }
}

fn window_is_hidden_or_minimized(app: &tauri::AppHandle) -> bool {
    app.get_webview_window("main").is_some_and(|window| {
        let visible = window.is_visible().unwrap_or(true);
        let minimized = window.is_minimized().unwrap_or(false);
        notifications::eligible_when_hidden_or_minimized(visible, minimized)
    })
}

fn create_tray(app: &mut tauri::App) -> bool {
    use tauri::{
        menu::{Menu, MenuItem},
        tray::TrayIconBuilder,
    };
    let show = match MenuItem::with_id(app, "show", "Show", true, None::<&str>) {
        Ok(value) => value,
        Err(_) => return false,
    };
    let quit = match MenuItem::with_id(app, "quit", "Quit", true, None::<&str>) {
        Ok(value) => value,
        Err(_) => return false,
    };
    let menu = match Menu::with_items(app, &[&show, &quit]) {
        Ok(value) => value,
        Err(_) => return false,
    };
    let mut builder = TrayIconBuilder::with_id("apex-tray")
        .tooltip("APEX")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show" => show_main(app),
            "quit" => {
                let status = app.state::<DesktopState>().inner().clone();
                let supervisor = app.state::<Supervisor>().inner().clone();
                let app = app.clone();
                tauri::async_runtime::spawn(quit_app(app, status, supervisor));
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let tauri::tray::TrayIconEvent::Click {
                button: tauri::tray::MouseButton::Left,
                ..
            } = event
            {
                show_main(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app).is_ok()
}

fn ensure_usable_geometry(window: &tauri::WebviewWindow) {
    let was_maximized = window.is_maximized().unwrap_or(false);
    if window.is_minimized().unwrap_or(false) {
        let _ = window.unminimize();
    }
    let Ok(position) = window.outer_position() else {
        return;
    };
    let Ok(size) = window.outer_size() else {
        return;
    };
    let Some(area) = usable_work_area(window, position, size) else {
        return;
    };
    let Some(bounds) = window_geometry::clamp_saved_bounds(
        window_geometry::WindowBounds {
            x: position.x,
            y: position.y,
            width: size.width,
            height: size.height,
        },
        area,
        (1440, 900),
    ) else {
        return;
    };
    if area.width < 640 || area.height < 480 {
        let _ = window.set_min_size(Some(tauri::PhysicalSize::new(
            area.width.min(320),
            area.height.min(240),
        )));
    }
    if !was_maximized && (bounds.width != size.width || bounds.height != size.height) {
        let _ = window.set_size(tauri::PhysicalSize::new(bounds.width, bounds.height));
    }
    if bounds.x != position.x || bounds.y != position.y {
        let _ = window.set_position(tauri::PhysicalPosition::new(bounds.x, bounds.y));
    }
    if was_maximized {
        let _ = window.maximize();
    }
}

#[cfg(windows)]
fn usable_work_area(
    _window: &tauri::WebviewWindow,
    position: tauri::PhysicalPosition<i32>,
    size: tauri::PhysicalSize<u32>,
) -> Option<window_geometry::WorkArea> {
    use windows::Win32::{
        Foundation::RECT,
        Graphics::Gdi::{GetMonitorInfoW, MonitorFromRect, MONITORINFO, MONITOR_DEFAULTTONEAREST},
    };
    let rect = RECT {
        left: position.x,
        top: position.y,
        right: position
            .x
            .saturating_add(size.width.min(i32::MAX as u32) as i32),
        bottom: position
            .y
            .saturating_add(size.height.min(i32::MAX as u32) as i32),
    };
    let monitor = unsafe { MonitorFromRect(&rect, MONITOR_DEFAULTTONEAREST) };
    if monitor.0.is_null() {
        return None;
    }
    let mut info = MONITORINFO {
        cbSize: std::mem::size_of::<MONITORINFO>() as u32,
        ..Default::default()
    };
    if !unsafe { GetMonitorInfoW(monitor, &mut info) }.as_bool() {
        return None;
    }
    Some(window_geometry::WorkArea {
        x: info.rcWork.left,
        y: info.rcWork.top,
        width: info.rcWork.right.saturating_sub(info.rcWork.left).max(0) as u32,
        height: info.rcWork.bottom.saturating_sub(info.rcWork.top).max(0) as u32,
    })
}

#[cfg(not(windows))]
fn usable_work_area(
    window: &tauri::WebviewWindow,
    _position: tauri::PhysicalPosition<i32>,
    _size: tauri::PhysicalSize<u32>,
) -> Option<window_geometry::WorkArea> {
    let monitor = window.primary_monitor().ok().flatten()?;
    let position = monitor.position();
    let size = monitor.size();
    Some(window_geometry::WorkArea {
        x: position.x,
        y: position.y,
        width: size.width,
        height: size.height,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn close_hides_only_when_a_recovery_tray_is_available() {
        assert_eq!(close_action(true), CloseAction::Hide);
        assert_eq!(close_action(false), CloseAction::Quit);
    }

    #[cfg(windows)]
    #[tokio::test]
    async fn queued_host_error_is_received_before_fast_child_exit_is_classified() {
        let frame = r#"{"version":1,"type":"error","request_id":"start:1","payload":{"code":"port_in_use"}}"#;
        let script = format!("[Console]::Out.Write('{frame}' + [char]10)");
        let mut child = tokio::process::Command::new("powershell.exe")
            .args(["-NoProfile", "-NonInteractive", "-Command", &script])
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null())
            .spawn()
            .expect("Windows PowerShell should launch the fast protocol-error child");
        let stdout = child.stdout.take().expect("child stdout should be piped");
        let (sender, mut receiver) = mpsc::channel(32);
        start_stdout_reader(stdout, sender);

        let exit = child.wait().await.expect("protocol child should exit");
        assert!(exit.success(), "protocol child should exit successfully");
        let child_exited = child
            .try_wait()
            .expect("exit status should remain observable")
            .is_some();
        assert!(child_exited);

        let StartupReceive::Frame(Ok(received)) =
            receive_startup_frame(&mut receiver, EXIT_FRAME_GRACE, child_exited).await
        else {
            panic!("a buffered private error frame must be handled before reporting process exit");
        };
        assert_eq!(received.kind, "error");
        assert_eq!(received.request_id, "start:1");
        assert_eq!(received.payload["code"], "port_in_use");
    }
}
