#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod protocol;
mod security;
mod state;
#[cfg(windows)]
mod windows_job;

use futures_util::StreamExt;
use serde_json::{json, Value};
use state::{BackendStatus, DesktopState, Phase, RuntimeIdentity};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Duration,
};
use tauri::{Manager, State, WebviewUrl, WebviewWindowBuilder};
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
fn desktop_backend_status(
    window: tauri::WebviewWindow,
    status: State<'_, DesktopState>,
) -> Result<BackendStatus, &'static str> {
    validate_caller(&window)?;
    Ok(status.snapshot())
}

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
    supervisor.quitting.store(true, Ordering::Release);
    cancel_start(supervisor.inner()).await;
    run_shutdown(
        app.clone(),
        status.inner().clone(),
        supervisor.inner().clone(),
    )
    .await;
    app.exit(0);
    Ok(())
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
    status.transition(
        app,
        generation,
        phase,
        error.map(state::safe_error_code),
        identity,
    )
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
                return fail_start(&app, &state, generation, session, code, identity.as_ref()).await
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
                .await
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
                    .is_some_and(|item| Some(item.instance_id.as_str()) != instance_id)
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
                        *supervisor.session.lock().await = Some(session);
                        *supervisor.cancellation.lock().await = None;
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
        let mut owned = supervisor.session.lock().await;
        let Some(session) = owned.as_mut() else {
            return;
        };
        let mut outcome: Option<(bool, &'static str)> = None;
        match session.child.try_wait() {
            Ok(Some(_)) | Err(_) => outcome = Some((false, "backend_crashed")),
            Ok(None) => {}
        }
        if outcome.is_none() {
            loop {
                match session.rx.try_recv() {
                    Ok(Ok(frame))
                        if frame.kind == "completion"
                            && frame.request_id
                                == frame
                                    .payload
                                    .get("run_id")
                                    .and_then(Value::as_str)
                                    .unwrap_or("")
                            && frame.payload.get("instance_id").and_then(Value::as_str)
                                == Some(expected_instance) =>
                    {
                        continue
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
        let Some((stopped_frame, code)) = outcome else {
            continue;
        };
        drop(owned);
        let _operation = supervisor.operation.lock().await;
        if state.snapshot().generation != generation {
            return;
        }
        let mut owned = supervisor.session.lock().await;
        let Some(mut session) = owned.take() else {
            return;
        };
        let snapshot = state.snapshot();
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
        windows_job::spawn(&exe, &bundle, &launch_id).map_err(|_| "startup_failed")?;
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
        .setup(move |app| {
            let handle = app.handle().clone();
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("APEX")
                .inner_size(1440.0, 900.0)
                .min_inner_size(1024.0, 700.0)
                .use_https_scheme(false)
                .on_navigation(|url| security::is_trusted_url(url.as_str(), cfg!(debug_assertions)))
                .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
                .build()?;
            let initial_status = app.state::<DesktopState>().inner().clone();
            let initial_supervisor = app.state::<Supervisor>().inner().clone();
            tauri::async_runtime::spawn(async move {
                let _ = run_start(handle, initial_status, initial_supervisor).await;
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let app = window.app_handle().clone();
                let status = app.state::<DesktopState>().inner().clone();
                let supervisor = app.state::<Supervisor>().inner().clone();
                tauri::async_runtime::spawn(async move {
                    run_shutdown(app.clone(), status, supervisor).await;
                    app.exit(0);
                });
            }
        })
        .invoke_handler(tauri::generate_handler![
            desktop_backend_status,
            desktop_backend_retry,
            desktop_quit
        ])
        .run(tauri::generate_context!())
        .expect("failed to run APEX desktop shell");
}

#[cfg(test)]
mod tests {
    use super::*;

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
