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
        _ => return Err("protocol_error"),
    }
    Ok(())
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
}
