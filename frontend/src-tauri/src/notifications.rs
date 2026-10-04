use crate::services::{NotificationSetting, NotificationSettingProbe};

const HRESULT_ELEMENT_NOT_FOUND: u32 = 0x8007_0490;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CompletionAttempt {
    pub probe: NotificationSettingProbe,
}

pub fn classify_setting_result(
    result: Result<NotificationSetting, u32>,
) -> Result<NotificationSettingProbe, &'static str> {
    match result {
        Ok(setting) => Ok(NotificationSettingProbe::Known(setting)),
        Err(HRESULT_ELEMENT_NOT_FOUND) => Ok(NotificationSettingProbe::IdentityNotFound),
        Err(_) => Err("notification_unavailable"),
    }
}

fn may_attempt_show(probe: &NotificationSettingProbe) -> bool {
    matches!(
        probe,
        NotificationSettingProbe::IdentityNotFound
            | NotificationSettingProbe::Known(NotificationSetting::Enabled)
    )
}

const COMPLETION_TITLE: &str = "APEX";
const COMPLETION_BODY: &str = "An APEX run has completed.";

fn completion_xml() -> String {
    format!(
        "<toast><visual><binding template=\"ToastGeneric\"><text>{COMPLETION_TITLE}</text><text>{COMPLETION_BODY}</text></binding></visual></toast>"
    )
}

pub fn eligible_when_hidden_or_minimized(is_visible: bool, is_minimized: bool) -> bool {
    !is_visible || is_minimized
}

#[cfg(windows)]
struct Apartment;

#[cfg(windows)]
impl Apartment {
    fn initialize() -> windows::core::Result<Self> {
        unsafe {
            windows::Win32::System::WinRT::RoInitialize(
                windows::Win32::System::WinRT::RO_INIT_MULTITHREADED,
            )?;
        }
        Ok(Self)
    }
}

#[cfg(windows)]
impl Drop for Apartment {
    fn drop(&mut self) {
        unsafe { windows::Win32::System::WinRT::RoUninitialize() };
    }
}

#[cfg(windows)]
pub fn query_setting() -> Result<NotificationSettingProbe, &'static str> {
    use windows::{core::HSTRING, UI::Notifications::ToastNotificationManager};
    let _apartment = Apartment::initialize().map_err(|_| "notification_unavailable")?;
    let aumid = HSTRING::from("com.edumarcano.apex");
    let notifier = ToastNotificationManager::CreateToastNotifierWithId(&aumid)
        .map_err(|_| "notification_unavailable")?;
    classify_setting_result(
        notifier
            .Setting()
            .map(map_os_setting)
            .map_err(|error| error.code().0 as u32),
    )
}

#[cfg(windows)]
fn map_os_setting(setting: windows::UI::Notifications::NotificationSetting) -> NotificationSetting {
    use windows::UI::Notifications::NotificationSetting as OsSetting;
    match setting {
        OsSetting::Enabled => NotificationSetting::Enabled,
        OsSetting::DisabledForApplication => NotificationSetting::DisabledApp,
        OsSetting::DisabledForUser => NotificationSetting::DisabledUser,
        OsSetting::DisabledByGroupPolicy => NotificationSetting::DisabledPolicy,
        OsSetting::DisabledByManifest => NotificationSetting::DisabledManifest,
        _ => NotificationSetting::Unknown,
    }
}

#[cfg(not(windows))]
pub fn query_setting() -> Result<NotificationSettingProbe, &'static str> {
    Ok(NotificationSettingProbe::Known(
        NotificationSetting::Unavailable,
    ))
}

#[cfg(windows)]
pub fn show_completion() -> Result<CompletionAttempt, &'static str> {
    use windows::{
        core::HSTRING,
        Data::Xml::Dom::XmlDocument,
        UI::Notifications::{ToastNotification, ToastNotificationManager},
    };
    let _apartment = Apartment::initialize().map_err(|_| "notification_failed")?;
    let aumid = HSTRING::from("com.edumarcano.apex");
    let notifier = ToastNotificationManager::CreateToastNotifierWithId(&aumid)
        .map_err(|_| "notification_failed")?;
    let probe = classify_setting_result(
        notifier
            .Setting()
            .map(map_os_setting)
            .map_err(|error| error.code().0 as u32),
    )?;
    if !may_attempt_show(&probe) {
        return Ok(CompletionAttempt { probe });
    }
    let xml = XmlDocument::new().map_err(|_| "notification_failed")?;
    let xml_string = completion_xml();
    let xml_text = HSTRING::from(xml_string);
    xml.LoadXml(&xml_text).map_err(|_| "notification_failed")?;
    let toast =
        ToastNotification::CreateToastNotification(&xml).map_err(|_| "notification_failed")?;
    notifier.Show(&toast).map_err(|_| "notification_failed")?;
    Ok(CompletionAttempt { probe })
}

#[cfg(not(windows))]
pub fn show_completion() -> Result<CompletionAttempt, &'static str> {
    Err("notification_unavailable")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn notification_status_never_claims_submission_is_delivery() {
        assert_ne!(NotificationSetting::Unknown, NotificationSetting::Enabled);
        assert_ne!(
            NotificationSetting::Unavailable,
            NotificationSetting::Enabled
        );
    }

    #[test]
    fn completion_toast_uses_the_fixed_generic_copy() {
        assert_eq!(COMPLETION_TITLE, "APEX");
        assert_eq!(COMPLETION_BODY, "An APEX run has completed.");
        assert_eq!(
            completion_xml(),
            "<toast><visual><binding template=\"ToastGeneric\"><text>APEX</text><text>An APEX run has completed.</text></binding></visual></toast>"
        );
    }

    #[test]
    fn completion_notifications_are_suppressed_while_window_is_visible() {
        assert!(!eligible_when_hidden_or_minimized(true, false));
        assert!(eligible_when_hidden_or_minimized(false, false));
        assert!(eligible_when_hidden_or_minimized(true, true));
    }

    #[test]
    fn only_the_missing_identity_hresult_uses_the_first_submission_path() {
        assert_eq!(
            classify_setting_result(Err(HRESULT_ELEMENT_NOT_FOUND)),
            Ok(NotificationSettingProbe::IdentityNotFound)
        );
        assert_eq!(
            classify_setting_result(Err(0x8007_0005)),
            Err("notification_unavailable")
        );
        assert_eq!(
            classify_setting_result(Ok(NotificationSetting::Unknown)),
            Ok(NotificationSettingProbe::Known(
                NotificationSetting::Unknown
            ))
        );
        assert!(may_attempt_show(
            &NotificationSettingProbe::IdentityNotFound
        ));
        assert!(may_attempt_show(&NotificationSettingProbe::Known(
            NotificationSetting::Enabled
        )));
        for setting in [
            NotificationSetting::Unknown,
            NotificationSetting::DisabledApp,
            NotificationSetting::DisabledUser,
            NotificationSetting::DisabledPolicy,
            NotificationSetting::DisabledManifest,
            NotificationSetting::Unavailable,
        ] {
            assert!(!may_attempt_show(&NotificationSettingProbe::Known(setting)));
        }
    }
}
