fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "desktop_setup_status",
            "desktop_import_pick_source",
            "desktop_import_preview",
            "desktop_import_commit",
            "desktop_fresh_start",
            "desktop_import_recover",
            "desktop_backend_status",
            "desktop_backend_retry",
            "desktop_quit",
            "desktop_services_status",
            "desktop_services_retry",
            "desktop_open_external",
            "desktop_write_clipboard",
            "desktop_check_location_permission",
        ]),
    ))
    .expect("failed to build the Tauri application manifest")
}
