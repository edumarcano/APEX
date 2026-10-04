pub fn validate_external_url(raw: &str) -> Result<tauri::Url, &'static str> {
    if raw.is_empty() || raw.chars().any(char::is_control) || raw.trim() != raw {
        return Err("invalid_url");
    }
    let url = tauri::Url::parse(raw).map_err(|_| "invalid_url")?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err("invalid_url");
    }
    Ok(url)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn external_opening_accepts_only_credential_free_http_urls() {
        assert!(validate_external_url("https://example.com/path?q=1").is_ok());
        for rejected in [
            "file:///C:/private.txt",
            "javascript:alert(1)",
            "https://user:password@example.com/",
            "http://example.com/\n",
            " http://example.com/",
            "http://",
        ] {
            assert_eq!(
                validate_external_url(rejected),
                Err("invalid_url"),
                "{rejected}"
            );
        }
    }
}
