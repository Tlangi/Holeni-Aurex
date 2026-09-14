# Aurex source/version reconciliation — 2026-09-14

## Recovery baseline

- Approved remote: `https://github.com/Tlangi/Holeni-Aurex.git`, branch `codex/aurex-stage1-hardening`.
- Commit `b6dc424` records SQL migrations 051–058. All eight were already applied in `app.schema_migrations`; their database checksums matched the local source before commit. The commit was pushed to the approved branch.
- The local Angular build passed and frontend tests passed 40/40. Backend tests passed 330/330 after reconciling the proposal approval-window constant.
- These are source/build checks, **not** a production deployment attestation. Demo/Live execution authority was not changed.

## Remaining worktree inventory before this report

There were 53 modified tracked files and 62 untracked files after recording the eight migrations. The 62 untracked files comprised 9 frontend files, 9 backend modules, 12 backend scripts, 18 backend tests, and 14 documents. No untracked large binary, model artifact, database dump, certificate, or private-key file appeared in `git status -uall`. A targeted scan for common private-key and service-token signatures did not find a match; this is not a substitute for a full independent secret review.

The work spans UI consolidation, owner overview, research/model and data quality, broker/account sync, Shadow worker, and authenticated approval reservation. It is interdependent, so an arbitrary subset of Python modules is not a deployable API release. The approval reservation is explicitly pre-submission; it does not authorize an IG order.

## Verified integration issue

The Shadow worker constructed a proposal expiry 15 minutes after decision, while `TradeProposalCreate` rejected windows over five minutes. This would fail when an otherwise eligible proposal was attempted. The producer and validator now share `PROPOSAL_APPROVAL_WINDOW_SECONDS = 300`; the validator boundary test and full backend suite pass. This is not evidence that the end-to-end proposal-to-order workflow is complete.

## Runtime/version caveat

NSSM reports `AurexPlatformAPI`, `AurexTradingWorker`, `AurexHealthMonitor`, and `AurexOwnerOverviewAPI` all point to `C:\Projects\Forex\services\platform-api`. Long-running processes can therefore have imported code from before later worktree edits. `AurexWeb` is stopped/disabled; IIS serves a separate static release. The latest visible release directory was `C:\sites\aurex\releases\20260914-201152`, whose frontend bundle filenames matched the freshly built local bundle, but IIS configuration access was denied, so its active physical path was not attested.

GitHub source, working tree, loaded Python modules, and active IIS assets must be recorded separately; matching filenames or a passing test does not prove the same live version.

## Release decision

Do not restart the API from this integration worktree. Before deployment, create an isolated release from an explicit commit, compare routes/imports and schema dependencies, test startup/recovery, attest Demo/Live controls and unresolved intents, record rollback paths, then switch one service at a time under the account-sync backend release gate. A source-control checkpoint is recoverable history, not a production approval.
