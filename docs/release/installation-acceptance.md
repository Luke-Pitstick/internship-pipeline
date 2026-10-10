# S5 — Hosted installation and exact-image recovery acceptance

**Current status (October 10):** [RC3 acceptance](rc3-status.md) supersedes older preparation results below. RC3 is a public prerelease; anonymous Linux installation/recovery and one macOS arm64 Docker journey pass. Live, remaining host/operator and trial gates remain open. RC1 and RC2 are held drafts.

Prepared October 8, 2026. **Execution pending:** no published immutable installer/image references, fresh test hosts or unfamiliar operator have been supplied. Native executable fake-runtime tests establish host command behavior; T17 native tests establish backup semantics. Neither certifies Docker/Podman, a macOS VM or the hosted bytes. This run sheet authorizes no paid model calls, email sends, remote Sheet writes, engine startup on the existing low-disk Colima host, pruning or removal of user resources.

## Candidate and host evidence

Freeze the successful CI source SHA/run URL, accepted platform OCI checksums/config identities, published image manifest/platform digests, complete installer bundle SHA-256, bootstrap SHA-256, release version, immutable URLs and integrity trust source from S4. A local config ID, archive checksum, platform manifest and multi-platform manifest are distinct identities. Changing any bundled helper invalidates the bundle hash and requires S4 repackaging and affected acceptance again. The source and bootstrap must come from the same reviewed release.

Local October 8 preparation passes **150 tests, with 1 skipped**, using `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_installer.py tests/test_management.py tests/test_operations.py tests/test_recovery_transfer.py` (54.79 seconds). Owned Ruff/strict mypy, Python compilation, shell syntax, help entrypoints and diff whitespace checks pass. The skip is a sandbox-denied real loopback bind; fake-socket collision behavior is covered. The existing Starlette warning remains. This evidence covers simulated runtime boundaries and native T17 data semantics only.

Fill every claimed cell independently. A Linux image smoke/recovery report is an input to host acceptance; it doesn't prove the hosted installer or macOS VM. Narrow advertised support deliberately if a required host cannot be tested.

| Cell | Host architecture | Engine arrangement | OS/runtime/Python versions | Installation/operator/recovery evidence | State |
| --- | --- | --- | --- | --- | --- |
| L-D-A | Linux amd64 | local Docker Linux engine | pending | pending | untested |
| L-D-R | Linux arm64 | local Docker Linux engine | pending | pending | untested |
| L-P-A | Linux amd64 | rootless local Podman | pending | pending | untested |
| L-P-R | Linux arm64 | rootless local Podman | pending | pending | untested |
| M-D-I | macOS Intel | local Docker Linux VM | pending | pending | untested |
| M-D-S | macOS Apple Silicon | local Docker Linux VM | pending | pending | untested |
| M-P-I | macOS Intel | local Podman machine | pending | pending | untested |
| M-P-S | macOS Apple Silicon | local Podman machine | pending | pending | untested |

Record kernel/OS release, native CPU and selected image platform, engine/client versions, VM CPU/RAM/disk allocation, available host/VM disk, Python 3.12+ version, firewall/proxy/network, image cache state and SELinux enforcing/permissive/absent. Podman machine must prove its saved loopback SSH URI, explicit private identity path, host filesystem visibility and loopback forwarded port. Docker must prove its saved Unix endpoint and private host bind access. Windows, remote engines, emulation-only claims and cross-engine recovery are excluded.

## Exact hosted commands

S4 supplies actual immutable HTTPS values; placeholders below are intentionally not working URLs. Download the versioned `bootstrap_installer.py` without a checkout, verify its SHA-256 against the independently trusted release channel, and save it as `/private/installer/bootstrap_installer.py` with owner-only permissions. Do not derive the trusted checksum from the same untrusted download. Preserve the verification transcript without private host paths or credentials in public evidence. The bootstrap verifies, strictly extracts and launches the complete five-deploy-file bundle plus MIT `LICENSE`; the shell file alone isn't the hosted installer.

