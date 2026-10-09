# Image notice review — October 8, 2026

**Current status (October 9):** [RC3 acceptance](rc3-status.md) supersedes older preparation results below. RC3 passed source/image and all four Linux registry-installer/recovery cells; it remains a private draft, with public, live and human/trial gates open. RC1 and RC2 are held drafts.

The accepted amd64 OCI artifact from [run 37838328196](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37838328196), source `df4835f7674007de38a45045f593c5a0b314b680`, was inspected without executing it. Its config digest is `sha256:c0e002c301d6c50ed336090c3d2f542313479e4554d93c3eb2e397ce01b5bcc6`. The [path/hash inventory](image-notice-inventory-df4835f.json) records 467 observed Debian, TeX and Python notice files. The SBOM has 300 package entries, including duplicates/build-cache entries, and 85 entries with `NOASSERTION`; those counts are not a count of unique runtime dependencies or a finding that those packages lack licenses.

## Packaging defects and correction

The Dockerfile omitted the project LICENSE from its build context copies. No project distribution license was found in the inspected image. It also copied only the frontend build, which lacked a bundled dependency notice artifact, and retained the build-only uv executable and download cache.

The corrected Dockerfile copies LICENSE before building the Python project. Vite's native `build.license` option generates `third-party-licenses.md` for the dependencies actually bundled; the local production build includes Svelte, SvelteKit and devalue notices and the static adapter preserves it in `build/`. The image build fails if either the project license or frontend notice file is absent or empty. uv is temporarily mounted from its pinned build stage, and its cache uses a build cache mount, so those build-only files do not remain in runtime layers. See [Vite license output](https://vite.dev/config/build-options.html#build-license) and [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/#using-uv-temporarily).

The corrected frontend production build passed and contains 3,524 bytes of bundled notices. This source change requires new full candidate acceptance; the historical artifact inventory above cannot certify the corrected image.

## Remaining boundaries

The inspected Debian image retains Latin Modern and TeX copyright/license documents, including the GUST Font License within the lmodern copyright file. This inspection establishes presence, not complete review of every dependency's terms or satisfaction of source-distribution obligations. The final candidate's SBOM, image notices, conditional packages, embedded fonts and any required corresponding sources still need reconciliation before public redistribution.

A scan of 323 tracked files at the curl-installer preparation snapshot found no private-key or provider-token patterns. It does not establish absence of all private information, nor clear Git history or third-party rights. The design README identifies generated concepts and synthetic screenshots; PDF/DOCX fixtures are named synthetic. No repository visibility change, public release, license-rights representation or security-reporting verification is implied by these checks.
