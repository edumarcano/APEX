# Python reference

Applicability evidence: Python source or an approved Python implementation decision.
Remora's own Python helper does not select Python for the target application.

Inspect the project's package metadata, supported Python versions, environment
ownership, and configured verification entrypoints. Ask which behavior needs
protection, whether imports have side effects, and whether resource cleanup,
cancellation, encoding, or filesystem behavior affects the requested change.

Do not infer pytest, uv, Ruff, a package layout, or a deployment model. Commands
remain configured until actually executed. Preserve the project's working tooling.
