# NSIS template provenance

`installer.nsi` is based on the Tauri v2.12.1 template at [`installer.nsi`](https://github.com/tauri-apps/tauri/blob/tauri-cli-v2.12.1/crates/tauri-bundler/src/bundle/windows/nsis/installer.nsi).

- Upstream repository: `tauri-apps/tauri`
- Tag: `tauri-cli-v2.12.1`
- Upstream file SHA-256: `DABED59013B1D78B879A1A85BC7F2EED2993B33A9A90CDABE5946DE3D3950597`
- Upstream project license: MIT OR Apache-2.0
- Local file: `installer.nsi` is the upstream template with the APEX-specific changes described below.

The template pins current-user installs to `%LOCALAPPDATA%\Programs\APEX`, rejects `/D` and conflicting restored paths, checks every existing path component for reparse points, and fails closed if APEX or its standalone backend is running. It asks the user to quit and retry; it never requests process termination. It removes the directory selector and app-data deletion flow. Uninstall removes the packaged files, owned shortcuts and registration, then performs only non-recursive directory cleanup so unrelated files and APEX data remain.

The unmodified downloaded source is retained as `installer.nsi.upstream` so the local derivation can be checked byte-for-byte against the recorded hash.
