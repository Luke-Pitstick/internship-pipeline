# Reset a forgotten password

If you installed Internship Pipeline, you can reset your sign-in details from a
terminal on the computer where you installed it. You don't need the old password.
If someone else installed the app, ask them to follow these steps on that computer.
There isn't an email reset link.

Resetting your sign-in details preserves your profile, saved jobs, résumés,
application tracking, and connections. It signs out all existing browser sessions.

## Installed with the installer

Keep Docker or Podman running. Open Terminal on macOS, or your terminal on Linux,
using the same computer account you used to install the app.

1. **Stop the app.** Run:

   ```sh
   internship-pipeline stop
   ```

   Also stop any workers you launched separately. The app will be unavailable until
   you start it again, but its saved data stays in place.

2. **Choose new sign-in details.** Run:

   ```sh
   internship-pipeline recover-owner
   ```

   At `Username to use:`, enter the username you want to use. You can keep your
   previous username or choose a new one if you forgot it. Enter a new password of
   **12–256 characters**, then enter it again to confirm. Nothing appears while
   you type the password; that's expected. The old password isn't required.
   Wait for the command to report success before continuing.
   If an entry is invalid or the passwords don't match, the command explains why
   and lets you try again. Press Ctrl+C to cancel without changing your sign-in details.

3. **Reopen the app and sign in.** Run:

   ```sh
   internship-pipeline start
   internship-pipeline open
   ```

   Sign in with the username and password you just chose. Save them in your
   password manager.

## If a command fails

- **`command not found`:** the installer normally puts the command at
  `~/.local/bin/internship-pipeline`. Use that full path in place of
  `internship-pipeline` in each command above. If you chose a different command
  directory during installation, use that location instead.
- **The app is still running:** run `stop` and stop any separately launched workers
  before trying `recover-owner` again. Don't run recovery inside the active app
  container.
- **A private interactive terminal is required:** type the command directly in your
  terminal so it can prompt for the new password. Don't pipe input into it or put
  your password in the command itself.
- **The installation can't be found:** use the computer account and installation
  directory you originally used. For a custom directory, put
  `--install-dir /absolute/path/to/installation` before each subcommand, for example
  `internship-pipeline --install-dir /absolute/path/to/installation recover-owner`.
  The default installation directory is `~/.local/share/internship-pipeline`.

If the reset fails, keep the existing installation and its data. Don't delete its
volume or reinstall to try to regain access.

## Installed directly with Docker Compose

Use the [Compose account recovery steps](deployment.md#account-recovery) from the
same project directory and with the same Compose files used to start the app.
They stop the app and run `recover-owner` in a temporary container using the
existing image and data volume. Then restart the app and sign in with your new
details.
