# Windows backend bundle

The backend bundle is an experimental Windows x64 package for running the existing FastAPI backend and CLI without a source checkout. It keeps the backend and command-line client separate from the future desktop shell. The package is built from the locked Python runtime plus every project extra, and includes its configuration defaults, demo fixtures, and documentation resources.

## Build

Build from the repository root on Windows x64 with Python 3.14.7 x64 and uv 0.12.3. The build creates a one-folder distribution at `dist/backend-bundle` and uses the versions of PyInstaller and its hooks pinned by the build lock.

```powershell
uv sync --locked --all-extras --python 3.14.7
uv run --locked --all-extras --python 3.14.7 python scripts/build_backend_bundle.py --with-smoke-probe --reproducibility-check
```

The `--with-smoke-probe` flag builds a validation-only executable under `build/backend-bundle/smoke-probe/`. That probe is not copied into the distributable folder. `--reproducibility-check` rebuilds with the same seed and compares the resulting manifest. Omit either flag when that check is not needed.

Build inputs use the source commit and `SOURCE_DATE_EPOCH`; the build manifest records the inputs and packaged files. A license or source-material inventory failure stops the build. The bundle stages APEX's MIT license, Python's interpreter license, the PyInstaller bootloader exception, and original license/notice files from the locked runtime distributions. It also includes corresponding-source archives for GPL components and pygame-ce's LGPL source distribution in `licenses/source-material/`. The staged `THIRD_PARTY_NOTICES.md` lists each component version and links to its material.

The all-extras runtime contains Kokoro's `phonemizer-fork` and `espeakng-loader` dependencies. The latter carries eSpeak NG native files. Their source revisions and archives are pinned and checked during notice staging; do not omit those files from the final bundle. The pygame-ce sdist and its carried license texts are included. Exact DLL-to-source revision mappings are verified for its libxmp and WavPack DLLs; other bundled codec DLLs have their license texts included from that release but their exact upstream build revisions are not independently mapped yet. See [`packaging/windows/source-material/README.md`](../packaging/windows/source-material/README.md) for the evidence boundary.

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

## Troubleshooting

- If notice staging reports a missing distribution license file, inspect that installed wheel's `RECORD` and upstream package before adding any material. Do not infer a license from package metadata.
- If notice staging reports that an archive hash or source revision differs, compare the checked-in source archive and manifest to `uv.lock` and the upstream build workflow. Do not replace an exact source with a newer release.
- If the packaged API cannot start, read its stderr output and confirm the complete `_internal` installation is beside the executables. The caller's working directory may be elsewhere. Run `apex-backend.exe --help` to confirm the packaged entrypoint.
- If a smoke check needs a model file, supply the external file to the smoke command; model files are not downloaded or copied into the bundle by this build.

For source development, environment setup, and the ordinary browser workflow, see [Getting Started](getting-started.md). For CLI commands and behavior, see the [CLI guide](cli.md).
