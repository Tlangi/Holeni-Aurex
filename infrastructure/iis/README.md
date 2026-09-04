# Aurex production IIS deployment

This deployment is intentionally restricted to `https://holeniaurex.co.za`.
It does not create a `www` binding and must not alter any other IIS site.

## Required private API configuration

Keep secrets only in `services/platform-api/.env` and set these non-secret controls:

```text
APP_ENV=production
API_HOST=127.0.0.1
API_PORT=8010
WEB_ORIGINS=https://holeniaurex.co.za
TRUSTED_HOSTS=holeniaurex.co.za,127.0.0.1,localhost
SESSION_COOKIE_SECURE=true
TRADING_MODE=disabled
BROKER_ENVIRONMENT=demo
ALLOW_DEMO_TRADING=false
ALLOW_LIVE_TRADING=false
EXPERIMENTAL_DEMO_ENABLED=false
```

Do not store passwords, connection strings, broker credentials, cookie values, or certificate private keys in IIS or a release directory.

## Deployment and rollback

Run `deploy-aurex.ps1 -WhatIf` first, then run it without `-WhatIf` from an elevated PowerShell session. Each deployment creates a new directory under `C:\sites\aurex\releases` and changes only the `Aurex` site physical path.

Before the first IIS change, create an AppCmd backup:

```powershell
& "$env:windir\System32\inetsrv\appcmd.exe" add backup "Aurex-before-YYYYMMDD-HHMMSS"
```

To roll back, select a previously verified directory and run:

```powershell
.\rollback-aurex.ps1 -ReleasePath 'C:\sites\aurex\releases\YYYYMMDD-HHMMSS'
```

An AppCmd backup is a last-resort IIS configuration rollback. Restoring it affects the entire IIS server, so prefer the site-scoped rollback script.

## DNS and TLS

Create only this public record:

```text
A  holeniaurex.co.za  102.206.117.162
```

Do not create an AAAA record unless IPv6 has separately been configured and tested. After the A record resolves publicly and TCP 80/443 reach this server, use the existing win-acme installation to issue and automatically renew an IIS certificate for `holeniaurex.co.za` only.
