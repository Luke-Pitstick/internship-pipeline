# Internship Pipeline

Find internships, see how they match your experience, prepare tailored résumés, and
track your applications in one workspace that runs on your own machine.

## What it does

- Collects internship postings from LinkedIn, Indeed, and company career boards.
- Assesses eligibility and fit against your profile, with reasoning you can review.
- Imports your résumé and uses your confirmed experience to prepare tailored drafts.
- Keeps saved jobs, notes, and application status together.
- Optionally sends email alerts and syncs with Google Sheets.

You review the results and submit applications yourself.

## Requirements

- **macOS or Linux**, on an Intel/AMD 64-bit or ARM64 machine.
- **Python 3.12+** and **curl**.
- **Docker Desktop, Docker Engine, or Podman** to run the app.
- A browser and an internet connection.

For AI features, connect **Jev** for job matching and **OpenAI, Claude, or OpenRouter**
for résumé drafts. You can set up your account before connecting providers. Email
and Google Sheets are optional.

## Installation

Start Docker or Podman, then run:

```sh
curl -fsSL https://raw.githubusercontent.com/Luke-Pitstick/internship-pipeline/main/install.sh | sh
```

The installer starts the app and opens your browser so you can choose a username
and password. On macOS, it can open an installed Docker Desktop for you. If the
browser doesn't open, use the link printed in your terminal.

## Quick start

1. **Add your profile.** Import a PDF or DOCX résumé, or enter your experience manually.
2. **Choose your preferences.** Set the roles, locations, and requirements that matter to you.
3. **Connect your models.** Set up matching and résumé generation in the browser.
4. **Finish setup and review jobs.** Collection starts automatically. Review matches,
   prepare drafts, and mark jobs as applied after you submit them.

You can change your profile, sources, models, and integrations in Settings.

## Everyday commands

```sh
internship-pipeline open     # Open the app
internship-pipeline status   # Check whether it's running
internship-pipeline stop     # Stop the app
internship-pipeline start    # Start it again
internship-pipeline update --check  # Check for a compatible release
internship-pipeline update         # Install the latest compatible release
```

The installer prints the command's location if it isn't on your PATH. Your data
persists between restarts. Rerunning the installer keeps your existing installation;
it doesn't upgrade it. Use the explicit update command once it is available in
your installed release; see the [update guide](docs/cli-updates.md) for bootstrap
and recovery instructions.

## Forgot your password?

On the computer where you installed the app, open a terminal and run
`internship-pipeline stop`, then `internship-pipeline recover-owner`. Enter the
username you want to use and a new password when prompted. After the reset succeeds,
run `internship-pipeline start` and `internship-pipeline open`, then sign in with
those details. Your saved work stays in place.

If someone else installed the app, ask them to reset it for you.
See the [password reset guide](docs/password-recovery.md) for the full steps,
troubleshooting, and Docker Compose instructions.

## More information

- [Installation and troubleshooting](docs/t19-installer.md)
- [Backups and recovery](docs/t20-management.md#private-backup-and-recovery)
- [Privacy and data flow](docs/privacy.md)
- [Development and contributing](CONTRIBUTING.md)
- [Release notes](CHANGELOG.md) — changes and update requirements for v1.0.0.

## License

[MIT](LICENSE).
