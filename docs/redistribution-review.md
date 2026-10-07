# Redistribution review — release preparation

October 7, 2026. This is a local metadata/template/asset inventory, **not legal clearance or an open-source license grant**. No root `LICENSE`/`NOTICE`, Python project license declaration or agreed project-license choice exists in this checkout. The earlier [repository audit](open-source-step-1.md) identified the same unresolved decision.

## Required owner decision

The project owner must select the intended license, confirm authority over the contributed source/template/assets and supply the applicable copyright holder/year before publication. Then add the chosen license text and matching package metadata, establish contribution terms/private security contact, and review redistributed third-party notices against the actual artifacts. This preparation does not select a license on the owner's behalf or silently license existing work. Until those inputs exist, **open-source release remains blocked**.

## Locked dependency metadata

[Machine-readable inventory](redistribution-inventory.json) records local distribution metadata and declared license-file paths for the locked Python packages, plus license fields from `web/package-lock.json`. It contains no private runtime inputs. The scope includes development/build dependencies; being in this inventory does not prove that a package ships in the runtime image.

There are 62 Python lock entries including the project: 60 third-party distributions are installed and match their lock versions; Windows-only `colorama` is not installed on this host and its wheel/license text was not inspected. All 60 installed entries expose license expression, legacy field or classifier metadata. The npm lock has 84 third-party package entries and all declare a license field. These are package metadata assertions, not a license-compatibility verdict or proof that required notice texts were shipped.

Direct runtime Python metadata observed:

| Dependency | Locked version | Declared local license metadata |
| --- | --- | --- |
| pydantic | 2.13.5 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| PyYAML | 6.0.3 | MIT |
| apprise | 1.13.1 | BSD-2-Clause |
| pypdf | 6.19.0 | BSD-3-Clause |
| ats-scrapers | 0.3.0 | MIT |
| python-jobspy | 1.2.0 | MIT |
| fastapi | 0.142.2 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| pwdlib | 0.3.1 | MIT classifier |
| cryptography | 46.0.7 | Apache-2.0 OR BSD-3-Clause |
| python-docx | 1.2.0 | MIT |
| google-auth | 2.60.0 | Apache 2.0 legacy field |
| tzdata | 2026.5 | Apache-2.0; additional license files retained in metadata inventory |

Direct frontend/build packages declare MIT for Svelte, SvelteKit, adapter-static, the Svelte Vite plugin, Svelte check, Vite and Node types; Playwright and TypeScript declare Apache-2.0. Exact installed/locked versions and transitive entries are in the inventory. Where a legacy license field contains a full text, its inventory summary is truncated and explicitly flagged; consult the package's actual license file before assembling notices. Some packages declare no `License-File` metadata but contain license files in the installed distribution; those paths are also recorded rather than treating the missing field as missing permission.

## Template, fonts and image assets

The active master template is an inline literal in `src/internship_pipeline/resumes/master_template.py` with its own version/hash. It uses article, fontenc, inputenc, Latin Modern (`lmodern`), textcomp, geometry, enumitem, needspace and `glyphtounicode`. The code labels it application-owned, but provenance/ownership and the selected project license still require the owner's confirmation; that label is not legal evidence. No arbitrary uploaded template or former personal LaTeX source-edit path is shipped as the current generation workflow.

The frontend declares Inter/system fonts in CSS and has no `@font-face` declaration or bundled web-font file in the application source. Declaring a font name does not redistribute that font. `web/design/` contains generated concepts and synthetic browser reference screenshots documented in its README; the frontend build does not ship those design images. Their provenance/distribution choice still belongs in a source-release review. The committed PDF/DOCX fixtures are identified as synthetic and need the same final provenance review before redistribution.

Docker uses Python/Node Bookworm base images, the uv build-stage binary and Debian `texlive-latex-extra`/`texlive-fonts-recommended`. The resulting Debian/TeX/font/system dependency set has **not** been inspected because no actual image finished building. Retain the relevant package license/copyright/notice files, inspect font embedding/redistribution terms and generated PDF contents, and reconcile a full image SBOM before publishing. Metadata from the macOS Python environment cannot clear those Linux image components.

## Remaining artifact gates

| Missing input or evidence | Required action |
| --- | --- |
| Owner-selected project license and source/template/asset authority | Obtain explicit owner decision, add license/package metadata and identify required copyright/contribution terms. |
| Complete runtime/build dependency notice review | Review actual dependency license texts and applicable notices, including absent conditional packages; generate an artifact-scoped notice bundle after choosing the project license. |
| Built image and package/font inventory | Finish T18 on a healthy runtime, retain SBOM/provenance and review Debian/TeX/base-image content and embedded fonts before registry publication. |
| Source-release privacy/provenance | Review tracked source, historical references, synthetic fixtures and design assets at the exact release revision; exclude personal runtime inputs and unapproved assets. |
| Public redistribution claim | Close the above gates and record decision/evidence in [release readiness](release-readiness.md). A passing metadata scan alone cannot close this gate. |
