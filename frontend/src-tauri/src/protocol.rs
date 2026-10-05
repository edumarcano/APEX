use serde::Deserialize;
use serde_json::Value;
#[cfg(test)]
use std::io::{BufRead, BufReader, Read};

pub const MAX_FRAME_BYTES: usize = 64 * 1024;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Envelope {
    pub version: u8,
    #[serde(rename = "type")]
    pub kind: String,
    pub request_id: String,
    pub payload: Value,
}

pub fn decode(bytes: &[u8]) -> Result<Envelope, &'static str> {
    if bytes.len() > MAX_FRAME_BYTES
        || !bytes.ends_with(b"\n")
        || bytes[..bytes.len().saturating_sub(1)].contains(&b'\n')
        || bytes.contains(&b'\r')
    {
        return Err("protocol_error");
    }
    let frame: Envelope =
        serde_json::from_slice(&bytes[..bytes.len() - 1]).map_err(|_| "protocol_error")?;
    if frame.version != 1
        || frame.request_id.is_empty()
        || frame.request_id.len() > 128
        || !frame
            .request_id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._:-".contains(&b))
    {
        return Err("protocol_error");
    }
    validate_payload(&frame)?;
    Ok(frame)
}

fn validate_payload(frame: &Envelope) -> Result<(), &'static str> {
    let payload = frame.payload.as_object().ok_or("protocol_error")?;
    match frame.kind.as_str() {
        "starting" | "ready" => {
            const KEYS: &[&str] = &[
                "app_id",
                "app_version",
                "build_id",
                "instance_id",
                "pid",
                "hosting_mode",
                "launch_id",
                "data_root_fingerprint",
                "shutdown_timeout_seconds",
            ];
            if payload.len() != KEYS.len() || KEYS.iter().any(|key| !payload.contains_key(*key)) {
                return Err("protocol_error");
            }
        }
        "error" => {
            if payload.len() != 1 {
                return Err("protocol_error");
            }
            let code = payload
                .get("code")
                .and_then(Value::as_str)
                .ok_or("protocol_error")?;
            if ![
                "startup_failed",
                "port_in_use",
                "profile_in_use",
                "protocol_error",
                "shutdown_timeout",
                "shutdown_failed",
                "child_failed",
                "internal_error",
            ]
            .contains(&code)
            {
                return Err("protocol_error");
            }
        }
        "stopping" | "stopped" => {
            if !payload.is_empty() {
                return Err("protocol_error");
            }
        }
        "completion" => {
            if payload.len() != 3
                || !payload.contains_key("instance_id")
                || !payload.contains_key("run_id")
                || !payload.contains_key("status")
            {
                return Err("protocol_error");
            }
            if !["completed", "failed", "cancelled"]
                .contains(&payload.get("status").and_then(Value::as_str).unwrap_or(""))
            {
                return Err("protocol_error");
            }
            if uuid::Uuid::parse_str(
                payload
                    .get("instance_id")
                    .and_then(Value::as_str)
                    .unwrap_or(""),
            )
            .is_err()
                || uuid::Uuid::parse_str(
                    payload.get("run_id").and_then(Value::as_str).unwrap_or(""),
                )
                .is_err()
            {
                return Err("protocol_error");
            }
        }
        "desktop_preferences" => {
            if payload.len() != 3
                || !payload.contains_key("instance_id")
                || !payload.contains_key("launch_on_startup")
                || !payload.contains_key("completion_notifications")
                || payload
                    .get("instance_id")
                    .and_then(Value::as_str)
                    .and_then(|value| uuid::Uuid::parse_str(value).ok())
                    .is_none()
                || payload
                    .get("launch_on_startup")
                    .and_then(Value::as_bool)
                    .is_none()
                || payload
                    .get("completion_notifications")
                    .and_then(Value::as_bool)
                    .is_none()
                || !valid_desktop_request(&frame.request_id)
            {
                return Err("protocol_error");
            }
        }
        "device_preferences" => {
            if payload.len() != 3
                || uuid_value(payload.get("instance_id")).is_none()
                || positive_u64(payload.get("revision")).is_none()
                || payload
                    .get("location_enabled")
                    .and_then(Value::as_bool)
                    .is_none()
                || !valid_sequence(&frame.request_id, "device-prefs:")
                || frame
                    .request_id
                    .strip_prefix("device-prefs:")
                    .and_then(|value| value.parse::<u64>().ok())
                    != positive_u64(payload.get("revision"))
            {
                return Err("protocol_error");
            }
        }
        "device_request" => {
            if payload.len() != 2
                || uuid_value(payload.get("instance_id")).is_none()
                || positive_u64(payload.get("revision")).is_none()
                || !valid_sequence(&frame.request_id, "device:")
            {
                return Err("protocol_error");
            }
        }
        "device_result" => {
            let outcome = payload.get("outcome").and_then(Value::as_str);
            let valid_fix = match (outcome, payload.get("fix")) {
                (Some("ok"), Some(fix)) => valid_fix(fix),
                (
                    Some(
                        "permission_required"
                        | "denied"
                        | "revoked"
                        | "unavailable"
                        | "timed_out"
                        | "expired"
                        | "unsupported",
                    ),
                    Some(Value::Null),
                ) => true,
                _ => false,
            };
            if payload.len() != 4
                || uuid_value(payload.get("instance_id")).is_none()
                || positive_u64(payload.get("revision")).is_none()
                || !valid_fix
                || !valid_sequence(&frame.request_id, "device:")
            {
                return Err("protocol_error");
            }
        }
        "device_state" => {
            let permission = payload.get("permission").and_then(Value::as_str);
            let availability = payload.get("availability").and_then(Value::as_str);
            if payload.len() != 4
                || uuid_value(payload.get("instance_id")).is_none()
                || positive_u64(payload.get("revision")).is_none()
                || !["unknown", "granted", "denied", "revoked", "unsupported"]
                    .contains(&permission.unwrap_or(""))
                || ![
                    "unknown",
                    "available",
                    "unavailable",
                    "timed_out",
                    "unsupported",
                ]
                .contains(&availability.unwrap_or(""))
                || !valid_sequence(&frame.request_id, "device-state:")
            {
                return Err("protocol_error");
            }
        }
        _ => return Err("protocol_error"),
    }
    Ok(())
}