```sh
python3 /private/installer/bootstrap_installer.py \
  --bundle-url 'S4_IMMUTABLE_HTTPS_BUNDLE_URL' \
  --sha256 'S4_TRUSTED_BUNDLE_SHA256' --version 'S4_RELEASE_VERSION' \
  --image 'S4_ACCEPTED_REGISTRY_IMAGE@sha256:MANIFEST_DIGEST' -- \
  --runtime docker --install-dir /private/pipeline-source \
  --command-dir /private/pipeline-source-command --port 18080
/private/pipeline-source-command/internship-pipeline status
/private/pipeline-source-command/internship-pipeline url
```

Use `--runtime podman` in Podman cells. These exact bootstrap flag names are shared with S4; verify the final shipped `--help` and bind the executed command to its hash before marking the row passed. The image platform digest must trace to CI's accepted platform artifact; a successful pull by itself doesn't establish that relationship. Runtime/Python installation and VM startup are guided dependencies, performed deliberately by the operator, rather than installer automation.

## Operator sequence and pass conditions

1. **Prepare isolated private storage.** Start on a declared fresh host without a source checkout, with a responsive engine and adequate measured disk. Use a new installation root, command directory, port and generated installation UUID. Inventory only this installation's resources and labels. Record initial engine/context and connection environment; no existing global context is changed. Check missing Python/runtime, stopped engine and ambiguous two-engine guidance without resetting or starting another user's VM.
2. **Install the exact bytes.** Execute the hosted command and retain bounded private timing/error transcripts. Test an occupied loopback port, foreign command/root, unsafe permissions and corrupted/incomplete bundle separately before allocating application resources. Confirm mode 0600 manifest, private root/markers/bundle, UUID labels, named-volume write permission, exact image, recorded data/config root, loopback-only port and healthcheck readiness. Record cold download/pull/start elapsed time, transferred bytes/cache/network and peak host/VM disk; send observed limits to S3/S4. Installer output must contain the URL and deliberately private raw-log command, never the setup token itself.
3. **Claim and reach useful data.** In the private terminal retrieve the unclaimed token, claim once, create the synthetic owner/profile and follow shipped setup documentation. Reuse S2's approved bounded provider/input envelope to reach the first useful job; when that envelope isn't authorized/available, record the job/provider gate pending. Reject reused claim tokens. Don't include passwords, token-bearing logs, resumes or connection values in public screenshots/evidence.
4. **Exercise interrupted/idempotent installation.** Interrupt a pull, container create and first start only for the new owned installation; rerun the same hosted command. Exercise an owned stopped container and an owned missing container with its retained volume. Confirm one manifest/UUID/volume remains, data survives and no empty replacement appears. A missing previously-created volume must refuse recovery; test this using a separately designated synthetic disposable fixture and retain it for operator review rather than removing the useful installation's volume. Missing/mismatched labels, mount, data/config root, image or port must refuse lifecycle changes. Change ambient/global connection selections and prove every saved command still targets its original endpoint; don't change or delete that endpoint itself.
5. **Remove the checkout dependency.** Make any source checkout inaccessible, retain the installed bundle and run `status`, `start`, `stop`, `url`, bounded sanitized `logs`, interactive `status --diagnostics` and `logs --diagnostics`. Owner login/CSRF/logout must work over the serving container. Verify jobs, settings and byte-identical retained PDFs survive stop/start. Exercise stopped-only token rotation on a separately unclaimed fixture and interactive owner recovery on the claimed fixture; running-container recovery must refuse, passwords must be prompted privately, and old sessions must be revoked.
6. **Take a complete stopped backup.** Stop the source and all separately launched writers. Inspect its owned container through the saved endpoint and record the local image ID privately. Follow T20's network-disabled, `--pull never` backup command, using that image ID and the manifest's `data_dir`. Use T20's separately labelled backup volume and network-disabled stdio export to a private owner-only host archive/directory; confirm both databases, the exact key, configuration/registries, retained uploads/provenance and PDFs exist in the completed T17 manifest. A backup while supported writers hold their locks must refuse. Hash/read checks use synthetic data; no provider/delivery calls are needed.
7. **Restore and manage a distinct destination.** Keep the original stopped container/volume/manifest. Execute the same verified hosted bundle using the recovery command below with no new image/runtime selection. Confirm new UUID/volume/port, the inspected source local image ID, pulls/network disabled for maintenance, stdin-only private transfer without host bind or UID overrides, archive manifest identity, `/var/data/restored`, fresh config and completion marker before container startup. Sign in with the retained owner, confirm sessions revoked, read retained PDFs, decrypt saved connections locally and inspect jobs/settings/confirmed delivery/sync ledgers. Confirm uncertain side effects require review and confirmed work isn't replayed. Run the recovered installed command's lifecycle, diagnostics and stopped-only owner recovery with the source checkout unavailable. Original bytes/resources must remain unchanged.
8. **Test failure and operator comprehension.** On a separate synthetic recovery destination, interrupt/fail restore and confirm both installer and installed manager refuse startup without completion. Preserve uncertain volume/root; a deliberate retry uses another fresh destination. After completed restore, interrupt container creation/start and confirm an ordinary same-destination rerun resumes without another restore or pull. Have an operator who didn't implement this tooling complete steps 1–7 using only shipped documentation; record obstacles, fix omissions, repackage if bytes change and rerun affected rows. Never delete recovery markers to force progress.

