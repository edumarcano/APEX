# Third-Party Notices

APEX includes third-party software under the licenses carried by its source distributions and installed packages. The frozen backend bundle stages the original license and notice files from the locked runtime dependency closure in `licenses/`; this document accompanies that generated inventory.

## Bundle scope

The backend bundle uses the Python dependencies in `pyproject.toml` and `uv.lock`, including the `tts-google`, `tts-kokoro`, and `tracing` extras. Its generated inventory records each installed distribution name and version and links to the license or notice files copied from that distribution. It also includes the Python interpreter license and PyInstaller's bootloader license exception. Build-only packages are excluded except for the PyInstaller bootloader notice.

The inventory is generated at build time because optional dependencies and transitive versions are part of the shipped files. If a runtime distribution has no installed license or notice material, the collector stops instead of inferring a license from package metadata.

## Native and model files

The all-extras dependency graph includes `pygame-ce`, ONNX Runtime, `phonemizer-fork`, and the Windows `espeakng-loader` wheel. The eSpeak NG native files have licensing and corresponding-source material separate from the Python loader package. The pygame-ce Windows wheel also bundles SDL and codec DLLs; its hash-verified 2.5.7 source distribution supplies the pygame and multimedia license texts, with separate upstream licenses staged for the libxmp 4.6.1 and WavPack 5.6.0 DLLs. See [Backend bundle](docs/backend-bundle.md) for the exact packaging scope and source-material status.

Model weights are not bundled. APEX downloads retrieval models on demand and operators may supply speech weights separately; model terms are governed by their respective upstream sources and are outside this software inventory.

The loader source archive also carries a verified MIT grant for the 0.2.4 Python wrapper. The collector stages it only after comparing the installed wrapper bytes with the upstream licensed source.

## Frontend attributions

The APEX source distribution also includes frontend software under separate licenses. React and related frontend libraries and assistant-ui (`@assistant-ui/react`) are MIT-licensed; Lucide is ISC-licensed. The frontend package manifests and lockfile identify the exact versions. These source-project attributions remain relevant when distributing the frontend; they are not part of the standalone backend bundle's generated dependency inventory.

## Source project attributions

The source project also uses Microsoft Authentication Library for Python (`msal`) and Microsoft Authentication Extensions for Python (`msal-extensions`), both under the MIT License. Its Python dependency set includes Apache-2.0 components such as FastMCP, Google Auth, Google Gen AI, OpenAI, Requests, Google Cloud Text-to-Speech, and OpenTelemetry packages, plus components under other upstream licenses such as pygame-ce, pyttsx3, psutil, and python-dotenv. Consult the project dependency manifests and lockfiles for exact versions and each package's complete terms. These source-project attributions do not replace the generated backend bundle inventory.

## Other attributions

Third-party data and hosted-service attribution requirements are presented in the APEX interface where applicable. They are not replaced by this file.
