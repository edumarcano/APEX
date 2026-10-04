use serde::Serialize;
use std::sync::{Arc, Mutex};

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Permission {
    Unknown,
    Granted,
    Denied,
    Revoked,
    Unsupported,
}

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Availability {
    Unknown,
    Available,
    Unavailable,
    TimedOut,
    Unsupported,
}

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct PublicStatus {
    pub permission: Permission,
    pub availability: Availability,
}

impl Default for PublicStatus {
    fn default() -> Self {
        Self {
            permission: if cfg!(windows) {
                Permission::Unknown
            } else {
                Permission::Unsupported
            },
            availability: if cfg!(windows) {
                Availability::Unknown
            } else {
                Availability::Unsupported
            },
        }
    }
}

pub fn foreground_eligible(visible: bool, minimized: bool, focused: bool) -> bool {
    visible && !minimized && focused
}

#[derive(Clone, Debug)]
struct Session {
    generation: u64,
    instance_id: Option<String>,
    revision: u64,
    enabled: bool,
    status: PublicStatus,
    last_request_sequence: u64,
    cancellation: tokio_util::sync::CancellationToken,
}

#[derive(Clone)]
pub struct LocationState(Arc<Mutex<Session>>);

impl Default for LocationState {
    fn default() -> Self {
        Self(Arc::new(Mutex::new(Session {
            generation: 0,
            instance_id: None,
            revision: 0,
            enabled: false,
            status: PublicStatus::default(),
            last_request_sequence: 0,
            cancellation: tokio_util::sync::CancellationToken::new(),
        })))
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RequestContext {
    pub generation: u64,
    pub instance_id: String,
    pub revision: u64,
    pub enabled: bool,
}

impl LocationState {
    pub fn reset(&self, generation: u64) {
        let mut state = self.0.lock().expect("location state mutex poisoned");
        state.cancellation.cancel();
        *state = Session {
            generation,
            instance_id: None,
            revision: 0,
            enabled: false,
            status: PublicStatus::default(),
            last_request_sequence: 0,
            cancellation: tokio_util::sync::CancellationToken::new(),
        };
    }

    pub fn cancel_pending(&self) {
        if let Ok(state) = self.0.lock() {
            state.cancellation.cancel();
        }
    }

    pub fn cancellation_token(&self) -> tokio_util::sync::CancellationToken {
        self.0
            .lock()
            .map(|state| state.cancellation.clone())
            .unwrap_or_default()
    }

    pub fn accept_preferences(
        &self,
        generation: u64,
        instance_id: &str,
        revision: u64,
        enabled: bool,
    ) -> bool {
        let Ok(mut state) = self.0.lock() else {
            return false;
        };
        if generation != state.generation || revision == 0 {
            return false;
        }
        if let Some(current) = state.instance_id.as_deref() {
            if current != instance_id {
                return false;
            }
            if revision < state.revision {
                return false;
            }
            if revision == state.revision {
                return state.enabled == enabled;
            }
        }
        let changed = state.revision != revision || state.enabled != enabled;
        state.instance_id = Some(instance_id.to_owned());
        state.revision = revision;
        state.enabled = enabled;
        if changed {
            state.cancellation.cancel();
            state.cancellation = tokio_util::sync::CancellationToken::new();
            state.status = PublicStatus::default();
            state.last_request_sequence = 0;
        }
        true
    }

    pub fn context(&self) -> Option<RequestContext> {
        let state = self.0.lock().ok()?;
        Some(RequestContext {
            generation: state.generation,
            instance_id: state.instance_id.clone()?,
            revision: state.revision,
            enabled: state.enabled,
        })
    }

    pub fn status(&self) -> PublicStatus {
        self.0.lock().map(|state| state.status).unwrap_or_default()
    }

    pub fn is_current(&self, context: &RequestContext) -> bool {
        self.context().as_ref() == Some(context)
    }

    pub fn set_status(&self, context: &RequestContext, status: PublicStatus) -> bool {
        let Ok(mut state) = self.0.lock() else {
            return false;
        };
        if state.generation != context.generation
            || state.instance_id.as_deref() != Some(context.instance_id.as_str())
            || state.revision != context.revision
        {
            return false;
        }
        if matches!(state.status.permission, Permission::Granted)
            && matches!(status.permission, Permission::Denied | Permission::Revoked)
        {
            state.cancellation.cancel();
            state.cancellation = tokio_util::sync::CancellationToken::new();
        }
        state.status = status;
        true
    }

    pub fn accept_request_sequence(&self, context: &RequestContext, sequence: u64) -> bool {
        let Ok(mut state) = self.0.lock() else {
            return false;
        };
        if state.generation != context.generation
            || state.instance_id.as_deref() != Some(context.instance_id.as_str())
            || state.revision != context.revision
            || sequence <= state.last_request_sequence
        {
            return false;
        }
        state.last_request_sequence = sequence;
        true
    }
}

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Fix {
    pub latitude: f64,
    pub longitude: f64,
    pub observed_at: f64,
}

impl Fix {
    pub fn validate(self, now_unix: f64) -> Result<Self, ReadOutcome> {
        let age = now_unix - self.observed_at;
        if !self.latitude.is_finite()
            || !(-90.0..=90.0).contains(&self.latitude)
            || !self.longitude.is_finite()
            || !(-180.0..=180.0).contains(&self.longitude)
            || !self.observed_at.is_finite()
        {
            return Err(ReadOutcome::Unavailable);
        }
        if age < 0.0 || age > 900.0 {
            return Err(ReadOutcome::Expired);
        }
        Ok(self)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReadOutcome {
    PermissionRequired,
    Denied,
    Revoked,
    Unavailable,
    TimedOut,
    Expired,
    Unsupported,
}

#[derive(Default)]
pub struct LocationObserver;

impl LocationObserver {
    pub fn remove(&self) {
        #[cfg(windows)]
        winrt::remove_observer();
    }

    pub fn observe(&self, app: tauri::AppHandle, context: RequestContext) {
        #[cfg(windows)]
        winrt::observe(app, context);
        #[cfg(not(windows))]
        let _ = (app, context);
    }
}

#[cfg(windows)]
mod winrt {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};
    use tauri::WebviewWindow;
    use tauri::{Emitter, Manager};
    use windows::Devices::Geolocation::StatusChangedEventArgs;
    use windows::{
        Devices::Geolocation::{GeolocationAccessStatus, Geolocator, PositionStatus},
        Foundation::{DateTime, TimeSpan, TypedEventHandler},
    };

    const WINDOWS_EPOCH_UNIX_SECONDS: f64 = 11_644_473_600.0;
    const TICKS_PER_SECOND: f64 = 10_000_000.0;

    static OBSERVER: std::sync::OnceLock<std::sync::Mutex<Option<(Geolocator, i64)>>> =
        std::sync::OnceLock::new();

    pub fn remove_observer() {
        if let Some(observer) = OBSERVER.get() {
            if let Ok(mut observer) = observer.lock() {
                if let Some((locator, token)) = observer.take() {
                    let _ = locator.RemoveStatusChanged(token);
                }
            }
        }
    }

    pub fn observe(app: tauri::AppHandle, context: RequestContext) {
        remove_observer();
        let Ok(locator) = Geolocator::new() else {
            return;
        };
        let location = app.state::<LocationState>().inner().clone();
        let event_app = app.clone();
        let event_context = context.clone();
        let handler =
            TypedEventHandler::<Geolocator, StatusChangedEventArgs>::new(move |_, args| {
                let Some(args) = args.as_ref() else {
                    return Ok(());
                };
                let Ok(status) = args.Status() else {
                    return Ok(());
                };
                if status == PositionStatus::Disabled {
                    let _ = location.set_status(
                        &event_context,
                        PublicStatus {
                            permission: Permission::Revoked,
                            availability: Availability::Unavailable,
                        },
                    );
                } else {
                    let availability = match status {
                        PositionStatus::Ready | PositionStatus::Initializing => {
                            Availability::Available
                        }
                        PositionStatus::NotInitialized => Availability::Unknown,
                        _ => Availability::Unavailable,
                    };
                    let current = location.status();
                    let _ = location.set_status(
                        &event_context,
                        PublicStatus {
                            availability,
                            ..current
                        },
                    );
                }
                let event_app = event_app.clone();
                let event_context = event_context.clone();
                let event_location = location.clone();
                let should_remove = status == PositionStatus::Disabled;
                tauri::async_runtime::spawn(async move {
                    if event_location.is_current(&event_context) {
                        let backend = event_app.state::<crate::DesktopState>();
                        let supervisor = event_app.state::<crate::Supervisor>();
                        let _ = crate::send_location_state(
                            &event_app,
                            &backend,
                            &supervisor,
                            &event_location,
                            &event_context,
                        )
                        .await;
                        let _ = event_app.emit("desktop-device-state", serde_json::json!({}));
                        if should_remove {
                            event_app.state::<LocationObserver>().remove();
                        }
                    }
                });
                Ok(())
            });
        if let Ok(token) = locator.StatusChanged(&handler) {
            if let Ok(mut observer) = OBSERVER.get_or_init(|| std::sync::Mutex::new(None)).lock() {
                *observer = Some((locator, token));
            }
        }
    }

    pub async fn request_access(
        window: &WebviewWindow,
        cancellation: tokio_util::sync::CancellationToken,
    ) -> Result<PublicStatus, &'static str> {
        let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(30);
        let (sender, receiver) = tokio::sync::oneshot::channel();
        let dispatch_cancellation = cancellation.clone();
        let dispatch_window = window.clone();
        if window
            .run_on_main_thread(move || {
                if !foreground_eligible(
                    dispatch_window.is_visible().unwrap_or(false),
                    dispatch_window.is_minimized().unwrap_or(true),
                    dispatch_window.is_focused().unwrap_or(false),
                ) {
                    let _ = sender.send(Err("foreground_required"));
                } else if dispatch_cancellation.is_cancelled() {
                    let _ = sender.send(Err("stale_request"));
                } else {
                    let _ = sender.send(Ok(Geolocator::RequestAccessAsync()));
                }
            })
            .is_err()
        {
            return Ok(PublicStatus {
                permission: Permission::Unknown,
                availability: Availability::Unavailable,
            });
        }
        let dispatch_wait = deadline.saturating_duration_since(tokio::time::Instant::now());
        let received = tokio::select! {
            biased;
            _ = cancellation.cancelled() => return Err("stale_request"),
            result = tokio::time::timeout(dispatch_wait, receiver) => result,
        };
        let operation = match received {
            Ok(Ok(Ok(Ok(operation)))) => operation,
            Ok(Ok(Err(error))) => return Err(error),
            Ok(Ok(Ok(Err(_)))) | Ok(Err(_)) => {
                return Ok(PublicStatus {
                    permission: Permission::Unknown,
                    availability: Availability::Unavailable,
                })
            }
            Err(_) => {
                cancellation.cancel();
                return Ok(PublicStatus {
                    permission: Permission::Unknown,
                    availability: Availability::TimedOut,
                });
            }
        };
        let cancel_operation = operation.clone();
        let operation_wait = deadline.saturating_duration_since(tokio::time::Instant::now());
        let mut task = tokio::task::spawn_blocking(move || operation.get());
        let access = tokio::select! {
            biased;
            _ = cancellation.cancelled() => {
                let _ = cancel_operation.Cancel();
                task.abort();
                return Err("stale_request");
            }
            result = tokio::time::timeout(operation_wait, &mut task) => match result {
                Ok(Ok(Ok(value))) => value,
                Err(_) => {
                    let _ = cancel_operation.Cancel();
                    cancellation.cancel();
                    return Ok(PublicStatus { permission: Permission::Unknown, availability: Availability::TimedOut });
                }
                Ok(Err(_)) => return Ok(PublicStatus { permission: Permission::Unknown, availability: Availability::Unavailable }),
                Ok(Ok(Err(_))) => return Ok(PublicStatus { permission: Permission::Unknown, availability: Availability::Unavailable }),
            }
        };
        Ok(match access {
            GeolocationAccessStatus::Allowed => PublicStatus {
                permission: Permission::Granted,
                availability: location_status(),
            },
            GeolocationAccessStatus::Denied => PublicStatus {
                permission: Permission::Denied,
                availability: Availability::Unavailable,
            },
            _ => PublicStatus {
                permission: Permission::Unknown,
                availability: Availability::Unavailable,
            },
        })
    }

    fn location_status() -> Availability {
        let Ok(locator) = Geolocator::new() else {
            return Availability::Unavailable;
        };
        match locator.LocationStatus() {
            Ok(PositionStatus::Ready | PositionStatus::Initializing) => Availability::Available,
            Ok(PositionStatus::NotInitialized) => Availability::Unknown,
            Ok(_) | Err(_) => Availability::Unavailable,
        }
    }

    fn map_location_error(error: windows::core::Error) -> ReadOutcome {
        if error.code().0 == 0x80070005_u32 as i32 {
            ReadOutcome::Revoked
        } else {
            ReadOutcome::Unavailable
        }
    }

    pub async fn read(
        cancellation: tokio_util::sync::CancellationToken,
    ) -> Result<Fix, ReadOutcome> {
        let locator = Geolocator::new().map_err(map_location_error)?;
        match locator.LocationStatus().map_err(map_location_error)? {
            PositionStatus::Disabled => return Err(ReadOutcome::Revoked),
            PositionStatus::NotAvailable | PositionStatus::NoData => {
                return Err(ReadOutcome::Unavailable)
            }
            PositionStatus::NotInitialized
            | PositionStatus::Ready
            | PositionStatus::Initializing => {}
            _ => return Err(ReadOutcome::Unavailable),
        }
        let operation = locator
            .GetGeopositionAsyncWithAgeAndTimeout(
                TimeSpan {
                    Duration: (900.0 * TICKS_PER_SECOND) as i64,
                },
                TimeSpan {
                    Duration: (10.0 * TICKS_PER_SECOND) as i64,
                },
            )
            .map_err(map_location_error)?;
        let cancel_operation = operation.clone();
        let mut task = tokio::task::spawn_blocking(move || operation.get());
        let position = tokio::select! {
            biased;
            _ = cancellation.cancelled() => {
                let _ = cancel_operation.Cancel();
                task.abort();
                return Err(ReadOutcome::Unavailable);
            }
            result = tokio::time::timeout(std::time::Duration::from_secs(10), &mut task) => match result {
                Ok(Ok(Ok(value))) => value,
                Err(_) => {
                    let _ = cancel_operation.Cancel();
                    return Err(ReadOutcome::TimedOut);
                }
                Ok(Err(_)) => return Err(ReadOutcome::Unavailable),
                Ok(Ok(Err(error))) => return Err(map_location_error(error)),
            }
        };
        let coordinate = position
            .Coordinate()
            .map_err(|_| ReadOutcome::Unavailable)?;
        let point = coordinate
            .Point()
            .map_err(|_| ReadOutcome::Unavailable)?
            .Position()
            .map_err(|_| ReadOutcome::Unavailable)?;
        let timestamp: DateTime = coordinate
            .Timestamp()
            .map_err(|_| ReadOutcome::Unavailable)?;
        let observed_at =
            timestamp.UniversalTime as f64 / TICKS_PER_SECOND - WINDOWS_EPOCH_UNIX_SECONDS;
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| ReadOutcome::Unavailable)?
            .as_secs_f64();
        Fix {
            latitude: point.Latitude,
            longitude: point.Longitude,
            observed_at,
        }
        .validate(now)
    }
}

#[cfg(windows)]
pub use winrt::{read as read_current, request_access};

#[cfg(not(windows))]
pub async fn request_access(
    _window: &tauri::WebviewWindow,
    _cancellation: tokio_util::sync::CancellationToken,
) -> Result<PublicStatus, &'static str> {
    Ok(PublicStatus {
        permission: Permission::Unsupported,
        availability: Availability::Unsupported,
    })
}

