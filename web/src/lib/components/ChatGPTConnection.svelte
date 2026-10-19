<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import type { Api } from '#lib/api.ts';
  import type { ModelConfig } from '#lib/model-connections.ts';

  let {config = $bindable(), revision, disabled = false, ondisconnect = () => {}} = $props<{
    config: ModelConfig; revision: number; disabled?: boolean; ondisconnect?: () => void;
  }>();
  interface Account { id: string; email: string; client_id: string; status: string; welcomed: boolean }
  const api = getContext<Api>('api');
  let accounts = $state<Account[]>([]);
  let models = $state<{slug: string; display_name: string}[]>([]);
  let local = $state(true);
  let busy = $state(false);
  let error = $state('');
  let message = $state('');
  let attempt = $state('');
  let pairingCode = $state('');
  let confirmDisconnect = $state(false);
  let welcomeAccount = $state<Account | null>(null);
  let welcomeDialog: HTMLDialogElement;
  let origin = $state('');
  let alive = true;
  let checking = false;
  let modelRequest = 0;
  const selected = $derived(accounts.find(account => account.id === config.chatgpt_account_id));
  const usage = 'https://chatgpt.com/settings/usage';

  async function load() {
    const result = await api.request<{accounts: Account[]; local: boolean}>('/api/chatgpt');
    if (!alive) return;
    accounts = result.accounts; local = result.local;
  }
  async function loadModels() {
    const request = ++modelRequest;
    models = [];
    const id = config.chatgpt_account_id;
    if (!id || accounts.find(account => account.id === id)?.status !== 'connected') return;
    try {
      const result = await api.request<{models: typeof models}>('/api/chatgpt/models', {account_id: id});
      if (alive && request === modelRequest && id === config.chatgpt_account_id && accounts.find(account => account.id === id)?.status === 'connected') {
        models = result.models;
        const account = accounts.find(account => account.id === id);
        if (account && !account.welcomed) welcomeAccount = account;
      }
    } catch (reason) { if (alive && request === modelRequest) error = (reason as Error).message; }
  }
  onMount(() => {
    origin = window.location.origin;
    void load().catch(reason => error = reason.message);
    return () => { alive = false; };
  });
  $effect(() => {
    // Bound drafts also change through parent reload/discard controls.
    const id = config.chatgpt_account_id;
    if (id && accounts.length) void loadModels();
    else models = [];
  });
  $effect(() => {
    if (welcomeAccount && welcomeDialog && !welcomeDialog.open) welcomeDialog.showModal();
  });
  $effect(() => {
    if (!attempt) return;
    const timer = window.setInterval(() => void checkConnection(), 2000);
    return () => window.clearInterval(timer);
  });
  async function checkConnection() {
    if (checking || !attempt) return;
    checking = true;
    const id = attempt;
    try {
      const result = await api.request<{status: string; account_id: string | null}>('/api/chatgpt/status', {attempt_id: id});
      if (!alive || attempt !== id) return;
      if (result.status === 'connected') {
        attempt = ''; pairingCode = '';
        await load();
        config = {...config, chatgpt_account_id: result.account_id, model: ''};
        message = 'ChatGPT connected. Choose a model, then save and test this connection.';
      } else if (['failed', 'expired', 'cancelled'].includes(result.status)) {
        attempt = ''; pairingCode = '';
        error = 'The connection did not finish. Continue with ChatGPT to try again.';
      }
    } catch (reason) { if (alive) error = (reason as Error).message; }
    finally { checking = false; }
  }
  async function connect(accountId: string | null) {
    busy = true; error = ''; message = '';
    // Open synchronously from the click so browser popup protection permits the sign-in tab.
    const popup = local ? window.open('about:blank', '_blank') : null;
    if (popup) popup.opener = null;
    try {
      const result = await api.request<{attempt_id: string; authorize_url: string | null; pairing_code: string | null}>('/api/chatgpt/start', {expected_revision: revision, account_id: accountId});
      attempt = result.attempt_id; pairingCode = result.pairing_code ?? '';
      if (result.authorize_url) {
        if (!popup) { await api.request('/api/chatgpt/cancel', {attempt_id: attempt}); attempt = ''; throw new Error('Allow a sign-in popup for this site, then try again.'); }
        popup.location.href = result.authorize_url;
        message = 'Complete sign-in in the OpenAI tab, then return here.';
      }
    } catch (reason) { popup?.close(); error = (reason as Error).message; }
    finally { busy = false; }
  }
  async function cancel() {
    try { await api.request('/api/chatgpt/cancel', {attempt_id: attempt}); attempt = ''; pairingCode = ''; }
    catch (reason) { error = (reason as Error).message; }
  }
  async function disconnect() {
    if (!selected) return;
    busy = true; error = ''; message = '';
    try {
      const result = await api.request<{message: string}>('/api/chatgpt/disconnect', {account_id: selected.id});
      message = result.message; confirmDisconnect = false;
      await load(); models = []; ondisconnect();
    } catch (reason) { error = (reason as Error).message; }
    finally { busy = false; }
  }
  async function welcome() {
    if (!welcomeAccount) return;
    try {
      await api.request('/api/chatgpt/welcome', {account_id: welcomeAccount.id});
      accounts = accounts.map(account => account.id === welcomeAccount?.id ? {...account, welcomed: true} : account);
      welcomeAccount = null; welcomeDialog.close();
    } catch (reason) { error = (reason as Error).message; }
  }
