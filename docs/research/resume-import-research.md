# Resume import: source fidelity and structured extraction

Research date: 2026-10-20. This revisits the earlier
[resume import research](resume-import.md) after reproducing failures on a real
PDF/TeX pair. Recommendations are engineering judgments, not comparative
accuracy claims. Public source code and official documentation were researched;
the private resume was not uploaded to research services.

## Decision

Keep extraction, entry grouping, and profile validation separate. Improve the
local PDF path with positional text extraction, retain the existing static
`pylatexenc` TeX parser, and let the optional model return typed resume entries
directly. Both paths should finish in the same validated, editable profile draft.
The previous model-to-pipe-delimited-rows-to-heuristics design throws away
structure the model has already identified, so it can reproduce the local
parser's mistakes even when the PDF transcription is accurate.

The local reproduction identified several independent failures: an unrecognized
“Technical Experience” heading hid whole jobs; an uncommon leadership title did
not match the role dictionary; adjacent PDF font spans lost spaces; hyperlink
annotation targets were absent; project technologies and a single-month project
date were lost; and a standalone TeX list marker became a skill. These failures
require tests at the final draft boundary, not merely assertions that extracted
text is nonempty. This diagnosis comes from this session's local reproduction,
not from a library's marketing claims.

## What OpenResume contributes