## Hosted recovery command

```sh
python3 /private/installer/bootstrap_installer.py \
  --bundle-url 'S4_IMMUTABLE_HTTPS_BUNDLE_URL' \
  --sha256 'S4_TRUSTED_BUNDLE_SHA256' --version 'S4_RELEASE_VERSION' -- \
  --restore-source /private/pipeline-source \
  --restore-from /private/backups/snapshot \
  --install-dir /private/pipeline-recovered \
  --command-dir /private/pipeline-recovered-command --port 18081
/private/pipeline-recovered-command/internship-pipeline status
/private/pipeline-recovered-command/internship-pipeline status --diagnostics
```

The source backup must be an owner-only regular host directory readable by the invoking user. The installer privately archives regular files/directories, checks temporary disk, and passes an immutable temporary tar through bounded subprocess stdin; the image UID receives it inside the new owned volume, with no host bind or permission change. Record `.backup-manifest.sha256`, untouched host backup hashes/modes, temporary-disk usage and volume space for copied backup plus restored data. The source must still have its owned stopped container and volume, because its inspected image ID and saved endpoint anchor this explicit recovery. Missing/deleted source containers or unavailable exact local images aren't a reason to follow a tag or create empty data; record that case blocked. If transferring to another host is a release requirement, separately supply/import the accepted same image and accept a destination registration procedure; this run doesn't certify it. Actual image-UID fresh-volume ownership, Docker/Podman stdio, rootless mappings and private backup-volume export require their own successful cell evidence; don't bypass private permissions globally.

After a completed restore, normal bootstrap reruns omit `--image` and use the saved destination paths; the installer validates the existing manifest and retains its exact local image ID. A first installation without an image remains an error. A retained complete reviewed bundle can likewise be rerun without an image argument. They retain the saved endpoint and data root. The same versioned bundle can be reacquired after its temporary extraction directory is removed; the management files already live in the destination's installed command bundle. Do not overwrite its bundle with a newer release.

## Evidence handoff and current limits

For each cell record date/operator, full exact command with placeholders resolved in a private transcript, source/run/artifact identities, host versions, each numbered outcome, elapsed measurements, resource/permission/context observations, private backup checks, restored document hashes, retained ledger counts and unfamiliar-operator obstacles. Public evidence should contain only synthetic aggregate facts and sanitized command details. Link S2 useful-job acceptance and S3 measurements rather than inventing provider/runtime success here. Record failed, blocked and untested checks separately.

The first-release wording is **fresh installation and complete exact-image recovery**. There is no automatic updater, development-snapshot upgrade, cross-release migration, downgrade or cross-engine compatibility promise. All eight host cells, published-download execution, real bind/volume permissions, port forwarding and unfamiliar-operator recovery remain untested here. Final support scope is an owner decision tied to actual successful cells.