</script>

<div class="chatgpt-connection">
  <p>Use the AI allowance in your eligible ChatGPT plan for résumé generation. Usage shares your ChatGPT limits and doesn't give this app access to your ChatGPT conversations or memory.</p>
  {#if error}<p role="alert" class="connection-error">{error}</p>{/if}
  <p role="status">{message}</p>
  <fieldset disabled={disabled || busy}>
    {#if accounts.length}
      <label for="chatgpt-account">ChatGPT account</label>
      <select id="chatgpt-account" value={config.chatgpt_account_id ?? ''} onchange={(event) => {config = {...config, chatgpt_account_id: event.currentTarget.value || null, model: ''}; error = '';}}>
        <option value="">Choose an account</option>
        {#each accounts as account}<option value={account.id}>{account.email} · {account.client_id} · {account.status}</option>{/each}
      </select>
    {/if}
    {#if !attempt}
      <div class="actions"><button type="button" class="continue" onclick={() => connect(config.chatgpt_account_id ?? null)}>Continue with ChatGPT</button>
      {#if selected}<button type="button" onclick={() => connect(null)}>Connect another account</button>{/if}</div>
    {:else}
      {#if pairingCode}
        <div class="remote-steps">
          <p>Complete sign-in on this computer to connect your remote pipeline.</p>
          <ol>
            <li><a href="/api/chatgpt/helper" download>Download the ChatGPT connection helper</a>.</li>
            <li>Run it with Python 3.10 or later:<code>python3 pipeline-chatgpt-connect.py --origin {origin}</code></li>
            <li>Paste this one-time code when the terminal asks for it:<output aria-label="One-time pairing code">{pairingCode}</output></li>
          </ol>
          <p>The code expires in 10 minutes. The helper opens OpenAI sign-in and securely transfers the connection to this installation.</p>
        </div>
      {/if}
      <button type="button" onclick={cancel}>Cancel connection</button>
    {/if}
    {#if selected?.status === 'connected'}
      <p class="plan-status">Using ChatGPT plan · <a href={usage} target="_blank" rel="noreferrer">Manage usage</a></p>
      <label for="chatgpt-model">Model</label>
      <select id="chatgpt-model" required bind:value={config.model}>
        <option value="">Choose a model</option>
        {#each models as model}<option value={model.slug}>{model.display_name}</option>{/each}
      </select>
      <div class="actions"><button type="button" onclick={loadModels}>Refresh available models</button><button type="button" onclick={() => confirmDisconnect = true}>Disconnect ChatGPT</button></div>
      {#if confirmDisconnect}<div class="disconnect-confirm"><p>Disconnect {selected.email}? Generation using this account will stop.</p><button type="button" onclick={disconnect}>Confirm disconnect</button><button type="button" onclick={() => confirmDisconnect = false}>Keep connected</button></div>{/if}
    {:else if selected}<p>Reconnect this account to use its ChatGPT plan.</p>{/if}
    <p class="help">ChatGPT sets output and plan limits. Requests have a timeout and response-size limit; a maximum output-token setting is unavailable. <a href={usage} target="_blank" rel="noreferrer">Manage plan usage</a>.</p>
  </fieldset>
</div>

<dialog bind:this={welcomeDialog} oncancel={(event) => {event.preventDefault(); void welcome();}}>
  <h3>You're using your ChatGPT plan</h3>
  <p>Eligible AI requests in Internship Pipeline use your ChatGPT plan or credits. Review usage and set this app's limits in <a href={usage} target="_blank" rel="noreferrer">ChatGPT settings</a>.</p>
  <button type="button" onclick={welcome}>Got it</button>
</dialog>

<style>
  p {line-height:1.6} fieldset {border:0;padding:0;min-width:0} label {display:block;margin:1rem 0 .4rem;font-size:.85rem;font-weight:600}
  select {display:block;box-sizing:border-box;width:100%;min-width:0;padding:.7rem;border:1px solid var(--border);border-radius:var(--radius);font:inherit;background:transparent;color:inherit}
  .actions {display:flex;flex-wrap:wrap;gap:.6rem;margin:1rem 0} button {font:inherit;font-size:.85rem;padding:.65rem .85rem;border-radius:var(--radius);border:1px solid var(--border);background:transparent;color:inherit;cursor:pointer}
  .continue {background:var(--ink);color:var(--surface);border-radius:2rem} button:disabled {opacity:.5;cursor:default} a {color:var(--accent)}
  code,output {display:block;padding:.8rem;background:var(--surface-subtle);overflow-wrap:anywhere;white-space:pre-wrap;font-size:.8rem;margin:.5rem 0}
  .remote-steps {border-left:2px solid var(--accent);padding-left:1rem} ol {padding-left:1.25rem;line-height:1.7} .help {font-size:.85rem;color:var(--muted)} .connection-error {color:#a12822} .plan-status {font-weight:600}
  .disconnect-confirm {padding:1rem;background:var(--surface)} .disconnect-confirm button {margin-right:.6rem}
  dialog {max-width:28rem;width:calc(100% - 4rem);padding:1.5rem;border:1px solid var(--border);border-radius:var(--radius);color:var(--ink);background:var(--surface)} dialog::backdrop {background:#0006} dialog h3 {margin-top:0}
</style>
