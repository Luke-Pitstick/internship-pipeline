# Resume import research

Research date: 2026-10-19. Scope: fill the existing editable profile from PDF and
LaTeX resumes, use the user's configured model only when it supports native PDF
input, and keep a useful non-LLM import path. Recommendations below are design
judgments, not measured accuracy claims.

## Recommendation

Keep `pypdf` and `pylatexenc`, which are already dependencies, and improve the
structure carried from extraction into profile fields. A better PDF-to-text
library alone cannot assign an employment date to the right employer or fill
fields the importer never maps. Use a shared deterministic section/entry mapper
for PDF text and TeX structure. Give native PDF models a bounded transcription
task that preserves entries, dates, links, and bullets, then use that same mapper.
Do not ask a text-only model to guess fields from flattened extraction.

Maintain the original source and expose editable results. Preserve ambiguous
content in an entry's text rather than discarding it or inventing a title,
employer, degree, or date. Mark model transcription accurately; schema-valid
output alone does not demonstrate that it matches the document.

## What the existing libraries can do

| Option | Relevant capability | Limitation and decision |
| --- | --- | --- |
| Existing `pypdf` | Pure Python text extraction, fixed-width layout mode, text-position visitors, PDF metadata/annotations. | Content-stream order is not reliable reading order; layout mode ignores visitor callbacks. It cannot read image-only pages. Keep for normal digital resumes, preserve line/column separation, and explicitly detect unreadable pages. [Extraction documentation](https://pypdf.readthedocs.io/en/stable/user/extract-text.html), [API](https://pypdf.readthedocs.io/en/stable/modules/PageObject.html#pypdf._page.PageObject.extract_text). |
| Existing `pylatexenc` 2.10 | `LatexWalker`, `MacroSpec`, parsed argument nodes, environments, source positions, text decoding. | This is a syntax parser, not a full TeX engine; custom command meaning must be supplied. Use the installed v2 interface, not examples from v3 beta. [v2 parser](https://pylatexenc.readthedocs.io/en/v2.10/latexwalker/), [v2 macro specifications](https://pylatexenc.readthedocs.io/en/v2.10/macrospec/). |
| `pdfplumber` / `pdfminer.six` | Character and word bounding boxes, crop regions, configurable spacing, font attributes, ligature handling, and visual debugging. `pdfplumber` uses MIT licensing. | It has no OCR and does not automatically map resume fields. A strong candidate if representative PDFs demonstrate that pypdf layout loses entry boundaries; do not install a second parser merely to obtain another flat string. [Project documentation](https://github.com/jsvine/pdfplumber), [layout analysis](https://pdfminersix.readthedocs.io/en/latest/topic/converting_pdf_to_text.html). |
| PyMuPDF | Text blocks/words, rendering, extraction, and OCR integration in a mature native engine. | Its AGPL/commercial dual licensing is a materially different distribution choice for this MIT project. Do not add it casually as a parser replacement. [Official feature and license documentation](https://pymupdf.readthedocs.io/en/latest/about.html). |
| Docling | Structured document representation with layout, reading order, and OCR options; local execution. The standard PDF pipeline can use specialized models without an LLM; a native model-free pipeline also exists. | Standard processing introduces downloaded weights, inference dependencies, and deployment/runtime work. The code is MIT, but individual model licenses are separate. Evaluate for complex-layout/OCR demand after an evidence corpus justifies it. [Project](https://github.com/docling-project/docling), [pipeline options](https://docling-project.github.io/docling/reference/pipeline_options/), [offline model setup](https://docling-project.github.io/docling/usage/advanced_options/). |
| Tesseract OCR | Local image-to-text engine with Apache 2.0 licensing. | Requires image rendering and OCR integration; recognizing words does not associate them with employers or degrees. Useful for scans, not a reason to OCR digital documents that already contain reliable embedded text. [Official project](https://github.com/tesseract-ocr/tesseract). |
| spaCy rules / traditional NER | Rule-based matchers can combine token patterns and entity annotations. | A generic person/organization recognizer does not resolve whether an organization is an employer, school, client, or project owner. Introduce only if a labeled corpus shows a useful improvement over structural rules. [Official matching documentation](https://spacy.io/usage/rule-based-matching). |
| `pyresparser` | Existing resume-oriented extraction of contact information, skills, organizations, degrees, and designations using spaCy/NLTK. | The documented output is lists of extracted attributes, not the paired employment/education records this profile needs, and its setup adds language resources. It is not a drop-in solution to entry association. [Maintainer documentation and output example](https://github.com/OmkarPathak/pyresparser). |

No throughput or comparative accuracy benchmark was performed for these options.
Claims that a replacement is “more accurate” require testing on this app's resume
formats, particularly multi-column and custom-macro examples.

## Deterministic extraction design

### LaTeX

Keep syntax structure until semantic extraction is complete. The v2 parser can
register command argument signatures in `LatexContextDb` and exposes arguments as
`nodeargd.argnlist`, so nested formatting need not destroy field boundaries.
`LatexNodes2Text` supports configurable macro text handling, including
replacement functions. These existing capabilities are sufficient for targeted
resume command handling. [Macro API](https://pylatexenc.readthedocs.io/en/v2.10/macrospec/),
[text converter API](https://pylatexenc.readthedocs.io/en/v2.10/latex2text/).

Recommended behavior:

1. Extract identity commands even when they appear before `\begin{document}`:
   resume classes commonly put names, email, phone, and links in setup commands.
2. Preserve `\section`, `\item`, table cells/row breaks, `\href` targets, and
   command arguments as logical boundaries instead of concatenating their text.
3. Recognize common resume entry shapes such as a four-argument subheading, plus
   class-specific entry commands. Preserve the argument order specified by each
   supported command; there is no universal “argument 1 is job title” rule.
4. Decode accents, escaped punctuation, and formatting through pylatexenc.
   Preserve readable text in unknown groups. Skip layout-only commands and
   macro-definition bodies so template code does not become user experience.
5. Never execute uploaded TeX just to import a profile. Static parsing keeps
   import independent of TeX packages, shell escape, external files, and PDF
   rendering.

### Digital PDFs

PDF stores drawing instructions rather than semantic paragraphs. Absolute
character positions, tables, ligatures, and images explain why text extraction
can lose reading order. pypdf's documentation explicitly distinguishes these
problems from OCR and cautions against assuming that every file has usable text.
[pypdf explanation](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).

Recommended behavior:

1. Preserve the layout text's horizontal gaps until rows and columns have been
   interpreted. A date aligned at the right edge is usually part of the entry
   at its left; a full-height sidebar is a different region.
2. Group lines into sections and entries before mapping fields. Heading aliases,
   dates, explicit separators, bullets, and blank lines provide useful evidence;
   none should be treated as a universal rule in isolation.
3. Populate existing title, company, location, dates, current-role flag, and
   links from entry headers while retaining bullet text beneath that entry.
   Keep multiple education records distinct, and separate degree/major,
   institution, and graduation evidence.
4. Scope identity extraction to the header and contact regions. A title in an
   experience entry is not a candidate name. A street address should not be
   inferred from an employer location.
5. Read hyperlink annotations when visible anchor text hides a target. Normalize
   explicit link types without inventing URLs.
6. Treat image-only or mixed scanned pages as an extraction limitation. Without
   native PDF inference or an installed OCR path, clearly report that limitation
   rather than reporting an empty successful import. OCR should be a bounded
   page-processing feature with a real acceptance corpus if added.

### Shared mapping

Use one deterministic representation of logical entries for both formats.
Separate document extraction, entry segmentation, and profile mapping so that a
PDF layout improvement does not require a second set of profile heuristics.
Normalize whitespace and date punctuation, but preserve source specificity:
`2023` must not become an invented January 2023 start date.

For unknown templates, retain the source-backed entry text and fill only
unambiguous fields. A parser can use heuristics without disguising uncertain
results as verified facts.

## Native PDF model support

Use the configured provider and model. An API being “OpenAI compatible,” a model
accepting images, or a successful text connection test does not establish that
the specific connection accepts PDF content.

| Provider | Native request | Capability decision |
| --- | --- | --- |
| OpenAI Responses | A user content item with `type: "input_file"`, `filename`, and base64 `file_data`, alongside an instruction item. | Official docs describe visual PDF processing on vision-capable models, with extracted text and page images supplied together. Use documented, tested model identifiers/families; unknown or specialized text/audio variants must not inherit support solely from a `gpt-` prefix. [File input guide](https://developers.openai.com/api/docs/guides/file-inputs). |
| Anthropic Messages | `type: "document"` with `source: {type: "base64", media_type: "application/pdf", data: ...}`. | Current docs say all active models support PDF. Prefer an active model identity verified against the provider catalog; this does not prove support for every historical `claude-3-*` identifier. [PDF support](https://platform.claude.com/docs/en/build-with-claude/pdf-support). |
| OpenRouter Chat Completions | `type: "file"` with a filename and a PDF data URL; explicitly select the file-parser plugin's `pdf.engine: "native"`. | Require `file` in the selected model's `architecture.input_modalities`. `image` alone is different. Without an explicit native engine, unsupported models can trigger Mistral OCR with separate charges, contrary to a native-PDF-or-local-only policy. [PDF inputs](https://openrouter.ai/docs/guides/overview/multimodal/pdfs), [model properties](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties). |
| ChatGPT login / local or other adapters | Only a separately implemented and verified document transport can establish support. | The inspected repository's generic structured connection code uses fixed OpenAI, Anthropic, and OpenRouter endpoints, with a distinct ChatGPT authentication path. Public API PDF support alone does not establish that the login adapter supports the same payload. Leave unsupported transports on deterministic extraction. See `src/internship_pipeline/providers/structured.py` and `connections.py`. |

OpenAI documents a 50 MB aggregate file limit; Anthropic documents a 32 MB
request limit with page/context limits. The application's own smaller upload,
page, response, and timeout limits should remain authoritative. PDF inference
consumes text and visual input, so its cost is not equal to processing only the
extracted text. [OpenAI limits](https://developers.openai.com/api/docs/guides/file-inputs),
[Anthropic requirements](https://platform.claude.com/docs/en/build-with-claude/pdf-support).

Recommended inference contract: transcribe the resume into a bounded logical
structure, preserving source text and field associations, and output no inferred
skills, rewritten achievements, or invented dates. Validate that structure before
the deterministic mapper receives it. Provider errors should produce the local
import result with a clear note when local extraction is usable; unusable scans
must remain visibly incomplete. This recovery behavior is not a compatibility
layer: it is the required non-LLM product path.

## Acceptance evidence

Test outcomes that match editable fields, not just that extracted text contains
words. A useful focused corpus includes:

- A digital one-column PDF with right-aligned employment dates and wrapped
  bullets, asserting company/title/location/start/end/current and links.
- A two-column PDF with a skills sidebar, proving that sidebar lines do not
  become employment headings or bullets.
- A TeX resume with nested formatting, accents, custom subheading commands,
  header setup before the document body, and multiple education entries.
- Class-style TeX entry commands with different argument orders, proving that
  dates and organizations stay associated with the correct entry.
- A PDF with hidden link annotation targets and a document with a misleading
  title/name-like line outside the header.
- Image-only and mixed scanned PDFs, proving the limitation is visible rather
  than falsely reporting that the entire document was imported.
- Mocked native-provider request/response tests for document content, model
  gating, unknown models, authentication mode, malformed output, and the
  OpenRouter native-engine requirement.

Mock transport tests verify application contracts; they do not establish live
provider acceptance or extraction accuracy. Keep that distinction in release
notes and do not send private resumes to paid services merely to run tests.

## Implemented and verified in this change

Kept the existing dependencies and added shared entry grouping/field mapping,
conservative PDF column ordering, moderncv/AltaCV signatures and preamble contact
handling, and native PDF routing for supported tested API connections. The import
form offers local-only PDF parsing and reports which path was used. AI source rows
are labeled as transcriptions; the owner still edits and saves the existing form.
Year-only dates remain in supporting text. No local OCR engine or TeX compilation
was added to import.

The targeted Python suite passed 163 tests across import, profile persistence,
provider catalogs, native PDF contracts, TeX sources, master resumes, and tailoring.
Five Chromium import tests passed, including structured title/company/date filling,
owner edits, saving/reloading, discard, and stale responses. Svelte check, production
build, focused Ruff/mypy and diff whitespace checks passed. The two macOS compiler
isolation tests require execution outside the agent's outer sandbox so they can
create their own sandbox.

These tests use synthetic documents and mocked provider responses. Live provider
acceptance and comparative accuracy on representative user resumes remain
unverified. Hidden PDF annotation URLs, arbitrary layouts/custom macros, and local
scanned-page OCR remain areas for future corpus-driven evaluation.