#[cfg(not(windows))]
pub async fn read_current(
    _cancellation: tokio_util::sync::CancellationToken,
) -> Result<Fix, ReadOutcome> {
    Err(ReadOutcome::Unsupported)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn permission_prompt_requires_visible_focused_nonminimized_window() {
        assert!(foreground_eligible(true, false, true));
        assert!(!foreground_eligible(false, false, true));
        assert!(!foreground_eligible(true, true, true));
        assert!(!foreground_eligible(true, false, false));
    }

    #[test]
    fn preferences_revision_and_backend_generation_fence_cached_permission() {
        let state = LocationState::default();
        state.reset(3);
        assert!(state.accept_preferences(3, "instance", 1, true));
        let context = state.context().unwrap();
        assert!(state.set_status(
            &context,
            PublicStatus {
                permission: Permission::Granted,
                availability: Availability::Available
            }
        ));
        assert!(state.accept_preferences(3, "instance", 1, true));
        assert_eq!(state.status().permission, Permission::Granted);
        assert!(state.accept_preferences(3, "instance", 2, true));
        assert_eq!(state.status().permission, Permission::Unknown);
        assert!(!state.is_current(&context));
        let updated = state.context().unwrap();
        state.reset(4);
        assert!(!state.set_status(
            &updated,
            PublicStatus {
                permission: Permission::Granted,
                availability: Availability::Available
            }
        ));
    }

    #[test]
    fn revoke_then_regrant_same_revision_keeps_old_read_fenced() {
        let state = LocationState::default();
        state.reset(7);
        assert!(state.accept_preferences(7, "instance", 4, true));
        let context = state.context().unwrap();
        assert!(state.set_status(
            &context,
            PublicStatus {
                permission: Permission::Granted,
                availability: Availability::Available,
            }
        ));
        let old_read = state.cancellation_token().child_token();
        assert!(state.set_status(
            &context,
            PublicStatus {
                permission: Permission::Revoked,
                availability: Availability::Unavailable,
            }
        ));
        assert!(old_read.is_cancelled());
        assert!(state.set_status(
            &context,
            PublicStatus {
                permission: Permission::Granted,
                availability: Availability::Available,
            }
        ));
        assert!(state.is_current(&context));
        assert!(old_read.is_cancelled());
        assert!(!state.cancellation_token().is_cancelled());
    }

    #[test]
    fn fix_validation_enforces_ranges_and_fifteen_minute_freshness() {
        assert!(Fix {
            latitude: 90.0,
            longitude: -180.0,
            observed_at: 1000.0
        }
        .validate(1900.0)
        .is_ok());
        assert_eq!(
            Fix {
                latitude: 0.0,
                longitude: 0.0,
                observed_at: 999.0
            }
            .validate(1900.0),
            Err(ReadOutcome::Expired)
        );
        assert_eq!(
            Fix {
                latitude: 91.0,
                longitude: 0.0,
                observed_at: 1900.0
            }
            .validate(1900.0),
            Err(ReadOutcome::Unavailable)
        );
    }
}