fn uuid_value(value: Option<&Value>) -> Option<&str> {
    let value = value?.as_str()?;
    uuid::Uuid::parse_str(value).ok().map(|_| value)
}

fn positive_u64(value: Option<&Value>) -> Option<u64> {
    value?.as_u64().filter(|value| *value > 0)
}

fn valid_sequence(request_id: &str, prefix: &str) -> bool {
    let Some(value) = request_id.strip_prefix(prefix) else {
        return false;
    };
    value
        .as_bytes()
        .first()
        .is_some_and(|first| (b'1'..=b'9').contains(first))
        && value.bytes().all(|byte| byte.is_ascii_digit())
        && value.parse::<u64>().is_ok()
}

fn valid_fix(value: &Value) -> bool {
    let Some(fix) = value.as_object() else {
        return false;
    };
    if fix.len() != 3 {
        return false;
    }
    let latitude = fix.get("latitude").and_then(Value::as_f64);
    let longitude = fix.get("longitude").and_then(Value::as_f64);
    let observed_at = fix.get("observed_at").and_then(Value::as_f64);
    latitude.is_some_and(|v| v.is_finite() && (-90.0..=90.0).contains(&v))
        && longitude.is_some_and(|v| v.is_finite() && (-180.0..=180.0).contains(&v))
        && observed_at.is_some_and(f64::is_finite)
}

fn valid_desktop_request(request_id: &str) -> bool {
    let Some(value) = request_id.strip_prefix("desktop:") else {
        return false;
    };
    value
        .as_bytes()
        .first()
        .is_some_and(|first| (b'1'..=b'9').contains(first))
        && value.bytes().all(|byte| byte.is_ascii_digit())
        && value.parse::<u64>().is_ok()
}

