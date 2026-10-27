# Local execution reference

Applicability evidence: established requirements or implementation for local
execution. This dimension is independent of application language.

Inspect actual entrypoints, local data ownership, platform assumptions, working
directories, lifecycle, and permitted execution. Ask whether offline behavior,
paths with spaces, line endings, interrupted operations, and newer user edits
matter to the requested outcome. Prefer existing isolated checks.

Do not infer that local files imply local inference, that every command is safe,
or that a Windows observation establishes Unix behavior. Do not introduce a daemon,
installer, persistence layer, or cross-platform abstraction without a requirement.
