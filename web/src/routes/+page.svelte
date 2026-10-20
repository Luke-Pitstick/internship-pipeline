<script lang="ts">
  import { getContext, onMount, tick } from 'svelte';
  import { beforeNavigate } from '$app/navigation';
  import JobAssessment from '#lib/components/JobAssessment.svelte';
  import TailoredResume from '#lib/components/TailoredResume.svelte';
  import Icon from '#lib/components/Icon.svelte';
  import SearchRun from '#lib/components/SearchRun.svelte';
  import { Api } from '#lib/api.ts';
  import { formatDate, type Job, type JobStatus, type JobsPage, type JobsQuery, type Evaluation } from '#lib/jobs.ts';

  const api = getContext<Api>('api');
  let notesDraft = $state('');
  let overrideDraft = $state('review');
  let reasonDraft = $state('');
  let requestSequence = 0;
  let query = $state<JobsQuery>({ page: 1, pageSize: 25, search: '', status: 'All', sort: 'postedAt', direction: 'desc' });
  let result = $state<JobsPage>({ rows: [], total: 0, page: 1, pages: 1 });
  let loading = $state(true);
  let error = $state('');
  let actionError = $state('');
  let feedback = $state('');
  const sections = ['Overview', 'Match', 'Résumé', 'Notes'] as const;
  type DetailSection = typeof sections[number];
  let detailSection = $state<DetailSection>('Overview');
  let detailPane = $state<HTMLElement>();
  const viewLabels: Record<string, string> = {All: 'All jobs', Recommendations: 'Recommended', Applied: 'Applied', 'Needs review': 'Needs review', Saved: 'Saved', Rejected: 'Dismissed'};
  const viewDescriptions: Record<string, string> = {All: 'Your collected internships, ready to sort.', Recommendations: 'Roles recommended by your assessment or personal decision.', 'Needs review': 'Unapplied roles that need a closer look, including unscored jobs.', Saved: 'Your shortlist, including jobs you have already applied to.', Applied: 'Applications you have explicitly marked as submitted.', Rejected: 'Jobs you dismissed or personally rejected. You can restore them.'};
  let updating = $state(false);
  let searchDraft = $state('');
  let selected = $state<Job | null>(null);
  const notesDirty = $derived(notesDraft !== (selected?.workspace?.notes ?? ''));
  let detailOpen = $state(false);
  let focusRestoredDetail = false;
  let detailHeading = $state<HTMLHeadingElement>();
  let selectedButton: HTMLButtonElement | undefined;
  let pageDraft = $state(1);
  let pageError = $state('');

  function writeUrl(push = false) {
    const params = new URLSearchParams({page: String(query.page), page_size: String(query.pageSize), search: query.search, view: query.status, sort: query.sort, direction: query.direction});
    if (detailOpen && selected) {params.set('selected', selected.id); if (detailSection !== 'Overview') params.set('section', detailSection);}
    const url = `/?${params}`;
    if (push) history.pushState(history.state, '', url);
    else history.replaceState(history.state, '', url);
  }
  function readUrl() {
    const params = new URLSearchParams(location.search);
    detailOpen = !!params.get('selected'); focusRestoredDetail = detailOpen;
    const section = params.get('section'); detailSection = sections.includes(section as DetailSection) ? section as DetailSection : 'Overview';
    const positive = (value: string | null, fallback: number) => Number.isInteger(Number(value)) && Number(value) > 0 ? Number(value) : fallback;
    query.page = positive(params.get('page'), 1); pageDraft = query.page;
    const size = positive(params.get('page_size'), 25); query.pageSize = [25,50,100].includes(size) ? size : 25;
    query.search = params.get('search')?.slice(0,200) ?? ''; searchDraft = query.search;
    const view = params.get('view') ?? 'All'; query.status = ['All','Recommendations','Needs review','Saved','Applied','Rejected'].includes(view) ? view as JobsQuery['status'] : 'All';
    const sort = params.get('sort') ?? 'postedAt'; query.sort = ['postedAt','firstObservedAt','company','title','location','deadline','score'].includes(sort) ? sort as JobsQuery['sort'] : 'postedAt';
    query.direction = params.get('direction') === 'asc' ? 'asc' : 'desc';
  }
  function changeQuery() { query.page = 1; pageDraft = 1; pageError = ''; writeUrl(); void refresh(); }
  function navigate(page: number) { query.page = page; pageDraft = page; pageError = ''; writeUrl(); void refresh(); }
  function jump(event: SubmitEvent) {
    event.preventDefault();
    if (!Number.isInteger(pageDraft) || pageDraft < 1 || pageDraft > result.pages) { pageError = `Enter a page from 1 to ${result.pages}.`; return; }
    navigate(pageDraft);
  }
  function canLeaveNotes() { return !notesDirty || confirm('Discard unsaved notes for this job?'); }
  beforeNavigate(({cancel, type}) => { if (notesDirty && (type === 'leave' || !canLeaveNotes())) cancel(); });
  function chooseSection(value: DetailSection) { detailSection = value; detailOpen = true; writeUrl(); }
  function sectionKey(event: KeyboardEvent, index: number) {
    const next = event.key === 'ArrowRight' ? (index + 1) % sections.length : event.key === 'ArrowLeft' ? (index + sections.length - 1) % sections.length : event.key === 'Home' ? 0 : event.key === 'End' ? sections.length - 1 : -1;
    if (next < 0) return; event.preventDefault(); chooseSection(sections[next]); document.getElementById(`job-tab-${next}`)?.focus();
  }
  async function select(job: Job, event: MouseEvent) {
    if (selected?.id !== job.id && !canLeaveNotes()) return;
    ++requestSequence; loading = false;
    selectedButton = event.currentTarget as HTMLButtonElement;
    if (selected?.id !== job.id) { notesDraft = job.workspace?.notes ?? ''; overrideDraft = job.workspace?.decision ?? 'review'; reasonDraft = ''; detailSection = 'Overview'; actionError = ''; feedback = ''; }
    selected = job; detailOpen = true; writeUrl(true);
    if (detailPane) detailPane.scrollTop = 0;
    await tick(); detailHeading?.focus();
    if (matchMedia('(max-width:760px), (max-height:500px) and (max-width:1000px)').matches) detailPane?.scrollIntoView({block: 'start'});
    void refresh();
  }
  async function closeDetail() { detailOpen = false; writeUrl(); await tick(); if (selectedButton?.isConnected) selectedButton.focus(); else document.querySelector<HTMLButtonElement>('[data-job]')?.focus(); }
  async function status(job: Job, value: JobStatus) {
    if (updating) return;
    updating = true; actionError = ''; feedback = '';
    try {
      const response = await api.request<{applied_at: string | null}>(`/api/jobs/${job.id}/applied`, {status: value === 'Applied' ? 'applied' : 'not_applied'});
      const updated = { ...job, status: value, appliedAt: response.applied_at };
      result.rows = result.rows.map(row => row.id === job.id ? updated : row);
      if (selected?.id === job.id) selected = updated;
      feedback = value === 'Applied' ? `Marked ${job.title} at ${job.company} as applied.` : `Application status reset for ${job.title} at ${job.company}.`;
      await refresh();
    } catch (reason) { actionError = (reason as Error).message; }
    finally { updating = false; }
  }
  async function evaluate() {
    if (!selected || updating) return;
    updating = true; actionError = ''; feedback = '';
    try { await api.request(`/api/jobs/${selected.id}/evaluate`, {}); await refresh(); }
    catch (reason) { actionError = (reason as Error).message; }
    finally { updating = false; }
  }
  function toggleDismissed() {
    if (!selected) return;
    const rejected = selected.workspace?.decision === 'rejected';
    const dismissed = selected.workspace?.dismissed || rejected;
    void workspace({dismissed: !dismissed, ...(dismissed && rejected ? {decision: null, reason: 'Restored from Dismissed by owner.'} : {})});
  }
  type StoredJob = {id: string; title: string; company: string; locations: string[]; source_timestamp: string | null; first_seen: number; deadline: string | null; applied_at: string | null; description: string; description_truncated?: boolean; application_url: string; fit: number | null; eligible: boolean | null; evaluation: Evaluation; workspace: Job['workspace']};
  function mapJob(job: StoredJob): Job {
    return {id: job.id, title: job.title, company: job.company, location: job.locations.join(', ') || null, postedAt: job.source_timestamp, firstObservedAt: new Date(job.first_seen * 1000).toISOString(), deadline: job.deadline, score: job.fit, evaluation: job.evaluation, workspace: job.workspace, eligibility: job.evaluation.state === 'error' ? 'Evaluation error' : job.evaluation.state !== 'complete' ? 'Pending' : job.eligible === true ? 'Eligible' : 'Needs review', status: job.applied_at ? 'Applied' : 'To review', appliedAt: job.applied_at, description: job.description, descriptionTruncated: job.description_truncated, applicationUrl: job.application_url, resumeUrl: null};
  }
  async function workspace(body: {saved?: boolean; dismissed?: boolean; notes?: string; decision?: string | null; reason?: string}) {
    if (!selected || updating) return;
    updating = true; actionError = ''; feedback = '';
    try {
      const id = selected.id;
      await api.request(`/api/jobs/${id}/workspace`, body);
      if (selected?.id === id) {
        if (body.notes !== undefined) selected = {...selected, workspace: {...selected.workspace!, notes: body.notes}};
        feedback = body.notes !== undefined ? 'Notes saved.' : body.saved !== undefined ? (body.saved ? 'Added to Saved.' : 'Removed from Saved.') : body.dismissed !== undefined ? (body.dismissed ? 'Moved to Dismissed.' : 'Job restored.') : 'Your decision was saved.';
      }
      await refresh();
    }
    catch (reason) { actionError = (reason as Error).message; }
    finally { updating = false; }
  }
  async function refresh(background = false) {
    const sequence = ++requestSequence;
    if (!background) loading = true;
    const params = new URLSearchParams({page: String(query.page), page_size: String(query.pageSize), search: query.search, view: query.status, sort: query.sort, direction: query.direction});
    const selectedId = detailOpen || notesDirty ? selected?.id ?? new URLSearchParams(location.search).get('selected') : null;
    if (selectedId) params.set('selected', selectedId);
    try {
      const data = await api.request<{jobs: StoredJob[]; selected: StoredJob | null; pagination: {total: number; page: number; pages: number}}>(`/api/jobs?${params}`);
      if (sequence !== requestSequence) return;
      error = '';
      result = {...data.pagination, rows: data.jobs.map(mapJob)};
      if (query.page !== result.page) pageDraft = result.page;
      query.page = result.page;
      const next = data.selected ? mapJob(data.selected) : !selectedId ? result.rows[0] ?? null : null;
      if (selected?.id !== next?.id) { notesDraft = next?.workspace?.notes ?? ''; overrideDraft = next?.workspace?.decision ?? 'review'; reasonDraft = ''; actionError = ''; feedback = ''; }
      selected = next;
      if (!next) detailOpen = false;
      writeUrl();
      if (focusRestoredDetail) {focusRestoredDetail = false;await tick();if (detailOpen) {detailHeading?.focus();if (matchMedia('(max-width:760px), (max-height:500px) and (max-width:1000px)').matches) detailPane?.scrollIntoView({block:'start'});}}
    } catch (reason) { if (sequence === requestSequence) error = (reason as Error).message; }
    finally { if (sequence === requestSequence) loading = false; }
  }
  onMount(() => {
    readUrl(); refresh();
    const restore = async () => {
      const id = new URLSearchParams(location.search).get('selected');
      if (notesDirty && id !== selected?.id && !canLeaveNotes()) { writeUrl(); return; }
      if (id !== selected?.id) { selected = null; notesDraft = ''; }
      readUrl(); await refresh();
      if (!detailOpen) {await tick();if (selectedButton?.isConnected) selectedButton.focus();else document.querySelector<HTMLButtonElement>('[data-job]')?.focus();}
    };
    window.addEventListener('popstate', restore);
    const interval = setInterval(() => { if (!document.hidden && !updating && !loading) void refresh(true); }, 5000);
    return () => {requestSequence++; clearInterval(interval); window.removeEventListener('popstate', restore);};
  });