OpenResume's parser runs a useful four-stage pipeline: PDF text items, lines,
sections, then resume fields. Its entry point explicitly limits its algorithm to
single-column English resumes. It is a valuable implementation reference, but
does not establish support for this application's broader document set.
[Pipeline source](https://github.com/xitanggg/open-resume/blob/main/src/app/lib/parse-resume-from-pdf/index.ts).

Its PDF.js adapter preserves coordinates, dimensions, and original font names.
Line assembly uses end-of-line signals and distances between text fragments.
The important design lesson is to retain geometry and typography while deciding
which text belongs together; a flat string cannot recover evidence already
discarded. The adapter also deliberately leaves content-stream order unsorted,
which is unsuitable as a general reading-order solution for arbitrary design
exports. [PDF adapter](https://github.com/xitanggg/open-resume/blob/main/src/app/lib/parse-resume-from-pdf/read-pdf.ts),
[line assembly](https://github.com/xitanggg/open-resume/blob/main/src/app/lib/parse-resume-from-pdf/group-text-items-into-lines.ts).

Section recognition combines visual emphasis with heading keywords; entry
segmentation uses vertical gaps and bold transitions. Attribute extraction scores
several features instead of requiring one universal header order. These are useful
signals to combine with dates, indentation, and section context. They should not
be treated as certainty: OpenResume still relies on an English job-title list,
and its company inference rewards bold text after excluding title/date
candidates. [Sections](https://github.com/xitanggg/open-resume/blob/main/src/app/lib/parse-resume-from-pdf/group-lines-into-sections.ts),
[entry boundaries](https://github.com/xitanggg/open-resume/blob/main/src/app/lib/parse-resume-from-pdf/extract-resume-from-sections/lib/subsections.ts),
[employment fields](https://github.com/xitanggg/open-resume/blob/main/src/app/lib/parse-resume-from-pdf/extract-resume-from-sections/extract-work-experience.ts).

OpenResume uses AGPL-3.0; this repository declares MIT. The recommendation is an
independent implementation of the structural approach, not copying its parser
into this repository. Its license is relevant when considering code reuse.
[OpenResume license](https://github.com/xitanggg/open-resume/blob/main/LICENSE).

## Library choice

| Option | Evidence and consequence |
| --- | --- |
| `pypdf`, already installed | Layout mode approximates rendered spacing; text visitors expose text transforms and font information. Its documentation warns that coordinates can be wrong in complicated documents and that extraction has no OCR. Retain it where its existing PDF validation/metadata capabilities are useful, but the real-file spacing defect justifies evaluating another extraction backend. [Documentation](https://pypdf.readthedocs.io/en/stable/user/extract-text.html). |
| `pdfplumber` / `pdfminer.six` | Provides character/word boxes, character fonts, duplicate-character removal, link annotations, and configurable spacing. It has no OCR. This is the best small addition for the observed digital-PDF failure because the needed evidence remains accessible. Its license is MIT. [API documentation](https://github.com/jsvine/pdfplumber), [license](https://github.com/jsvine/pdfplumber/blob/stable/LICENSE.txt). |
| `pylatexenc` 2.10, already installed | `LatexWalker`, `MacroSpec`, parsed argument nodes, and `MacroTextSpec` already support a static syntax-aware solution. Retain the installed v2 APIs; current development-branch examples can use different v3 APIs. [v2 macro API](https://pylatexenc.readthedocs.io/en/v2.10/macrospec/), [v2 text conversion](https://pylatexenc.readthedocs.io/en/v2.10/latex2text/). |
| PyMuPDF | Supplies text extraction, rendering, and OCR integration, but its AGPL/commercial licensing differs from this project's existing dependency choices. No evidence here demonstrates that adopting it would fix the field-mapping bugs. [Official feature and licensing documentation](https://pymupdf.readthedocs.io/en/latest/about.html). |
| Docling | Provides document layout, reading order, table structure, and OCR in a larger document-processing system. Its local execution is useful for a future complex-document evaluation, but introduces a separate processing stack when the reproduced file is digitally generated. [Project documentation](https://github.com/docling-project/docling). |
| Tesseract | A local OCR engine for image text; it does not assign recognized words to resume fields. Add OCR only as an explicit tested scan capability, with image rendering and resource limits. [Official project](https://github.com/tesseract-ocr/tesseract). |

No cross-library accuracy or throughput benchmark was conducted as part of this
research. A dependency should be accepted based on the paired-file regression
and a varied layout corpus, not on a general PDF benchmark.

## Local extraction design

### Digital PDF

Use positional word extraction for normal text, with page and bounding-box
provenance retained through row assembly. Read link targets from annotations and
associate them with overlapping text. `pdfplumber` exposes these as `hyperlinks`.
It also documents that `use_text_flow=True` follows underlying PDF order, which
need not be logical; its `extra_attrs=["fontname", "size"]` splits words at style
changes. Prefer constituent characters for style evidence rather than forcing
every font change to become a word boundary.
[Extraction and object APIs](https://github.com/jsvine/pdfplumber).

The following are application design recommendations:

1. **Recover words before interpreting headers.** Preserve real spaces and infer
   missing spaces from character gaps relative to font size. Verify bold/regular
   boundaries around metrics, punctuation, URLs, and ordinary words. Avoid a
   global regex that inserts spaces around digits, because identifiers and
   technology names legitimately contain digits.
2. **Distinguish right-aligned metadata from independent columns.** An employer
   on the left and a date on the right form one header; a full-height skills
   sidebar is a separate region. Use several aligned rows and section boundaries
   before splitting columns, then keep subsequent bullets attached to the
   correct entry.
3. **Use structure before title vocabularies.** Section context, repeated header
   patterns, dates, and indentation must allow an unfamiliar job title.
   Vocabulary can disambiguate two header fields, but should not determine
   whether an entire experience exists.
4. **Preserve information that does not fit a field.** Keep a literal date or
   unresolved subtitle in the supporting text. Do not invent a month for
   year-only dates or discard a single-month project because it is not a range.
   Retain uncategorized source content for review.
5. **Check coverage.** A document with a recognized experience section but no
   imported experience, or substantial unused nondecorative text, should produce
   a visible partial-import warning. Do not report complete success merely
   because a name and email were found.

Maintain the existing upload, page, decoded-content, process-time, memory, and
output-size bounds around the parser. A small compressed PDF can require much
more memory while parsing; pypdf documents the content-stream expansion problem.
[Resource considerations](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).
Apply limits before materializing large character collections and reject
oversized output explicitly instead of quietly dropping the end of the resume.

### TeX

Parse syntax and literal arguments without compiling or executing the uploaded
document. Register known argument signatures and conversion rules separately,
using `nodeargd.argnlist` to preserve nested formatting and entry arguments.
The installed parser supports this directly.
[Macro parsing](https://pylatexenc.readthedocs.io/en/v2.10/macrospec/).

Treat generic custom command arguments as source text, while recognizing
explicitly supported entry/list/section shapes. Reading an argument count from
`newcommand` does not establish the meaning or output order of those arguments.
An unknown command that depends on a definition body, class file, or included file
must be reported as an extraction limitation when its content cannot be
recovered safely. Suppress empty list markers before skill extraction, retain
`\href` targets, preserve argument separators, and normalize wrapped bullet
text only after identifying its boundaries.

Keep input-directory configuration disabled: `LatexNodes2Text` ignores
`\input`/`\include` by default and can read files if explicitly configured.
Do not enable that behavior for an untrusted upload. More complete TeX execution
would introduce a separate sandboxed rendering problem rather than solve the
current mapping defect.
[Text conversion and input-file handling](https://pylatexenc.readthedocs.io/en/v2.10/latex2text/).

### Scans and mixed documents

Digital extraction cannot read image-only pages. Detect this per page, since a
partially scanned document can otherwise appear successful. A local-only request
should clearly identify unreadable pages and ask for a selectable-text PDF/TeX
source unless an explicit OCR path is implemented. A configured native PDF model
can be the selected scan-reading method, with accurate method labeling and
review. Do not automatically OCR every digital page, or imply that OCR is part
of local import when it is not.
[pypdf limitations](https://pypdf.readthedocs.io/en/stable/user/extract-text.html),
[Claude PDF support](https://platform.claude.com/docs/en/build-with-claude/pdf-support).

## Model extraction contract

The existing `providers/structured.py` already constructs provider-specific
structured-output requests and rejects incomplete/refused responses. Reuse that
boundary. Replace the model's pseudo-CSV rows with typed entries containing the
fields the editable profile supports: identity, education, experience, projects,
skills, links, literal supporting text, and source page references. Validate
these directly and feed them to the same draft preparation/save flow; do not
serialize them back into strings and guess their fields again.

Prompt for literal transcription and classification, with empty values for
missing information, no qualification inference, and an explicit unreadable or
unrelated-document outcome. Preserve bullets and metrics rather than rewriting
them. Treat instructions embedded in the resume as source content. Retain limits
on entry counts, strings, total response size, and page references.

Schema conformity proves shape, not factual correctness. OpenAI explicitly
documents that structured output can contain mistakes and that forcing unrelated
input into a schema can induce hallucination. Use the original PDF for review,
label AI-produced text, and assess field/bullet fidelity in evaluation.
Generate the provider schema from the validated type definitions where practical
to avoid divergent contracts.
[Structured-output guidance](https://developers.openai.com/api/docs/guides/structured-outputs).

Use a portable provider schema and enforce detailed bounds after parsing.
Anthropic documents unsupported constraints including `minLength`, `maxLength`,
numeric bounds, and most array bounds; naively forwarding every Pydantic schema
constraint can produce a provider 400 response. Its objects require
`additionalProperties: false`.
[Claude schema limitations](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

### Capability checks

| Transport | Grounded rule |
| --- | --- |
| OpenAI Responses API | Native PDF input sends extracted text and page images to a vision-capable model. Check the selected model against documented capability evidence and the connection's actual endpoint, rather than accepting every `gpt-*` name. The old allowlist ending at GPT-5.2 excludes documented newer models. [File-input contract](https://developers.openai.com/api/docs/guides/file-inputs). |
| Anthropic Messages API | Current Models API responses expose `capabilities.pdf_input.supported`, `capabilities.structured_outputs.supported`, and `lifecycle`; preserve these rather than reducing the catalog to ID/name alone. Require both relevant capabilities when supplied. Current PDF docs say active models support PDFs. [Models API](https://platform.claude.com/docs/en/api/models/list), [PDF support](https://platform.claude.com/docs/en/build-with-claude/pdf-support). |
| OpenRouter Chat Completions | `architecture.input_modalities` distinguishes `file` from `image`; image input alone is insufficient evidence for native PDF. Require native file capability and supported structured-output parameters, send `file-parser` with `engine: "native"`, and require provider parameter support. Otherwise OpenRouter may parse the PDF through another engine. [Model metadata](https://openrouter.ai/docs/guides/overview/models), [PDF routing](https://openrouter.ai/docs/guides/overview/multimodal/pdfs). |
| ChatGPT account transport or custom endpoint | A successful text connection test does not establish the same native-PDF contract. Keep native-file claims limited to transports with documented and tested support. |

Examples independently verified in current official OpenAI documentation include
[`gpt-5.4`](https://developers.openai.com/api/docs/models/gpt-5.4),
[`gpt-5.6-sol`](https://developers.openai.com/api/docs/models/gpt-5.6-sol),
[`gpt-6-astra`](https://developers.openai.com/api/docs/models/gpt-6-astra),
[`gpt-6.1-sol`](https://developers.openai.com/api/docs/models/gpt-6.1-sol), and
[`gpt-6-luna`](https://developers.openai.com/api/docs/models/gpt-6-luna).
These are examples of documented capabilities, not recommendations to change
the user's selected model or claims that a credentialed extraction test passed.
Date-snapshot aliases must map to a documented base model; an unknown future
model must not acquire file support simply because its name matches a broad
regular expression.

On a selected AI method's failure, surface the failure and offer the independently
working local method explicitly. Do not silently disguise local output as a
successful AI import. A first successful extraction request proves more than a
text-only connection probe, but still does not prove resume accuracy.

## Evaluation that can establish improvement

The first acceptance case is the actual PDF/TeX pair. Compare both final drafts
against a manually reviewed expected record: the identity, education, four
work/leadership entries, two projects, their complete bullets/metrics, 25 listed
skills, available URLs, and explicit dates. Keep private originals outside the
committed fixture set. Commit a structurally equivalent anonymized example with
the font changes, custom macros, headings, and uncommon title that caused the
failure.

Use a small, diverse corpus before broad accuracy claims:

| Case | What it must reveal |
| --- | --- |
| Single-column PDF with font changes inside bullets | Missing/extra spaces and altered numbers. |
| Employer-first and title-first headers, uncommon title | Field association without vocabulary dependence. |
| Right-aligned dates versus a true two-column sidebar | Whether row alignment is confused with column order. |
| Multiple education entries, year-only dates, single-month project | Grouping and date specificity. |
| Wrapped bullets and a job crossing a page boundary | Lost text or a bullet attached to the wrong employer. |
| Hidden hyperlink targets and visible short labels | Correct target-to-entry association. |
| TeX optional arguments, nested formatting, list wrappers, unknown macro | Safe parsing and honest partial results. |
| Image-only and mixed scanned/text PDF | Explicit unsupported-page handling or measured OCR/native-AI behavior. |
| Empty, non-resume, malformed, encrypted, oversized input | Useful failure without partial silent acceptance. |
| AI refusal, truncation, unknown fields, invalid pages, provider errors | Validated rejection and clear recovery. |

Measure entry recall, field precision, bullet-to-entry association, numeric/URL
fidelity, skill precision/recall, and unused source content. A single average
score can hide the most harmful failure: a correct achievement assigned to the
wrong employer. Record per-document failures and method/provider/model, and keep
the corpus stable across prompt or parser changes.

Finally verify the user-facing draft in a browser: every imported entry must be
discoverable, editable, and preserved by the normal save/reload path. Report
local deterministic tests, mocked provider tests, and credentialed model
acceptance separately. This research establishes the design rationale; it does
not claim those implementation acceptance checks have already passed.

## Implementation and acceptance, October 20

The implementation uses pdfplumber positional words and hyperlink annotations, preserves independent-column geometry, expands section recognition, and maps typed AI records directly into editable fields. Local parsing is the default; optional AI accepts extracted text for models without proven native-PDF support. The import has its own 8,192-token output allowance.

A credentialed synthetic test exposed a separate timeout cause: the selected DeepSeek model defaults to high reasoning effort. Its current OpenRouter catalog advertises optional reasoning with `none` support, so the text-import request now disables it only when that exact capability is present. This follows [OpenRouter reasoning metadata documentation](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens#discovering-per-model-reasoning-options); hiding reasoning text alone would not fix the latency. The text request also uses temperature zero only when the selected model advertises support, following [OpenRouter parameter documentation](https://openrouter.ai/docs/api/reference/parameters). Consented live extractions of both the real PDF and TeX subsequently passed the field-level assertions and save/reload checks. Earlier repeatability checks exposed empty entry lists and a valid dual-degree transformation rejected by overly strict substring grounding; the first now has an explicit local-recovery regression and the second has a bounded deterministic validation rule.

All four private PDF/TeX variants passed deterministic macOS and network-disabled Linux acceptance: four experiences, two projects, one education record, 25 listed skills, 16 bullets, two URLs and save/reload. The actual PDF also filled the isolated browser form correctly. Private files and provider responses are excluded from committed fixtures. This establishes acceptance for the reported documents and the tested provider, not universal résumé accuracy or deployment of the installed application.
