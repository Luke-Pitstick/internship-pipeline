# Downstream release work — October 8, 2026

The local implementation for the remaining release tasks is ready for a new candidate. Release acceptance remains partial. Three GPT-6.1 Sol workers at high reasoning implemented and independently reviewed distribution, recovery and live-test preparation; the parent integrated native browser/resource work and combined verification.

## Task disposition

| Task | Completed locally | Remaining acceptance |
| --- | --- | --- |
| S1: live-test preparation | Private two-job synthetic seed, per-provider input table, bounded run sheet and sanitized evidence template. Independent review verified private ownership/modes and restored umask. | Private credentials, selected models, approved spending/request envelope, recipient and disposable Sheet. |
| S2: live execution | Existing provider/worker regressions pass with synthetic transports. | Actual public collection, TypeSafe and each advertised general provider, grounded PDF, SMTP receipt and Sheet readback/recovery on the accepted image. |
| S3: support/resources | 10,000-job native browser journey at 320px/390px, measured bundle, static gzip negotiation, read-only cgroup sampler. | Serving-image rerun, actual idle/run/PDF measurements, declared browser versions, real screen reader, Step 12 operating trial. |
| S4: distribution | MIT candidate notice and package metadata, complete deterministic installer archive, checksum-verifying bootstrap, documented GHCR/GitHub Releases promotion. | Final source/image acceptance, image notices/SBOM/asset authority, working private security reporting, candidate publication and independent hosted download. |
| S5: installation/recovery | Fresh exact-image restore into isolated owned storage, installed management of the restored data root, private bounded backup transfer and recovery regressions. | Exact published installer on each declared host/runtime and an unfamiliar operator completing installation/recovery. All eight proposed host/runtime cells remain untested. |
| S6: reconciliation/promotion | This evidence index and concrete remaining gates. | Close required external rows and promote the exact accepted artifacts; no release promotion occurred here. |

Model-derived rejection continues to route to review. Automatic rejection requires the separate independent quality gate and is not necessary to finish a release with that restriction disclosed.

## Verification

The frozen-source native suite passed **866 tests, no skips, one existing Starlette deprecation warning in 106.43 seconds**. Command: `rtk proxy env PYTHONPATH=src /tmp/internship-pipeline-audit-venv/bin/python -m pytest -q --basetemp=/tmp/pipeline-release-final-20261008 --tb=short`. Local synthetic listeners required sandbox escalation; no external transports were authorized. The same implementation passed full Ruff and strict mypy over 63 source files. Svelte checking reported zero errors/warnings and the production build passed. Six default browser cases (15.4 seconds), one fresh guided-setup case (11.4 seconds) and one 10,000-job workspace case (18.3 seconds) passed using synthetic transports; these eight current cases do not replace every historical browser suite or certify an image.

Independent security reviews covered download/archive extraction, restore transfer and seed privacy. The reported seed permission and static encoding-negotiation defects were corrected and rechecked. Resource probes also enforce cgroup guards under optimized Python. No separate visual redesign was made; native responsive/focus behavior was checked in the workspace journey.

The distribution candidate was built twice with identical bytes, its unpacked installer help executed, and wheel/sdist license inclusion verified. It is a local, unpublished artifact. Its recorded dirty-source metadata is intentionally not release provenance; regenerate provenance from the final commit and repeat affected CI/image checks before publication.

The parallel CI owner reports the full image workflow passed at `49ddcef`. The current checkout additionally contains provider commit `8f14e54` and the changes described here. That earlier image result cannot certify these later application/installer bytes. Obtain the final CI run, source SHA, platform/image identities and attestations from the CI evidence owner before running this acceptance sequence.

## Concrete next inputs and execution order

1. **Freeze and accept the combined candidate.** Include the provider changes and these fixes in the source revision, rerun affected native/image gates, and retain verified platform identities, SBOM and provenance. Preserve the existing CI owner's workflow scope.
2. **Provide private live-test inputs.** Root `.env` field-presence inspection found a Jev credential but no populated current general-provider key/model fields. Existing saved application settings were not successfully inspected. Supply only credential locations in chat; save secrets privately. Select a primary provider/model and a billing limit, then approve the run sheet's exact request/transport/write ceilings, inbox and disposable Sheet. Each additional advertised provider needs its own bounded probe/generation run.
3. **Execute live and resource acceptance.** Use fresh owned installations and the synthetic two-job fixture, keep public-source collection separate, observe actual SMTP receipt and Sheet readback, and collect idle/run/PDF measurements from the accepted image. Do not expand budgets or manufacture favorable assessments to make downstream scenarios pass.
4. **Complete distribution gates and publish a candidate.** Confirm MIT copyright/asset authority, inspect actual image notices, enable and independently verify private security reporting, then publish the accepted bytes to GHCR and GitHub Releases with hashes and provenance. Test the downloaded bytes on the explicitly selected support matrix.
5. **Complete operator/accessibility/trial evidence.** An unfamiliar operator must reach a useful job and restore the installation from shipped instructions; a real screen-reader session and the planned 24-hour trial remain open. Any narrower first-release scope needs an explicit owner decision. Reconcile the matrix and promote without rebuilding different bytes.

## Evidence and run sheets

- [Task cards](../../agents/remaining-release-subtasks.md)
- [Live acceptance plan](live-acceptance-plan.md), [current live status](live-acceptance.md), [evidence template](live-acceptance-evidence-template.md)
- [Native support measurements and container sampler](support-measurements.md)
- [Distribution and promotion procedure](distribution.md)
- [Hosted installation and recovery acceptance matrix](installation-acceptance.md)
- [Release acceptance matrix](../release-readiness.md)

No paid call, external email, remote Sheet mutation, image publication or public release was performed by this downstream task.
