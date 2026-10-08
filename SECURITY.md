# Security and service terms

This is an independent Windows utility, not a Google product or an approved Antigravity integration.

## Google service terms

The [Google Antigravity Additional Terms of Service](https://antigravity.google/terms), checked on 2026-10-08, clause 6, prohibit using third-party software, tools or services to access the Service and state that this may lead to Antigravity and/or Gemini CLI account suspension or termination. Enterprise subscriptions may be governed by different applicable agreements.

This application directly calls Antigravity internal quota endpoints and refreshes OAuth grants. Those functions carry a material service-terms risk even without proxying model requests. The terms do not separately clarify whether restoring local login snapshots is permitted. Open source publication and this MIT license do not grant permission from Google or override its terms. This repository makes no claim of being compliant or safe from enforcement. It does not provide a model-request proxy or alter device identifiers to evade enforcement.

## Credential boundary

- The current Windows credential target is `gemini:antigravity`. Scanning reads that current login; it does not enumerate all browser accounts or other Windows credentials.
- For an unmatched login, scanning uses the existing access token with Google's user-info endpoint to confirm email/subject, with token refresh when necessary. Scan candidates remain in backend memory until the user names and confirms enrollment. The current login is checked again before saving.
- Exact refresh-grant matches or previously verified Google subject metadata prevent duplicate enrollment. Older snapshots without subject metadata primarily match by their refresh grant. Independently reauthorizing an older account with a new grant can require manual review/update.
- Persistent account snapshots, recovery snapshots and quota cache files use Windows DPAPI for the current Windows user. The browser UI receives safe account/scan status and quota projections, never access tokens or refresh tokens.
- Same-user malware can still read the Windows vault or invoke DPAPI. Encryption is not isolation from software running as the same user.
- The runtime directory is `%LOCALAPPDATA%\AntigravityLocalSwitcher`, separate from this repository and the installation directory. Do not publish it. Uninstall leaves this directory in place.
- OAuth refresh reads the compatible desktop client configuration from the locally installed official Antigravity binary. No client ID or client secret is embedded in the source or release. A SHA-256 compatibility fingerprint selects the verified pair when multiple clients are present; unrecognized versions stop refresh. This installed-client configuration is not a user's Google access/refresh token and does not independently grant account access. No additional scopes are requested.

## Network and local control

Google requests use a fixed HTTPS endpoint allowlist and reject redirects. Quota requests share a serialized rate limiter. Account refreshes are sequential, and HTTP 429 pauses the batch and preserves a cooldown. These are ordinary load controls, not a guarantee about Google's detection or policy enforcement.

The local web server binds only to `127.0.0.1`. State-changing requests validate Host, Origin, an HttpOnly SameSite cookie and a random control token. Credentials do not cross the local browser boundary. The application does not use remote fonts, analytics, CDNs or a vendor-operated credential service.

## Reporting issues

Do not attach account snapshots, recovery files, OAuth grants, raw provider traffic, unredacted logs or personal screenshots to public issues. Use synthetic examples. For a security issue, use GitHub's private vulnerability reporting if enabled; otherwise describe the issue without disclosing credentials or a live exploit against an account.
