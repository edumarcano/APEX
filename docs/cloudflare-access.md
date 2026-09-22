# Cloudflare Access deployment

This guide exposes the separate activity submission gateway to one interactive remote client. It keeps the normal APEX launcher and API private. Cloudflare owns the public hostname, TLS, Access policy, Managed OAuth, and tunnel; APEX only verifies the forwarded Access assertion before accepting an activity report.

The first reference client is Spark. A real Spark Managed OAuth handshake and MCP submission is an acceptance test for this deployment, not an assumed capability. This repository does not contain Cloudflare credentials or a completed Spark test.

## Before exposing the gateway

Keep APEX's main API and HUD on loopback as usual. The gateway also binds to loopback, including in Cloudflare mode. Do not start it with `--mode local` behind a tunnel: local mode grants the generic `operator` principal and a tunnel cannot prove that a caller is local.

Create a distinct activity registration for Spark and bind it only to the generic principal `cloudflare:spark`. Then add one `external_activity.cloudflare.bindings` item using the matching client ID, the Access application's audience, and the operator's signed Access `sub` claim. Copy the exact issuer and JWKS URL for the Cloudflare team into the same configuration. The example and field meanings are in [Configuration](configuration.md#external-activity-gateway).

The configuration contains no client secret, OAuth token, or private key. Keep any Cloudflare administrator credentials and tunnel credentials outside this repository. An incorrect or unavailable configuration prevents Cloudflare mode from starting; it does not affect normal APEX startup or local imports.

## Configure the Cloudflare boundary

Create one public hostname for Spark, such as `spark-mcp.example.com`. Point its Tunnel service only at the running gateway, `http://127.0.0.1:8001`; do not target port 8000, the HUD, or a general local proxy. Create one dedicated self-hosted Access application for that hostname and restrict its policy to the operator's identity.

Enable Managed OAuth for that Access application only when the remote client supports OAuth resource discovery and RFC 8707 resource indicators. Cloudflare issues and manages the OAuth credentials; APEX does not implement an authorization server, login screen, token exchange, or certificate management. Cloudflare service tokens are an option Cloudflare provides for unattended clients, but beta.4 does not add a second APEX authentication path for them.

For another remote client, create a different hostname and Access application with a different audience, then add a separate binding and activity registration. Do not share an operator subject as the sole identity of two registrations: the distinct verified audience selects the integration. APEX rejects a token that matches zero or more than one configured binding, and it rejects a report whose requested `client_id` differs from the binding.

## Start and verify

Start the gateway after its configuration is present:

```powershell
uv run python -m core.activity.gateway --mode cloudflare
```

Start the Cloudflare Tunnel with the externally managed configuration that targets this gateway. APEX does not launch or supervise `cloudflared`.

Use this checklist after deployment:

1. Complete Spark's real Managed OAuth discovery and authorization flow against the public MCP endpoint, then submit one report with `submit_activity`.
2. Confirm the report appears in Inbox with the configured Spark source and that repeating the same submission key returns the original receipt with `duplicate: true`.
3. Disable Spark's registration in `config.json` and submit again through the existing MCP session. The new request must fail while the earlier report remains visible.
4. Submit a report through the local Codex CLI using its separate local registration. This is local source attribution, not proof of an independently authenticated remote client.
5. Stop the tunnel and gateway. Verify that local CLI/file import and the existing context-review flow still work.

The Spark step is deliberately not replaced by a generic HTTP request. If it cannot complete, treat the remote integration as unverified while local activity operation remains available.

## Troubleshooting and revocation

An assertion verification failure returns `401`. Check that Cloudflare forwards `Cf-Access-Jwt-Assertion`, the issuer and application audience match the configured values, the signed `sub` is allowed, and the APEX host can refresh the configured JWKS endpoint. APEX caches usable signing keys for five minutes by default (`key_cache_seconds` can set a 60-second to one-hour interval), then fails closed if refresh fails.

A `403` means the verified Access application does not match the requested client ID, or its registration is disabled, removed, assigned to another partition, or does not allow its generic `cloudflare:<client-id>` principal. Disable a single registration to revoke submissions from that integration without deleting retained reports or blocking another binding.

The gateway logs client and report identifiers plus failure categories. It does not log assertion values, report bodies, or Cloudflare claims.
