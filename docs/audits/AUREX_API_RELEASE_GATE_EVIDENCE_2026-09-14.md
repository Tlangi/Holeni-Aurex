# Aurex API release gate evidence — 2026-09-14

Decision: **NOT DEPLOYABLE YET**. No service was restarted, reconfigured, or pointed at the candidate. No trading control was changed.

## Candidate and reproducibility

- Source: commit `d1cf0bec440111dac0aeabfadc17499679eb2c56` on `codex/aurex-stage1-hardening`.
- Isolated audit archive: `AurexApiReleaseAudit-d1cf0be/source.zip` under the operator's temporary directory. It contains committed `services/platform-api`, `database/scripts`, and the TradingAgents worker referenced by backend tests. It contains no `.env` or broker credential.
- Archive SHA-256: `A1A6AE26E47F3DEA402ED925926A7D8CF49FD37CAC9283EEB2D89A0D079A8064`.
- `requirements.txt` SHA-256: `96761AB8EBE63BA9A52ED6958D9E9BFC3CD5E5827E65EA97E4152553E2F8CCFE`.
- `requirements-dev.txt` SHA-256: `F5BF5D4EE1BA6674D94FED05586744B7EB5012395F6B0326DF053CCEEAD7C52B`.
- Python 3.12.10; tests used the existing local virtual environment. Thus dependency *files* are hashed, but a fresh dependency install has not been proven.
- All 331 backend tests passed from the isolated archive. Only SQL configuration keys were supplied as process environment for the database integration test; no secret file was copied into the archive. The new retry test verifies no IG client is constructed or authenticated while the schema is unavailable, followed by authentication and one sync after recovery.

## Read-only pre-switch checks

- The live API answered `/health/ready` and exposed 62 OpenAPI route paths. The committed source exposed the same 62 paths. Route equality does not prove loaded module/hash equality.
- NSSM points `AurexPlatformAPI` at `C:\Projects\Forex\services\platform-api\.venv\Scripts\python.exe`, working directory `C:\Projects\Forex\services\platform-api`, runner `scripts\run_api.py`. This is not a versioned immutable release. The previously running imported-code hash is unavailable.
- Engine controls: `SHADOW`, `new_orders_enabled=0`; Live disabled; zero pending proposals and unresolved submission intents; authoritative size increment for zero markets. Demo execution is configured in environment but is not armed by engine control.
- Three-plus scheduled account syncs succeeded before a switch at approximately five-minute intervals; this is baseline evidence, not post-release acceptance.
- Daily backup completed 2026-09-14 00:18 UTC; the latest disposable restore verification was 2026-09-13 01:01 UTC.

## Unmet release requirements

1. The committed checkpoint contains risk/proposal/API changes beyond the gate's account-sync-only scope. Although live route paths match, exact loaded risk/broker implementation cannot be attested. Treat this as a scope failure, not a reason to weaken the gate.
2. The audit archive is temporary, not a versioned service release with a separately managed configuration path. The code-relative `.env` would be absent from a clean service directory, and copying credentials into the release would violate the gate.
3. The candidate has not been started on a separate localhost port with database-available, unavailable, and recovery checks. A second API process must not accidentally run account sync or broker submission while testing.
4. The prior service target is recorded, but it points to the mutable checkout rather than a known, hash-attested executable for rollback. A rollback to that path would not establish the former loaded version.
5. The release owner has not approved an exact deployable manifest, service target, restart window, and rollback path. Post-switch three scheduled successes and rechecks necessarily remain outstanding.

`install_api_service.ps1` is not the release-gate method: it stops/removes and reinstalls the service from the shared checkout. Do not use it for this switch. Build a separately versioned, externally configured API release, resolve scope and rollback attestation, then repeat the checks before a one-service switch.
