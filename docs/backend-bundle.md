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

The suite relocates the packaged programs under a Unicode path, runs them from an unrelated working directory, and sanitizes child `PATH` values. It checks the frozen bundle and separate probe; it does not establish VM or clean-install evidence.

## Included and excluded files

The bundle contains the backend runtime, standalone CLI, default configuration, demo JSON fixtures, and the documentation the backend needs at runtime. It excludes model weights, provider credentials, databases, operator configuration, caches, and other personal data. Mutable installed data defaults to `%LOCALAPPDATA%\APEX`; see [runtime paths](architecture.md#runtime-resource-and-data-paths) and [configuration](configuration.md#where-settings-live).

The manifest records the source commit, reproducibility seed, staged notices, and final output files. Rebuild from the same commit and `SOURCE_DATE_EPOCH` to compare output manifests and verify reproducibility.

## Desktop build handoff

Build the backend bundle before starting the Vite build. The desktop preparation step stages the complete repository-level `dist/backend-bundle` tree at `frontend/src-tauri/resources/backend-bundle`; Vite clears the repository-level `dist` directory, so prepare must finish first. The native assembly step later copies that staged tree beside `APEX.exe` in `build/desktop-shell/APEX/backend-bundle`. Preserve the executable, its adjacent `_internal` directory, configuration and demo resources, and license notices together. Do not stage only the executable.

From the repository root, prepare the locked backend bundle, then run the desktop commands from `frontend`:

```powershell
uv sync --locked --all-extras --python 3.14.7
uv run --locked --all-extras --python 3.14.7 python scripts/build_backend_bundle.py
Push-Location frontend
npm run desktop:prepare
npm run desktop:build
Pop-Location
```

For repeat desktop builds after Vite clears repository-level `dist`, `desktop:prepare` reuses and validates the complete staged bundle by default. If you pass `--bundle` explicitly, the value must be an absolute path.

The assembled native executable is `build/desktop-shell/APEX/APEX.exe`. The sibling `backend-bundle` directory is part of its runtime and must remain intact. The shell stores mutable operator state in its selected data directory, outside these installed resources.

Run the real WebView2 gate with a `tauri-driver` installation and the Microsoft Edge WebDriver binary matching the host WebView2/Edge version. The smoke launches the supplied executable, guards the fixed API port, sets a disposable data profile and `DEMO_MODE`, and writes a JSON report under the local build directory:

```powershell
uv run --locked --all-extras --python 3.14.7 python scripts/smoke_desktop_shell.py `
  --application build/desktop-shell/APEX/APEX.exe `
  --driver C:\tools\tauri-driver.exe `
  --native-driver C:\tools\msedgedriver.exe `
  --report build/desktop-shell/smoke-report.json
```

The smoke exercises native startup conflict and retry, the four workspaces, a demo Briefing, and Cortex through a disposable loopback llama.cpp-compatible streaming fixture. It waits for the first provider delta before clicking the real WebView Stop control, then checks persisted cancellation and run events. It also checks managed-child crash recovery and graceful close. An essential case reported as `unverified` makes the command exit nonzero; review the JSON report with the build and do not treat an unverified case as a pass.

## Troubleshooting

- If notice staging reports a missing distribution license file, inspect that installed wheel's `RECORD` and upstream package before adding any material. Do not infer a license from package metadata.
- If notice staging reports that an archive hash or source revision differs, compare the checked-in source archive and manifest to `uv.lock` and the upstream build workflow. Do not replace an exact source with a newer release.
- If the packaged API cannot start, read its stderr output and confirm the complete `_internal` installation is beside the executables. The caller's working directory may be elsewhere. Run `apex-backend.exe --help` to confirm the packaged entrypoint.
- If Kokoro falls back with an eSpeak `phontab` path error, check whether the installation path contains non-ASCII characters. The frozen Windows runtime uses an existing ASCII short-path alias for eSpeak data when Windows provides one. If it cannot verify an alias, install APEX under an ASCII-only path such as `C:\Apps\APEX` and retry. The adapter does not copy eSpeak data or write into the installation.
- If a smoke check needs a model file, supply the external file to the smoke command; model files are not downloaded or copied into the bundle by this build.

For source development, environment setup, and the ordinary browser workflow, see [Getting Started](getting-started.md). For CLI commands and behavior, see the [CLI guide](cli.md).
