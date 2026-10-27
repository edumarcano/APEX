# Web runtime reference

Applicability evidence: browser/server web code, deployment configuration, or an
approved web runtime decision. Language alone is insufficient.

Inspect client/server boundaries, configured build commands, environment inputs,
and existing deployment ownership. Ask which request, response, authentication,
error, or persistence boundary the change affects and where it can be checked
without contacting live services.

Do not infer Vercel, Next.js, a cloud provider, authentication, or a database.
Configured deployment files do not establish successful deployment. Builds are
not production verification; installation does not authorize network calls,
credential access, dependency installation, deployment, or provider changes.
