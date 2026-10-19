# Use your ChatGPT plan

The open-source pipeline can connect an eligible ChatGPT account for general AI
work, including grounded résumé generation. Select **ChatGPT plan** under
**Settings → AI Models → General LLM**. API-key connections to OpenAI, Claude and
OpenRouter remain separate choices. Pipeline owner sign-in still protects the
installation.

## Connect an installation on this computer

1. Select **Continue with ChatGPT** and complete OpenAI's sign-in and plan-usage
   consent in the new tab. Allow this site's sign-in popup if your browser blocks
   it. Cancelling leaves the previous connection unchanged.
2. Return to AI settings. Confirm the first-use explanation, choose the saved
   account and an available model, then **Save General LLM**.
3. Select **Test General LLM**. This sends synthetic facts and consumes some of
   your ChatGPT allowance. Generation becomes available only after the current
   revision passes the structured-output test.

Direct sign-in works for a pipeline configured with an HTTP origin on
`localhost` or `127.0.0.1`, using its published port. The callback uses
`http://127.0.0.1:<port>/auth/callback`, including with a locally published Docker
port. The pipeline accepts both loopback hostnames for this configuration.
HTTPS and other origins use the local helper below.

## Connect a remote installation

OpenAI requires the open-source OAuth callback to reach `127.0.0.1` on the
computer running the browser. A remote server's loopback address cannot receive
that browser callback. The settings screen therefore provides a local helper:

1. Select **Continue with ChatGPT**, then download the provided Python helper.
2. Run the displayed command on the computer with your browser. It needs Python
   3.10 or later and no third-party packages. Use the exact pipeline origin shown
   in settings; remote installations require HTTPS.
3. Paste the one-time pairing code into the terminal prompt and approve OpenAI's
   sign-in and plan-usage consent. Pairing expires after ten minutes. The helper
   exchanges the code locally, transfers the session securely to your pipeline,
   and never writes credentials to a local file.
4. Return to settings to choose, save and test a model.

Each installation retains its own opaque host ID. The server owns later token
refreshes, serialized across its API and background workers. Transferred
sessions have the host-attribution/revocation limitations described in OpenAI's
[self-hosted VM guide](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms).

## Usage, disconnection and recovery

When this connection is selected, eligible requests consume the connected
account's ChatGPT plan allowance or credits. It is not a separate allowance for
each app. **Manage usage** opens ChatGPT settings to review usage, app access and
limits. A usage-limit failure stops that request; the pipeline does not switch
automatically to a paid API connection.

**Disconnect ChatGPT** stops new requests through that registration and attempts
to revoke its renewable session. If remote revocation cannot be confirmed, the
screen says so; disconnect the app in ChatGPT settings to end remote access.
Already transmitted inference may finish remotely. The saved account label and
registration mapping remain available for reconnecting; tokens are cleared.

Back up the database and private `model-credentials.key` together. Access,
refresh and ID tokens are encrypted with the same instance key as other provider
credentials, and are never returned by account/status APIs. Backup verification
checks these encrypted records too. Storage format 2 includes the new OAuth
records and model authentication settings; use an image declaring the same
storage format when restoring. No older-format conversion is provided.

## Current OpenAI preview contract

The integration uses OpenAI's public `/v1/models` and `/v1/responses` endpoints.
It discovers models for the selected account, requests strict JSON schema output,
and accepts generation only after a completed event and local validation of
confirmed fact IDs and permitted source edits. It does not receive ChatGPT
conversation history, memory or uploaded account files.

Plan requests use `store:false`, `stream:true`, array input and no unsupported
`max_output_tokens`. The pipeline bounds response bytes and request time, but
these are not a provider-enforced token or spending cap, especially for model
reasoning. Use ChatGPT's app limits to control plan/credit consumption. Per-run
token admission remains an estimate and is reconciled with reported actual usage.

Availability and account/workspace policy come from OpenAI. Commercial or
centrally hosted offerings may require separate access; this implementation
targets the open-source, owner-operated installation. See the
[OpenAI overview](https://developers.openai.com/siwc/token-sharing-open-source),
[registration contract](https://developers.openai.com/siwc/token-sharing-open-source/sign-in),
[inference contract](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
and [preview restrictions](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

Synthetic JWT, OAuth, HTTP/SSE and browser fixtures verify the implementation.
They do not prove that a particular real ChatGPT account has access or that a
chosen model supports this application's exact schema. Live acceptance requires
official user consent followed by an explicitly requested capability test.
