pub fn is_trusted_url(raw: &str, debug_build: bool) -> bool {
    let Ok(url) = tauri::Url::parse(raw) else {
        return false;
    };
    let native = url.scheme() == "http"
        && url.host_str() == Some("tauri.localhost")
        && url.port().is_none()
        && url.username().is_empty()
        && url.password().is_none();
    let dev = debug_build
        && url.origin().ascii_serialization() == "http://127.0.0.1:5173"
        && url.username().is_empty()
        && url.password().is_none();
    native || dev
}

pub fn is_trusted_caller(label: &str, url: &str, debug_build: bool) -> bool {
    label == "main" && is_trusted_url(url, debug_build)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_navigation_requires_the_exact_custom_origin() {
        assert!(is_trusted_url("http://tauri.localhost/index.html", false));
        assert!(!is_trusted_url("https://tauri.localhost/index.html", false));
        assert!(!is_trusted_url(
            "http://tauri.localhost:8080/index.html",
            false
        ));
        assert!(!is_trusted_url(
            "http://user@tauri.localhost/index.html",
            false
        ));
        assert!(!is_trusted_url("https://example.com/", false));
    }

    #[test]
    fn remote_development_navigation_is_exact_and_debug_only() {
        assert!(is_trusted_url("http://127.0.0.1:5173/src/main.tsx", true));
        assert!(!is_trusted_url("http://127.0.0.1:5173/", false));
        assert!(!is_trusted_url("http://localhost:5173/", true));
        assert!(!is_trusted_url("http://127.0.0.1:5174/", true));
    }

    #[test]
    fn only_the_main_webview_can_call_desktop_commands() {
        assert!(is_trusted_caller(
            "main",
            "http://tauri.localhost/index.html",
            false
        ));
        assert!(!is_trusted_caller(
            "other",
            "http://tauri.localhost/index.html",
            false
        ));
        assert!(!is_trusted_caller("main", "http://example.com/", true));
    }
}
