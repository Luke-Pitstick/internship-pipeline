# GitHub Actions candidate execution

October 8, 2026. Owner authorized committing, pushing and dispatching the repaired candidate. Branch: `codex/release-repairs-20261008`. HTTPS OAuth lacked workflow scope; the existing configured SSH credentials successfully pushed to the same repository without changing credentials or global Git settings.

The initial candidate `0ce882f4081ed8ab99ac16799a85ab013bc37224` contains application repair commit `676de22` and the CI/package/evidence commit. Its exact SHA was verified on [run 37830607054](https://github.com/Luke-Pitstick/internship-pipeline/actions/runs/37830607054).

That Linux run passed lint, strict typing, frontend check/build/bundle budget and 34 browser cases, but failed eight PDF-dependent Python tests (684 passed) and the automatic-generation browser case. Both image jobs were correctly held behind failed prerequisite checks. Installing TeX alone was insufficient: the template requires `lmodern.sty`, while `--no-install-recommends` left out the separate `lmodern` package. The dependency log lists it only as recommended. The [Debian package file list](https://packages.debian.org/bookworm/all/lmodern/filelist) identifies its TeX support files separately from `fonts-lmodern`.

Follow-up adds explicit `lmodern` to both Linux test jobs and the Dockerfile, plus `kpsewhich lmodern.sty` to fail early if the package contract breaks. Application source and test expectations are unchanged. The original 201-file manifest remains a historical record of the initial candidate; only Dockerfile/workflow entries differ after this follow-up. R6 remains pending until a corrected exact-SHA run accepts both platforms and engines.
