#![cfg_attr(debug_assertions, allow(dead_code))]

use std::path::Path;

const RUN_KEY: &str = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run";
const APPROVED_KEY: &str =
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run";
const ENTRY_NAME: &str = "APEX";
const ENABLED_APPROVAL: [u8; 12] = [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Reconciliation {
    pub actual_enabled: Option<bool>,
    pub error_code: Option<&'static str>,
}

pub fn expected_command_line(executable: &Path) -> Result<String, &'static str> {
    let executable = executable.to_str().ok_or("autostart_path_invalid")?;
    if executable.contains('"') || executable.chars().any(char::is_control) {
        return Err("autostart_path_invalid");
    }
    Ok(format!("\"{executable}\" --autostart"))
}

pub fn command_matches(actual: &str, expected: &str) -> bool {
    actual == expected
}

pub fn task_manager_allows(bytes: Option<&[u8]>) -> Result<bool, &'static str> {
    let Some(bytes) = bytes else { return Ok(true) };
    if bytes.len() != 12 {
        return Err("autostart_read_failed");
    }
    match bytes[0] {
        2 | 6 => Ok(true),
        3 | 7 => Ok(false),
        _ => Err("autostart_read_failed"),
    }
}

#[cfg(windows)]
pub fn reconcile(requested: Option<bool>) -> Reconciliation {
    use windows_registry::{Type, CURRENT_USER};

    let executable = match std::env::current_exe().and_then(|path| path.canonicalize()) {
        Ok(path) => path,
        Err(_) => {
            return Reconciliation {
                actual_enabled: None,
                error_code: Some("autostart_path_invalid"),
            }
        }
    };
    let expected = match expected_command_line(&executable) {
        Ok(expected) => expected,
        Err(error) => {
            return Reconciliation {
                actual_enabled: None,
                error_code: Some(error),
            }
        }
    };

    let mut error = None;
    if let Some(enable) = requested {
        if enable {
            match CURRENT_USER
                .create(RUN_KEY)
                .and_then(|key| key.set_string(ENTRY_NAME, &expected))
            {
                Ok(()) => match CURRENT_USER
                    .create(APPROVED_KEY)
                    .and_then(|key| key.set_bytes(ENTRY_NAME, Type::Bytes, &ENABLED_APPROVAL))
                {
                    Ok(()) => {}
                    Err(_) => error = Some("autostart_failed"),
                },
                Err(_) => error = Some("autostart_failed"),
            }
        } else {
            if let Err(result) = remove_value_if_present(RUN_KEY) {
                error = Some(result);
            }
            if let Err(result) = remove_value_if_present(APPROVED_KEY) {
                if error.is_none() {
                    error = Some(result);
                }
            }
        }
    }

    let actual_enabled = read_actual(&expected);
    if requested.is_some_and(|wanted| actual_enabled != Some(wanted)) && error.is_none() {
        error = Some("autostart_mismatch");
    }
    if actual_enabled.is_none() && error.is_none() {
        error = Some("autostart_read_failed");
    }
    Reconciliation {
        actual_enabled,
        error_code: error,
    }
}

#[cfg(windows)]
fn remove_value_if_present(key_path: &str) -> Result<(), &'static str> {
    use windows_registry::CURRENT_USER;
    match CURRENT_USER.options().write().open(key_path) {
        Ok(key) => match key.remove_value(ENTRY_NAME) {
            Ok(()) => Ok(()),
            Err(error) if is_not_found(error.code().0 as u32) => Ok(()),
            Err(_) => Err("autostart_failed"),
        },
        Err(error) if is_not_found(error.code().0 as u32) => Ok(()),
        Err(_) => Err("autostart_failed"),
    }
}

#[cfg(windows)]
fn read_actual(expected: &str) -> Option<bool> {
    use windows_registry::CURRENT_USER;
    let run = match CURRENT_USER.open(RUN_KEY) {
        Ok(key) => match key.get_string(ENTRY_NAME) {
            Ok(command) => command,
            Err(error) if is_not_found(error.code().0 as u32) => return Some(false),
            Err(_) => return None,
        },
        Err(error) if is_not_found(error.code().0 as u32) => return Some(false),
        Err(_) => return None,
    };
    if !command_matches(&run, expected) {
        return Some(false);
    }
    let approval = match CURRENT_USER.open(APPROVED_KEY) {
        Ok(key) => match key.get_value(ENTRY_NAME) {
            Ok(value) if value.ty() == windows_registry::Type::Bytes => {
                Some(value.as_ref().to_vec())
            }
            Ok(_) => return None,
            Err(error) if is_not_found(error.code().0 as u32) => None,
            Err(_) => return None,
        },
        Err(error) if is_not_found(error.code().0 as u32) => None,
        Err(_) => return None,
    };
    task_manager_allows(approval.as_deref()).ok()
}

#[cfg(windows)]
fn is_not_found(code: u32) -> bool {
    code == 0x8007_0002
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn startup_entry_is_quoted_and_bound_to_the_fixed_flag_and_executable() {
        let expected = expected_command_line(Path::new(r"C:\Program Files\APEX\apex.exe")).unwrap();
        assert_eq!(expected, r#""C:\Program Files\APEX\apex.exe" --autostart"#);
        assert!(command_matches(&expected, &expected));
        assert!(!command_matches(
            r#""C:\Old\apex.exe" --autostart"#,
            &expected
        ));
        assert!(!command_matches(
            r#""C:\Program Files\APEX\apex.exe" --untrusted"#,
            &expected
        ));
    }

    #[test]
    fn task_manager_approval_must_be_enabled_or_absent() {
        assert_eq!(task_manager_allows(None), Ok(true));
        assert_eq!(task_manager_allows(Some(&ENABLED_APPROVAL)), Ok(true));
        assert_eq!(
            task_manager_allows(Some(&[3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])),
            Ok(false)
        );
        assert_eq!(
            task_manager_allows(Some(&[7, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])),
            Ok(false)
        );
        assert_eq!(
            task_manager_allows(Some(&[6, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])),
            Ok(true)
        );
        assert_eq!(
            task_manager_allows(Some(&[1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])),
            Err("autostart_read_failed")
        );
        assert_eq!(
            task_manager_allows(Some(&[1, 2])),
            Err("autostart_read_failed")
        );
    }
}
