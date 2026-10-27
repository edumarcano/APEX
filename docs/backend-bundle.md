# Windows backend bundle

The Windows x64 backend bundle contains the existing FastAPI backend and CLI for use without a source checkout. The desktop shell packages the same backend runtime alongside its native executable; FastAPI and the CLI remain independent of the shell. The package is built from the locked Python runtime plus every project extra, and includes its configuration defaults, demo fixtures, and documentation resources.

## Build

Build from the repository root on Windows x64 with Python 3.14.7 x64 and uv 0.12.3. The build creates a one-folder distribution at `dist/backend-bundle` and uses the versions of PyInstaller and its hooks pinned by the build lock.

```powershell
uv sync --locked --all-extras --python 3.14.7
uv run --locked --all-extras --python 3.14.7 python scripts/build_backend_bundle.py --with-smoke-probe --reproducibility-check
```

The `--with-smoke-probe` flag builds a validation-only executable under `build/backend-bundle/smoke-probe/`. That probe is not copied into the distributable folder. `--reproducibility-check` rebuilds with the same seed and compares the resulting manifest. Omit either flag when that check is not needed.

Build inputs use the source commit and `SOURCE_DATE_EPOCH`; the build manifest records the inputs and packaged files. A license or source-material inventory failure stops the build. The bundle stages APEX's MIT license, Python's interpreter license, the PyInstaller bootloader exception, and original license/notice files from the locked runtime distributions. It also includes corresponding-source archives for GPL components and pygame-ce's LGPL source distribution in `licenses/source-material/`. The staged `THIRD_PARTY_NOTICES.md` lists each component version and links to its material.

The all-extras runtime contains Kokoro's `phonemizer-fork` and `espeakng-loader` dependencies. The latter carries eSpeak NG native files. Their source revisions and archives are pinned and checked during notice staging; do not omit those files from the final bundle. The pygame-ce sdist and its carried license texts are included. Exact DLL-to-source revision mappings are verified for its libxmp and WavPack DLLs; other bundled codec DLLs have their license texts included from that release but their exact upstream build revisions are not independently mapped yet. The evidence notes are [in the APEX repository](https://github.com/edumarcano/APEX/blob/main/packaging/windows/source-material/README.md); a built bundle also includes them at `licenses/source-material/README.md`.

## Run the packaged backend and CLI

From the bundle directory, start the API on loopback:

```powershell
.\apex-backend.exe serve --standalone
```

In a second terminal, use the packaged CLI against that running backend:

```powershell
.\apex.exe --help
.\apex.exe status
```

The CLI is a client and does not start the API. Keep the backend process running while using it. The packaged programs do not read credentials from the build checkout; configure credentials through the documented runtime settings and `.env` behavior for the selected data profile.

## Smoke validation

Run the packaged smoke checks after building:

```powershell
uv run --locked --all-extras --python 3.14.7 python scripts/smoke_backend_bundle.py `
  --bundle dist/backend-bundle `
  --probe build/backend-bundle/smoke-probe/apex-bundle-probe.exe `
  --report build/backend-bundle/smoke-report.json
```

The smoke checks cover backend startup, authentication imports, retrieval, audio export, and worker dispatch. Supply external resources when you want the semantic retrieval and Kokoro asset checks:

```powershell
uv run --locked --all-extras --python 3.14.7 python scripts/smoke_backend_bundle.py `
  --bundle dist/backend-bundle `
  --probe build/backend-bundle/smoke-probe/apex-bundle-probe.exe `
  --fastembed-cache C:\models\fastembed `
  --kokoro-assets C:\models\kokoro
```

The Kokoro directory must contain `kokoro-v1.0.onnx` and `voices-v1.0.bin`. Add `--strict` to fail when any acceptance check remains unverified. Model weights are intentionally excluded from the bundle. A run without the external files can verify packaged startup and fallback behavior, but the corresponding model checks remain unverified.

The frozen probe can control the same suite without Python or `uv` on the target machine:

```powershell
build\backend-bundle\smoke-probe\apex-bundle-probe.exe --run-suite `
  --bundle dist\backend-bundle `
  --fastembed-cache C:\models\fastembed `
  --kokoro-assets C:\models\kokoro `
  --strict `
  --report build\backend-bundle\smoke-report.json
```

The suite relocates the packaged programs under a Unicode path, runs them from an unrelated working directory, and sanitizes child `PATH` values. It checks the frozen bundle and separate probe; it does not establish VM or clean-install evidence. The distribution lifecycle smoke passes `--inference-timeout 600` to its strict frozen backend suite, allowing bounded cold semantic inference in CI and installed test profiles. Direct `--run-suite` invocations keep the suite's configurable timeout.

## Included and excluded files

