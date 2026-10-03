fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "desktop_backend_status",
            "desktop_backend_retry",
            "desktop_quit",
        ]),
    ))
    .expect("failed to build the Tauri application manifest")
}
