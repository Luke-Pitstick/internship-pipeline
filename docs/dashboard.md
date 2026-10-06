# Internship dashboard

Open https://luke-internship-desk.lukepitstick06.chatgpt.site and sign in with the owner ChatGPT account. The Sites frontend loads the Render API through authenticated server routes; the browser never receives its bearer credential.

The dashboard displays bounded, preliminary internship matches, descriptions, official application links, fit evidence, eligibility questions, first-observed and source timestamps, and available PDF downloads. PDFs stay on Render's persistent disk and stream through the authenticated Site. Earlier non-LaTeX drafts are labeled explicitly.

Use Mark as applied only after submitting an application yourself. The action records the first timestamp idempotently and stops further resume/delivery work for that job. Opening an application or downloading a resume never marks it applied.

Resume generation edits supported text spans in the original .tex and compiles PDFs with pdflatex. It uses gpt-5.6-sol through the saved Codex subscription. The master source and credentials are private Render files, not Git assets.

The results service is srv-db23e6rtqb8s73btl8d0. Its /healthz is public and contains no job or candidate data; all other API endpoints require DASHBOARD_API_TOKEN. The Site stores the same value as secret RENDER_API_TOKEN and uses RENDER_API_ORIGIN=https://internship-pipeline-api.onrender.com. Local previews use ignored .env values.

The existing Codex relay still requires the Mac to be available for Google Sheets updates. It is not ChatGPT Dot. Dashboard reads and Render collection continue independently of the Mac.
