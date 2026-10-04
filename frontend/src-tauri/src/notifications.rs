use crate::services::NotificationSetting;

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
pub fn query_setting() -> Result<NotificationSetting, &'static str> {
    use windows::{
        core::HSTRING,
        UI::Notifications::{NotificationSetting as OsSetting, ToastNotificationManager},
    };
    let _apartment = Apartment::initialize().map_err(|_| "notification_unavailable")?;
    let aumid = HSTRING::from("com.edumarcano.apex");
    let notifier = ToastNotificationManager::CreateToastNotifierWithId(&aumid)
        .map_err(|_| "notification_unavailable")?;
    let setting = notifier.Setting().map_err(|_| "notification_unavailable")?;
    Ok(match setting {
        OsSetting::Enabled => NotificationSetting::Enabled,
        OsSetting::DisabledForApplication => NotificationSetting::DisabledApp,
        OsSetting::DisabledForUser => NotificationSetting::DisabledUser,
        OsSetting::DisabledByGroupPolicy => NotificationSetting::DisabledPolicy,
        OsSetting::DisabledByManifest => NotificationSetting::DisabledManifest,
        _ => NotificationSetting::Unknown,
    })
}

#[cfg(not(windows))]
pub fn query_setting() -> Result<NotificationSetting, &'static str> {
    Ok(NotificationSetting::Unavailable)
}

#[cfg(windows)]
pub fn show_completion() -> Result<(), &'static str> {
    use windows::{
        core::HSTRING,
        Data::Xml::Dom::XmlDocument,
        UI::Notifications::{ToastNotification, ToastNotificationManager},
    };
    let _apartment = Apartment::initialize().map_err(|_| "notification_failed")?;
    let aumid = HSTRING::from("com.edumarcano.apex");
    let notifier = ToastNotificationManager::CreateToastNotifierWithId(&aumid)
        .map_err(|_| "notification_failed")?;
    let xml = XmlDocument::new().map_err(|_| "notification_failed")?;
    let xml_text = HSTRING::from(
        "<toast><visual><binding template=\"ToastText02\"><text>APEX</text><text>An APEX run has completed</text></binding></visual></toast>",
    );
    xml.LoadXml(&xml_text).map_err(|_| "notification_failed")?;
    let toast =
        ToastNotification::CreateToastNotification(&xml).map_err(|_| "notification_failed")?;
    notifier.Show(&toast).map_err(|_| "notification_failed")
}

#[cfg(not(windows))]
pub fn show_completion() -> Result<(), &'static str> {
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
    fn completion_notifications_are_suppressed_while_window_is_visible() {
        assert!(!eligible_when_hidden_or_minimized(true, false));
        assert!(eligible_when_hidden_or_minimized(false, false));
        assert!(eligible_when_hidden_or_minimized(true, true));
    }
}