#[cfg(test)]
pub fn read_frame<R: Read>(reader: &mut BufReader<R>) -> Result<Envelope, &'static str> {
    let mut bytes = Vec::with_capacity(512);
    reader
        .take((MAX_FRAME_BYTES + 1) as u64)
        .read_until(b'\n', &mut bytes)
        .map_err(|_| "protocol_error")?;
    if bytes.is_empty()
        || bytes.len() > MAX_FRAME_BYTES
        || !bytes.ends_with(b"\n")
        || bytes[..bytes.len() - 1].contains(&b'\n')
        || bytes.contains(&b'\r')
    {
        return Err("protocol_error");
    }
    decode(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    fn parse(input: &[u8]) -> Result<Envelope, &'static str> {
        read_frame(&mut BufReader::new(Cursor::new(input)))
    }

    #[test]
    fn accepts_one_bounded_v1_control_record() {
        let valid =
            b"{\"version\":1,\"type\":\"stopped\",\"request_id\":\"shutdown:2\",\"payload\":{}}\n";
        assert_eq!(parse(valid).unwrap().kind, "stopped");
    }

    #[test]
    fn rejects_unbounded_truncated_and_extra_fields() {
        assert!(parse(&vec![b'a'; MAX_FRAME_BYTES + 1]).is_err());
        assert!(
            parse(b"{\"version\":1,\"type\":\"stopped\",\"request_id\":\"x\",\"payload\":{}}")
                .is_err()
        );
        assert!(parse(b"{\"version\":1,\"type\":\"stopped\",\"request_id\":\"x\",\"payload\":{},\"extra\":1}\n").is_err());
    }

    #[test]
    fn desktop_preference_frames_require_exact_payload_and_positive_sequence() {
        let instance = "581aeb4b-e90e-40d5-9708-1b1fb857fa26";
        let frame = format!(
            r#"{{"version":1,"type":"desktop_preferences","request_id":"desktop:1","payload":{{"instance_id":"{instance}","launch_on_startup":true,"completion_notifications":false}}}}"#
        );
        assert_eq!(
            decode(format!("{frame}\n").as_bytes()).unwrap().kind,
            "desktop_preferences"
        );
        for request in ["desktop:0", "desktop:01", "desktop:-1", "start:1"] {
            let bad = frame.replace("desktop:1", request);
            assert_eq!(
                decode(format!("{bad}\n").as_bytes()).unwrap_err(),
                "protocol_error"
            );
        }
        let bad_payload = frame.replace(
            "\"completion_notifications\":false",
            "\"completion_notifications\":false,\"extra\":1",
        );
        assert_eq!(
            decode(format!("{bad_payload}\n").as_bytes()).unwrap_err(),
            "protocol_error"
        );
    }

    #[test]
    fn device_location_frames_require_exact_identity_revision_and_coordinate_shapes() {
        let instance = "581aeb4b-e90e-40d5-9708-1b1fb857fa26";
        let frames = [
            format!(
                r#"{{"version":1,"type":"device_preferences","request_id":"device-prefs:1","payload":{{"instance_id":"{instance}","revision":1,"location_enabled":true}}}}"#
            ),
            format!(
                r#"{{"version":1,"type":"device_request","request_id":"device:1","payload":{{"instance_id":"{instance}","revision":1}}}}"#
            ),
            format!(
                r#"{{"version":1,"type":"device_state","request_id":"device-state:1","payload":{{"instance_id":"{instance}","revision":1,"permission":"granted","availability":"available"}}}}"#
            ),
            format!(
                r#"{{"version":1,"type":"device_result","request_id":"device:1","payload":{{"instance_id":"{instance}","revision":1,"outcome":"ok","fix":{{"latitude":1.25,"longitude":-2.5,"observed_at":1800000000.0}}}}}}"#
            ),
            format!(
                r#"{{"version":1,"type":"device_result","request_id":"device:2","payload":{{"instance_id":"{instance}","revision":1,"outcome":"unavailable","fix":null}}}}"#
            ),
        ];
        for frame in frames {
            assert!(
                decode(format!("{frame}\n").as_bytes()).is_ok(),
                "valid protocol frame was rejected"
            );
        }
        let bad = [
            format!(
                r#"{{"version":1,"type":"device_preferences","request_id":"device-prefs:01","payload":{{"instance_id":"{instance}","revision":1,"location_enabled":true}}}}"#
            ),
            format!(
                r#"{{"version":1,"type":"device_request","request_id":"device:1","payload":{{"instance_id":"{instance}","revision":0}}}}"#
            ),
            format!(
                r#"{{"version":1,"type":"device_state","request_id":"device-state:1","payload":{{"instance_id":"{instance}","revision":1,"permission":"granted","availability":"available","latitude":1}}}}"#
            ),
            format!(
                r#"{{"version":1,"type":"device_result","request_id":"device:1","payload":{{"instance_id":"{instance}","revision":1,"outcome":"unavailable","fix":{{}}}}}}"#
            ),
            format!(
                r#"{{"version":1,"type":"device_result","request_id":"device:1","payload":{{"instance_id":"{instance}","revision":1,"outcome":"ok","fix":{{"latitude":91,"longitude":0,"observed_at":1}}}}}}"#
            ),
        ];
        for frame in bad {
            assert_eq!(
                decode(format!("{frame}\n").as_bytes()).unwrap_err(),
                "protocol_error"
            );
        }
    }
}