</script>

<svelte:window onkeydown={(event) => { if (event.key === 'Escape' && detailOpen) closeDetail(); }} />
<section class="dashboard" class:showing-detail={detailOpen}>
  <div class="browse-controls">
    <header class="search-hero">
      <div><p class="eyebrow">YOUR WORKSPACE</p><h1>Jobs</h1><p class="intro">Review jobs, build a shortlist, and track applications.</p></div>
      <form class="search-form" role="search" onsubmit={(event) => { event.preventDefault(); query.search = searchDraft; changeQuery(); }}>
        <label class="search-field"><Icon name="search" /><span class="sr-only">Role, company, or location</span><input bind:value={searchDraft} placeholder="Search role, company, location…" type="search" /></label>
        <button class="primary" type="submit">Search jobs</button>
      </form>
    </header>
    <SearchRun compact />
    <nav class="status-filters" aria-label="Job views">
      {#each Object.entries(viewLabels) as [value, label]}
        <button aria-pressed={query.status === value} class:chosen={query.status === value} onclick={() => { query.status = value as JobsQuery['status']; changeQuery(); }}>{label}</button>
      {/each}
    </nav>
    <div class="results-toolbar">
      <div class="results-heading"><h2>{loading && !result.total ? 'Your opportunities' : `${result.total.toLocaleString()} opportunities`}</h2><span class="muted" role="status">{loading ? 'Loading jobs…' : `Page ${result.page} of ${result.pages}`}</span></div>
      <div class="sort-controls">
        <label><span class="sr-only">Sort by</span><select bind:value={query.sort} onchange={changeQuery} aria-label="Sort field">
          <option value="postedAt">Date posted</option><option value="firstObservedAt">Date found</option><option value="company">Company</option><option value="title">Role title</option><option value="location">Location</option><option value="deadline">Deadline</option><option value="score">Match score</option>
        </select></label>
        <button aria-label="Reverse sort direction" title={query.direction === 'desc' ? 'Descending — reverse sort' : 'Ascending — reverse sort'} class="small-button sort-direction" onclick={() => { query.direction = query.direction === 'desc' ? 'asc' : 'desc'; changeQuery(); }}><Icon name={query.direction === 'desc' ? 'descending' : 'ascending'} /><span>{query.direction === 'desc' ? 'Descending' : 'Ascending'}</span></button>
      </div>
    </div>
    <div class="view-context"><p>{query.search ? `Results for “${query.search}” · ${viewLabels[query.status]}` : viewDescriptions[query.status]}</p>{#if query.search || query.status !== 'All'}<button onclick={() => {query.search = ''; searchDraft = ''; query.status = 'All'; changeQuery();}}>Clear filters</button>{/if}</div>
  </div>
  {#if error}<div class="request-error" role="alert"><p>{error}</p><button class="small-button" onclick={() => refresh()}>Retry loading jobs</button></div>{/if}
  <div class="action-feedback" aria-live="polite">{#if updating}<p>Saving changes…</p>{:else if feedback}<p>{feedback}</p>{/if}</div>
  {#if actionError}<p class="action-error" role="alert">{actionError} Your change wasn’t saved. Try the action again.</p>{/if}
  <div class="jobs-workspace" class:has-selection={!!selected} class:detail-open={detailOpen}>
    <section class="jobs-list" aria-label="Job results" aria-busy={loading}>
      <div class="job-cards">
        {#each result.rows as job (job.id)}
          <article class="job-card" class:selected={selected?.id === job.id} aria-label={`${job.title} at ${job.company}`}>
          <button class="job-select" aria-pressed={selected?.id === job.id} data-job={job.id} onclick={(event) => select(job, event)}>
            <span class="job-card-top"><span class="job-card-company">{job.company}</span><span class="score-pill" class:strong-match={job.score !== null && job.score >= 75}>{job.score === null ? 'Unscored' : `${Math.round(job.score)} / 100 fit`}</span></span>
            <strong class="job-title">{job.title}</strong>
            <span class="job-location">{job.location ?? 'Location not provided'}</span>
            <span class="job-dates"><span>{job.postedAt ? `Posted ${formatDate(job.postedAt)}` : 'Posted date unknown'}</span>{#if job.deadline}<span>Closes {formatDate(job.deadline)}</span>{/if}</span>
            <span class="job-meta"><span class:review={job.eligibility === 'Needs review'} class:eligible={job.eligibility === 'Eligible'} class="eligibility">{job.eligibility}</span><span class="workspace-tags">{#if job.workspace?.saved}<span class="workspace-tag saved">Saved</span>{/if}{#if job.workspace?.dismissed || job.workspace?.decision === 'rejected'}<span class="workspace-tag">Dismissed</span>{/if}{#if job.status === 'Applied'}<span class="workspace-tag applied">Applied</span>{/if}</span></span>
          </button>
          <button class="small-button applied-action" class:is-applied={job.status === 'Applied'} aria-label={`${job.status === 'Applied' ? 'Undo applied' : 'Mark as applied'} to ${job.title} at ${job.company}`} disabled={updating} onclick={() => status(job, job.status === 'Applied' ? 'To review' : 'Applied')}>{job.status === 'Applied' ? 'Undo applied' : 'Mark as applied'}</button>
          </article>
        {:else}
          {#if loading}<div class="jobs-skeleton" role="status"><span class="sr-only">Loading opportunities…</span>{#each [1, 2, 3] as row}<div class="skeleton-row" aria-hidden="true"><span></span><span></span><span></span></div>{/each}</div>
          {:else if !error}<div class="empty-state">
            <Icon name="search" /><h3>{query.search || query.status !== 'All' ? 'No matching opportunities' : 'Your next opportunity starts here'}</h3>
            {#if query.search || query.status !== 'All'}<p>{query.status === 'Saved' && !query.search ? 'Save a job while reviewing it and it will appear in your shortlist.' : query.status === 'Applied' && !query.search ? 'After submitting an application, mark the job as applied to track it here.' : 'Try another view or search to see more of your collected jobs.'}</p><button class="secondary" onclick={() => {query.search = ''; searchDraft = ''; query.status = 'All'; changeQuery();}}>Show all jobs</button>
            {:else}<p>Jobs appear here as your sources collect them. Check your sources to start discovery.</p><a class="secondary" href="/settings/#Sources">Set up a source</a>{/if}
          </div>{/if}
        {/each}
      </div>
      {#if result.total > 0}<div class="pagination">
        <div class="pagination-summary">{(result.page - 1) * query.pageSize + 1}–{Math.min(result.page * query.pageSize, result.total)} of {result.total.toLocaleString()}<label>Rows <select aria-label="Rows per page" bind:value={query.pageSize} onchange={changeQuery}><option value={25}>25</option><option value={50}>50</option><option value={100}>100</option></select></label></div>
        <div class="page-buttons"><button class="small-button" onclick={() => navigate(result.page - 1)} disabled={result.page <= 1 || loading}>Previous</button><form onsubmit={jump} novalidate><label><span class="sr-only">Page</span><input aria-label="Page number" type="number" min="1" max={result.pages} bind:value={pageDraft} aria-invalid={!!pageError} aria-describedby={pageError ? 'page-error' : undefined} /></label><span> / {result.pages}</span><button class="small-button" type="submit" disabled={loading}>Go</button></form><button class="small-button" onclick={() => navigate(result.page + 1)} disabled={result.page >= result.pages || loading}>Next</button></div>
        {#if pageError}<p id="page-error" class="error" role="alert">{pageError}</p>{/if}
      </div>{/if}
    </section>
    {#if selected}<aside class="job-detail" bind:this={detailPane} aria-label="Selected job details">
      <button class="back-button" onclick={closeDetail}><Icon name="back" /> Back to results</button>
      {#if !loading && !result.rows.some(job => job.id === selected?.id)}<p class="outside-view">This job is outside your current results. You can keep reviewing it here.</p>{/if}
      <div class="detail-company-line"><p class="detail-company">{selected.company}</p><span class="score-pill" class:strong-match={selected.score !== null && selected.score >= 75}>{selected.score === null ? 'Unscored' : `${Math.round(selected.score)} / 100 fit`}</span></div>
      <div class="detail-top"><h2 bind:this={detailHeading} tabindex="-1">{selected.title}</h2></div>
      <p class="detail-location">{selected.location ?? 'Location not provided'}</p>
      <div class="detail-states"><span class="eligibility" class:review={selected.eligibility === 'Needs review'} class:eligible={selected.eligibility === 'Eligible'}>{selected.eligibility}</span>{#if selected.status === 'Applied'}<span class="workspace-tag applied">Applied {formatDate(selected.appliedAt)}</span>{/if}{#if selected.workspace?.dismissed || selected.workspace?.decision === 'rejected'}<span class="workspace-tag">Dismissed</span>{/if}</div>
      <div class="detail-actions"><a class="primary" href={selected.applicationUrl} target="_blank" rel="noopener noreferrer">Open original application <Icon name="external" /></a><button class="secondary applied-action" class:is-applied={selected.status === 'Applied'} disabled={updating} onclick={() => selected && status(selected, selected.status === 'Applied' ? 'To review' : 'Applied')}>{selected.status === 'Applied' ? 'Undo applied' : 'Mark as applied'}</button><button class="secondary" aria-pressed={selected.workspace?.saved ?? false} disabled={updating} onclick={() => workspace({saved: !selected?.workspace?.saved})}>{selected.workspace?.saved ? 'Unsave job' : 'Save job'}</button></div>
      <div class="tracking-actions"><button class="subtle" disabled={updating} onclick={toggleDismissed}>{selected.workspace?.dismissed || selected.workspace?.decision === 'rejected' ? 'Restore dismissed job' : 'Dismiss job'}</button></div>
      <p class="status-note">{selected.status === 'Applied' ? 'You marked this application as submitted.' : 'Apply on the company’s site, then mark it as applied here.'}</p>
      <div class="detail-tabs" role="tablist" aria-label="Job information">
        {#each sections as section, index}<button role="tab" id={`job-tab-${index}`} aria-selected={detailSection === section} aria-controls="job-tab-panel" tabindex={detailSection === section ? 0 : -1} onclick={() => chooseSection(section)} onkeydown={(event) => sectionKey(event, index)}>{section}{#if section === 'Notes' && notesDirty}<span aria-label="unsaved"> ·</span>{/if}</button>{/each}
      </div>
      <div id="job-tab-panel" class="detail-content" role="tabpanel" aria-labelledby={`job-tab-${sections.indexOf(detailSection)}`} tabindex="0">
        {#if detailSection === 'Overview'}
          <dl class="detail-facts"><div><dt>Posted by employer</dt><dd>{formatDate(selected.postedAt)}</dd></div><div><dt>Application deadline</dt><dd>{formatDate(selected.deadline)}</dd></div><div><dt>Found by us</dt><dd>{formatDate(selected.firstObservedAt)}</dd></div><div><dt>Application status</dt><dd>{selected.status}</dd></div></dl>
          <div class="detail-copy"><h3>About this role</h3><p class="posting-text">{selected.description || 'No description was provided. Open the original application to learn more about this role.'}</p>{#if selected.descriptionTruncated}<p>Posting text was shortened for this view. Open the original application to read the full posting.</p>{/if}</div>
        {:else if detailSection === 'Match'}<JobAssessment job={selected} {updating} onretry={evaluate} />
        {:else if detailSection === 'Résumé'}<TailoredResume jobId={selected.id} />
        {:else}
          <form class="job-notes" onsubmit={(event) => {event.preventDefault(); void workspace({notes: notesDraft});}}>
            <h3>Your notes</h3><p class="muted">Keep contacts, interview prep, and next steps with this job.</p><label>Private job notes <textarea bind:value={notesDraft} maxlength="10000" rows="6" placeholder="What stands out? What’s your next step?"></textarea></label><div class="notes-actions"><span>{notesDirty ? 'Unsaved changes' : 'Notes are up to date'}</span><button class="secondary" disabled={updating || !notesDirty}>Save notes</button></div>
          </form>
          <details class="decision-override"><summary>Record a decision override</summary><p>Your decision changes saved views and preserves the original Jev assessment.</p>
            <form onsubmit={(event) => {event.preventDefault(); void workspace({decision: overrideDraft === 'clear' ? null : overrideDraft, reason: reasonDraft});}}>
              <label>Your decision <select bind:value={overrideDraft}><option value="recommended">Recommended</option><option value="review">Needs review</option><option value="rejected">Rejected</option><option value="clear">Clear override</option></select></label>
              <label>Reason <textarea bind:value={reasonDraft} maxlength="2000" required rows="2"></textarea></label><button class="small-button" disabled={updating}>Record override</button>
            </form><p>Current override: {selected.workspace?.decision ?? 'None'}. {selected.workspace?.reason ?? ''}</p>
            {#each selected.workspace?.history ?? [] as item}<p>{new Date(item.at * 1000).toLocaleString()} · {item.decision ?? 'Cleared'} · {item.reason}</p>{/each}
          </details>
        {/if}
      </div>
    </aside>{/if}
  </div>
</section>

<style>
  .dashboard { --positive:#21654d; --positive-surface:#edf7f1; --caution:#806020; }
  .search-hero { display:flex; align-items:center; justify-content:space-between; gap:32px; margin-bottom:22px; }
  .eyebrow { color:var(--muted); font-size:11px; letter-spacing:.12em; font-weight:650; margin:0 0 8px; }
  h1 { font-size:32px; margin:0 0 8px; }
  .intro { margin:0; }
  .search-form { flex:1; max-width:540px; margin:0; gap:8px; }
  .search-field { padding-left:14px; }
  .search-field input { width:100%; }
  .search-form .primary { white-space:nowrap; min-height:46px; }
  .status-filters { display:flex; flex-wrap:wrap; gap:4px 24px; border-bottom:1px solid var(--border); }
  .status-filters button { padding:14px 0; min-height:48px; margin-bottom:-1px; font-weight:550; }
  .status-filters button:hover { color:var(--accent); }
  .status-filters .chosen { font-weight:700; }
  .results-toolbar { display:flex; justify-content:space-between; align-items:center; gap:16px; padding:20px 0 6px; }
  .results-heading { display:flex; align-items:baseline; gap:14px; margin:0; }
  .results-heading h2 { font-size:16px; }
  .sort-controls { margin:0; width:auto; font-size:12px; }
  .sort-controls select,.sort-direction { min-height:44px; }
  .view-context { display:flex; align-items:baseline; gap:12px; margin-bottom:18px; font-size:12px; color:var(--muted); }
  .view-context p { margin:0; }
  .view-context button { color:var(--accent); font-weight:600; flex-shrink:0; padding:4px; min-height:36px; }
  .jobs-workspace { grid-template-columns:minmax(0,.8fr) minmax(0,1.2fr); gap:0; border-top:1px solid var(--border); }
  .jobs-list { min-width:0; }
  .job-cards { max-height:calc(100dvh - 195px); overflow:auto; scrollbar-gutter:stable; }
  .job-card { padding:20px; gap:7px; border-left:3px solid transparent; }
  .job-card.selected { border-left-color:var(--accent); }
  .job-select { display:flex; flex-direction:column; gap:7px; width:100%; text-align:left; padding:0; }
  .applied-action,.detail-actions .secondary { color:var(--accent); border-color:var(--accent); min-height:44px; }
  .job-card .applied-action { align-self:flex-start; margin-top:8px; }
  .applied-action.is-applied { color:var(--positive); border-color:var(--positive); background:var(--positive-surface); }
  .job-card-top { justify-content:space-between; gap:12px; }
  .job-card-company { color:var(--muted); font-weight:600; overflow-wrap:anywhere; }
  .score-pill { font-size:12px; background:var(--surface-subtle); padding:4px 8px; border-radius:4px; }
  .score-pill.strong-match { background:var(--positive-surface); color:var(--positive); }
  .job-title { font-size:16px; line-height:1.4; }
  .job-location { font-size:13px; }
  .job-dates { font-size:12px; margin-top:3px; }
  .job-meta { gap:12px; flex-wrap:wrap; margin-top:7px; }
  .workspace-tags,.detail-states { display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
  .workspace-tag { font-size:11px; font-weight:600; color:var(--muted); background:var(--surface-subtle); border-radius:4px; padding:3px 7px; }
  .workspace-tag.saved { color:var(--accent); background:var(--selected); }
  .workspace-tag.applied { color:var(--positive); background:var(--positive-surface); }
  .job-detail { padding:24px 8px 24px 32px; max-height:calc(100dvh - 40px); top:20px; scrollbar-gutter:stable; scroll-padding-block:20px; }
  .outside-view { color:var(--muted); background:var(--surface-subtle); padding:12px; font-size:12px; margin-bottom:20px; }
  .detail-company-line { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:10px; }
  .detail-company { margin:0; font-size:14px; font-weight:600; color:var(--muted); }
  .detail-top h2 { font-size:26px; line-height:1.25; }
  .detail-location { color:var(--muted); margin:10px 0 12px; font-size:14px; }
  .detail-states { margin-bottom:22px; }
  .detail-actions { gap:8px; margin:0 0 10px; }
  .detail-actions .primary,.detail-actions .secondary { min-height:44px; }
  .tracking-actions { display:flex; gap:8px; flex-wrap:wrap; }
  .tracking-actions button { border-color:transparent; padding:8px 10px; min-height:44px; }
  .status-note { color:var(--muted); margin:8px 0 4px; font-size:12px; }
  .action-feedback { min-height:28px; color:var(--positive); font-size:12px; }
  .action-feedback p { margin:0; }
  .action-error { color:#a52637; font-size:13px; margin:8px 0 16px; }
  .detail-tabs { display:flex; gap:24px; border-bottom:1px solid var(--border); }
  .detail-tabs button { border-bottom:2px solid transparent; color:var(--muted); padding:12px 0; font-size:13px; min-height:46px; }
  .detail-tabs [aria-selected=true] { color:var(--accent); font-weight:650; border-bottom-color:var(--accent); }
  .detail-content { padding-top:20px; }
  .detail-facts { margin:0 0 24px; padding:0 0 20px; border-top:0; gap:18px; }
  .detail-facts dt { font-size:12px; }
  .detail-facts dd { font-size:13px; }
  .detail-copy { color:var(--ink); font-size:14px; line-height:1.7; }
  .detail-copy h3,.job-notes h3 { margin:0 0 12px; font-size:17px; }
  .posting-text { white-space:pre-line; }
  .job-notes { border:0; padding:0; margin:0 0 24px; }
  .job-notes label { font-size:13px; }
  textarea { font-size:14px; display:block; width:100%; max-width:100%; margin:8px 0 12px; resize:vertical; }
  .notes-actions { display:flex; gap:12px; align-items:center; justify-content:space-between; color:var(--muted); font-size:12px; }
  .decision-override { font-size:13px; color:var(--muted); border-top:1px solid var(--border); padding-top:8px; }
  .decision-override label { display:block; margin:12px 0; }
  .decision-override select { display:block; width:100%; margin-top:8px; }
  .pagination { padding:16px 16px 16px 0; border-top:1px solid var(--border); }
  .pagination-summary { gap:12px; align-items:center; }
  .pagination-summary label { display:flex; align-items:center; gap:8px; }
  .pagination-summary select { min-height:44px; }
  .page-buttons { flex-wrap:wrap; }
  .page-buttons button,.page-buttons input { min-height:44px; }
  .empty-state { border-top:0; padding:48px 24px; }
  .empty-state h3 { margin:16px 0 8px; }
  .back-button { display:none; }
  @media(max-width:1000px) { .search-hero { gap:24px; align-items:flex-start; flex-direction:column; } .search-form { width:100%; max-width:none; } .results-heading { flex-direction:column; gap:2px; } .job-detail { padding-left:24px; } }
  @media(max-width:760px), (max-height:500px) and (max-width:1000px) {
    .showing-detail .browse-controls { display:none; }
    .search-hero { gap:20px; margin-bottom:20px; }
    .eyebrow,.intro { display:none; }
    .search-hero { gap:12px; }
    .search-form { gap:8px; }
    .search-form .primary { padding:12px; }
    .search-field input { padding:12px 8px; }
    .status-filters { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:0 12px; }
    .status-filters button { font-size:12px; padding:10px 0; text-align:left; }
    .results-toolbar { align-items:flex-start; flex-wrap:wrap; gap:12px; padding-top:18px; }
    .results-heading { flex:1; min-width:130px; }
    .results-heading h2 { font-size:15px; }
    .sort-controls { flex-wrap:nowrap; gap:6px; }
    .sort-controls select { max-width:125px; font-size:12px; }
    .sort-direction { padding:8px; min-width:44px; }
    .sort-direction span { display:none; }
    .view-context { margin:8px 0 16px; flex-wrap:wrap; gap:4px; }
    .jobs-workspace { grid-template-columns:1fr; border-top:1px solid var(--border); }
    .jobs-workspace.detail-open { border:0; }
    .job-cards { max-height:none; overflow:visible; }
    .job-card { padding:20px 12px; }
    .detail-open .jobs-list { display:none; }
    .detail-open .job-detail { display:block; }
    .job-detail { display:none; position:static; border:0; padding:0; max-height:none; overflow:visible; }
    .detail-top h2 { font-size:26px; }
    .back-button { display:inline-flex; padding:0 0 16px; min-height:44px; margin-bottom:12px; }
    .detail-actions .primary { flex:1; }
    .detail-actions .secondary { min-width:85px; }
    .detail-tabs { justify-content:space-between; gap:12px; }
    .detail-tabs button { font-size:14px; }
    .detail-content { padding-top:24px; }
    .pagination { padding-right:0; }
    textarea { font-size:16px; }
  }
  @media(prefers-reduced-motion:reduce) { .job-card { transition:none; } }
</style>
