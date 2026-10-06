# Internship Tracker Feature Wishlist

A running list of features to add to the internship tracker.

## 1. Settings that are easy to use

Create a polished settings menu inspired by Cursor and the ChatGPT app: clear navigation, logically grouped controls, short explanations, and a layout that makes common changes easy to find.

### Resume generation

- Turn automatic resume generation on or off.
- Accept only `.tex` files as resume templates for generation.
- For each resume generation, create a tailored version by editing only the `.tex` source. Keep the original template intact and store the modified source for that job.
- Do not compile or create a PDF automatically during resume generation.
- When the user requests a PDF, compile the modified `.tex` file for that resume and serve the resulting PDF to the user for viewing or download.
- If compilation fails, show a clear error and preserve the modified `.tex` file so it can be corrected and retried.
- Configure which jobs qualify for resume generation using the Jev filtering and scoring work currently in progress.
- Use Jev's comparison of the job description and required skills against the user's resume, skills, and profile to decide whether a job is a good match.
- Set resume generation rules based on Jev's match score, apply recommendation, and hard-filter results. Make it clear which rules control resume generation and which control the overall job search.

### General job filters

- View and edit all general job-search filters in one place.
- Easily change Jev's hard-filter criteria and job-match preferences.
- Clearly show the active filters and explain how they affect the jobs included in the tracker.

### Profile and other information

- Easily upload, replace, and edit the resume and profile information used for job matching and resume generation.
- Keep skills, experience, preferences, and other job-search information easy to review and update.
- Provide clear access to AI model settings, including Jev and the general LLM, as those integrations become available.
- Keep email alert and spreadsheet sync preferences accessible as those features become available.

### Settings experience

- Use a simple category sidebar and a focused content panel, taking visual and interaction cues from Cursor and the ChatGPT app.
- Group settings into Resume Generation, Job Filters, Profile, AI Models, and Notifications & Integrations.
- Use labeled toggles for on/off options and straightforward controls for filters and editable information.
- Show whether changes have been saved, and give clear feedback when a value is invalid.
- Make the menu comfortable to use with a keyboard and on smaller screens.

### Details to settle during implementation

- Which Jev scores, recommendations, and hard-filter results will be available as resume generation criteria?
- What default rules should apply when resume generation is first enabled?
- Should settings save automatically or through an explicit Save button?

## 2. Sort the jobs-to-apply list

Make the main list of jobs to apply to sortable so users can easily prioritize opportunities.

- Sort by the date the position was posted, with newest-first and oldest-first options.
- Sort by other available job details, such as company, role title, location, application deadline, and Jev match score.
- Make the selected sort field and direction clear, and make switching between them easy.
- Distinguish the position's posting date from the date it was added to the tracker.
- Keep jobs with missing values visible and place them after jobs with known values.

## 3. One-command installation and pipeline management

Let users start installation with a single curl command pointing to a hosted installer. The installer should handle the setup needed to launch the app, without requiring users to manually pull containers or assemble configuration.

### Installation

- Download the required code or container image, create the necessary configuration, and start the pipeline's containers.
- Ask only for information that is actually required, and guide users through any remaining setup in plain language.
- Wait until the app is ready, then display the URL users can open to access it.
- Install a reusable management command and show how to run it again after installation.
- Make rerunning the installer safe: recognize an existing installation and preserve its configuration and data.

### Container runtime support

- Use a supported container runtime already installed on the user's system instead of requiring one specific runtime.
- Detect the operating system, architecture, and available runtimes, and check that the selected runtime is running and supports what the pipeline needs.
- If multiple supported runtimes are available, offer a simple choice with a sensible default.
- If no supported runtime is installed, recommend the easiest supported option for that operating system and guide the user through installing and starting it.
- Keep the application containers portable across supported runtimes, with runtime-specific behavior handled by the installer and management tool.

### Start, stop, and pipeline information

- Let users rerun the management tool to start or stop the pipeline without repeating installation or manually issuing container commands.
- Show whether the pipeline is running, the health of its services, and the URL for accessing the app.
- Provide useful pipeline information, such as recent runs, current activity, and errors, when available.
- Make logs easy to access when users need to troubleshoot a problem.
- Preserve configuration and stored data when the pipeline is stopped and started again.

### Details to settle during implementation

- Which operating systems and container runtimes will be supported initially?
- What will the installer URL and installed management command be called?
- Which pipeline status details should the management tool display?