The bundle contains the backend runtime, standalone CLI, default configuration, demo JSON fixtures, and the documentation the backend needs at runtime. It excludes model weights, provider credentials, databases, operator configuration, caches, and other personal data. Mutable installed data defaults to `%LOCALAPPDATA%\APEX`; see [runtime paths](architecture.md#runtime-resource-and-data-paths) and [configuration](configuration.md#where-settings-live).

The manifest records the source commit, reproducibility seed, staged notices, and final output files. Rebuild from the same commit and `SOURCE_DATE_EPOCH` to compare output manifests and verify reproducibility.

## Desktop build, installer, and validation

Build the backend bundle before starting the Vite build. The desktop preparation step stages the complete repository-level `dist/backend-bundle` tree at `frontend/src-tauri/resources/backend-bundle`; Vite clears the repository-level `dist` directory, so preparation must finish first. The folder assembly step copies that staged tree beside the portable `APEX.exe` in `build/desktop-shell/APEX/backend-bundle`. The installer instead installs the Tauri executable as `apex-desktop.exe` beside `backend-bundle/apex-backend.exe`. Keep the full bundle, including `_internal`, configuration, demo resources, and license notices, intact in both outputs.

From the repository root, prepare the locked backend bundle, then run the desktop commands from `frontend`:

```powershell
uv sync --locked --all-extras --python 3.14.7
uv run --locked --all-extras --python 3.14.7 python scripts/build_backend_bundle.py
Push-Location frontend
npm run desktop:prepare
npm run desktop:build
npm run desktop:package
Pop-Location
```

`desktop:build` assembles the portable folder at `build/desktop-shell/APEX/`; it does not create an installer. `desktop:package` uses the pinned Rust `1.99.0` toolchain and the locked npm, Cargo, and Python dependencies to create the x64 MSVC NSIS per-user installer. It invokes the Tauri build for `x86_64-pc-windows-msvc` with the `nsis` bundle and Cargo `--locked`. Packaging requires a clean committed checkout and an exact match between `HEAD` and the verified backend bundle commit before and after the Tauri build; after any source commit, including documentation changes, rebuild the backend bundle before packaging. The portable build checks bundle version compatibility rather than requiring the same commit. `desktop:package` keeps the same assembled folder and writes the installer and `distribution-manifest.json` receipt under `build/desktop-shell/installers/`. Rust outputs stay under the target-specific `frontend/src-tauri/target/x86_64-pc-windows-msvc/` directory.

For repeat desktop builds after Vite clears repository-level `dist`, `desktop:prepare` reuses and validates the complete staged bundle by default. If you pass `--bundle` explicitly, use the same absolute path with preparation and either build command:

```powershell
npm run desktop:prepare -- --bundle "C:\path\to\backend-bundle"
npm run desktop:build -- --bundle "C:\path\to\backend-bundle"
npm run desktop:package -- --bundle "C:\path\to\backend-bundle"
```

### Distribution smoke checks

The distribution smoke installs current and synthetic previous-version installers in a guarded disposable Windows account, then checks upgrade, uninstall, reinstall, the frozen probe, and data preservation. Build the previous-version fixture from a clean committed checkout before running the smoke. The fixture uses the actual `2.0.0` application payload from the approved baseline and overlays only the current installer wiring. Its sidecar binds the installer hash, baseline and overlay provenance, and backend build ID; it is a test fixture, not a released APEX installer.

Choose a new, empty output directory outside the repository for the fixture. The helper requires a clean committed source checkout, builds a temporary worktree from the approved baseline, packages the previous app, and places one discovered `*-setup.exe` plus its adjacent `.fixture.json` sidecar in the output directory:

```powershell
python scripts/build_distribution_fixture.py `
  --base-ref 31fdd21757a1822ac0223956c20595ff5a13d307 `
  --output C:\apex-distribution-fixture `
  --report build\desktop-shell\distribution-fixture-report.json
```

Keep the sidecar beside the fixture installer. The distribution controller validates it before starting an upgrade test. Build the current installer separately with `npm run desktop:package`; its installer and `distribution-manifest.json` are written to `build/desktop-shell/installers/`.

Use the asset provisioner to verify any external FastEmbed and Kokoro test assets before running the distribution smoke. It writes `apex-distribution-smoke-assets.json`, `fastembed_cache/`, and `kokoro/` into the destination you choose; keep these model files outside the repository and installer:

```powershell
uv run --locked --all-extras --python 3.14.7 python scripts/provision_distribution_smoke_assets.py `
  --destination C:\apex-distribution-test-assets
```

Use the locations from that manifest for `--fastembed-cache` and `--kokoro-assets`. Select the current installer named by the current `distribution-manifest.json` and the single setup executable produced in the fixture directory. From the repository root, run CI-mode installer and headless checks with those files and the frozen probe:

```powershell
uv run --locked --all-extras --python 3.14.7 python scripts/smoke_distribution.py `
  --installer "C:\path\to\build\desktop-shell\installers\<current-setup-file>.exe" `
  --previous-installer "C:\apex-distribution-fixture\<previous-setup-file>.exe" `
  --previous-version 2.0.0 `
  --probe build\backend-bundle\smoke-probe\apex-bundle-probe.exe `
  --fastembed-cache "C:\apex-distribution-test-assets\fastembed_cache" `
  --kokoro-assets "C:\apex-distribution-test-assets\kokoro" `
  --mode ci `
  --expected-version 2.1.0 `
  --report build\desktop-shell\distribution-ci-report.json
```

The smoke controller refuses to run installers in the operator's Windows account, and also refuses an existing APEX install, data profile, startup entry, or listener on port 8000. For local runs, use a dedicated ordinary Windows account. Set `APEX_DISTRIBUTION_SMOKE_PROFILE=1`, set `APEX_DISTRIBUTION_SMOKE_OPERATOR_SID` to the protected operator account SID, and create `%LOCALAPPDATA%\.apex-distribution-smoke-profile` with the exact content `APEX-DISTRIBUTION-SMOKE:<unique-id>:<current-account-SID>`. The marker must bind to the current account's actual SID and registered ordinary Windows profile.

Hosted CI has a narrow exception: the runner must report `GITHUB_ACTIONS=true` and `RUNNER_ENVIRONMENT=github-hosted`, and `APEX_DISTRIBUTION_SMOKE_OPERATOR_SID` must be `S-1-0-0`. The profile flag and marker bound to that hosted runner's actual account are still required. Do not use this sentinel SID outside a GitHub-hosted Actions runner.

CI mode exercises silent installation and headless runtime but reports the visible WebView, tray, startup behavior, notification delivery, and foreground location checks as `unverified`. The frozen probe can run the distribution controller on a clean Windows VM without Python or uv:

```powershell
build\backend-bundle\smoke-probe\apex-bundle-probe.exe --distribution-suite `
  --installer "C:\path\to\build\desktop-shell\installers\<current-setup-file>.exe" `
  --previous-installer "C:\apex-distribution-fixture\<previous-setup-file>.exe" `
  --previous-version 2.0.0 `
  --probe build\backend-bundle\smoke-probe\apex-bundle-probe.exe `
  --fastembed-cache "C:\apex-distribution-test-assets\fastembed_cache" `
  --kokoro-assets "C:\apex-distribution-test-assets\kokoro" `
  --mode ci `
  --expected-version 2.1.0 `
  --report "C:\apex-distribution-test-assets\distribution-ci-report.json"
```

Run interactive mode on a Windows VM with a visible desktop, `tauri-driver`, and the matching Microsoft Edge WebDriver installed. Use the same installer, previous-version fixture, and test assets, and provide the driver paths:

```powershell
build\backend-bundle\smoke-probe\apex-bundle-probe.exe --distribution-suite `
  --installer "C:\path\to\build\desktop-shell\installers\<current-setup-file>.exe" `
  --previous-installer "C:\apex-distribution-fixture\<previous-setup-file>.exe" `
  --previous-version 2.0.0 `
  --probe build\backend-bundle\smoke-probe\apex-bundle-probe.exe `
  --fastembed-cache "C:\apex-distribution-test-assets\fastembed_cache" `
  --kokoro-assets "C:\apex-distribution-test-assets\kokoro" `
  --mode interactive `
  --expected-version 2.1.0 `
  --driver C:\tools\tauri-driver.exe `
  --native-driver C:\tools\msedgedriver.exe `
  --report build\desktop-shell\distribution-interactive-report.json
```

This exercises the installed WebView, tray, notifications, startup, and foreground location flow through the operating system. Notification validation reads Windows toast history for APEX's own app identity; it does not request broad notification-listener permission. A clean-machine WebView2 bootstrap check requires a VM where the runtime is absent and network access is available. A build or CI-mode report is not evidence that this interactive gate passed.

## Troubleshooting

- If notice staging reports a missing distribution license file, inspect that installed wheel's `RECORD` and upstream package before adding any material. Do not infer a license from package metadata.
- If notice staging reports that an archive hash or source revision differs, compare the checked-in source archive and manifest to `uv.lock` and the upstream build workflow. Do not replace an exact source with a newer release.
- If the packaged API cannot start, read its stderr output and confirm the complete `_internal` installation is beside the executables. The caller's working directory may be elsewhere. Run `apex-backend.exe --help` to confirm the packaged entrypoint.
- If Kokoro reports an eSpeak `phontab` path error, the frozen Windows runtime could not find a verified ASCII short-path alias for its bundled eSpeak data. For the portable folder only, move `build/desktop-shell/APEX/` under an ASCII-only path such as `C:\Apps\APEX` and retry. Keep an installed build at its installer-managed location under `%LOCALAPPDATA%\Programs\APEX`; do not move the installation manually. For an installed build, the adapter uses a verified existing ASCII short-path alias when Windows provides one; if it cannot verify one, Kokoro initialization reports the path failure. The adapter does not copy eSpeak data or write into the installation.
- If a smoke check needs a model file, supply the external file to the smoke command; model files are not downloaded or copied into the bundle by this build.

For source development, environment setup, and the ordinary browser workflow, see [Getting Started](getting-started.md). For CLI commands and behavior, see the [CLI guide](cli.md).
