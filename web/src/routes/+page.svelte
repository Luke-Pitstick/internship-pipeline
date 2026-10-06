<script lang="ts">
  import { getContext, onMount, tick } from 'svelte';
  import { Api } from '#lib/api.ts';
  import { formatDate, type Job, type JobStatus, type JobsPage, type JobsQuery, type Evaluation } from '#lib/jobs.ts';

  const api = getContext<Api>('api');
  let inventory: Job[] = [];
  let truncated = $state(false);
  let query = $state<JobsQuery>({ page: 1, pageSize: 25, search: '', status: 'All', sort: 'postedAt', direction: 'desc' });
  let result = $state<JobsPage>({ rows: [], total: 0, page: 1, pages: 1 });
  let loading = $state(true);
  let error = $state('');
  let updating = $state(false);
  let searchDraft = $state('');
  let selected = $state<Job | null>(null);
  let detailOpen = $state(false);
  let detailHeading = $state<HTMLHeadingElement>();
  let selectedButton: HTMLButtonElement | undefined;
  let pageDraft = $state(1);
  let pageError = $state('');

  function load() {
    const text = query.search.toLowerCase();
    const rows = inventory.filter(job => (query.status === 'All' || job.status === query.status) && `${job.title} ${job.company} ${job.location ?? ''}`.toLowerCase().includes(text));
    rows.sort((a, b) => {
      const x = a[query.sort], y = b[query.sort];
      if (x === null || y === null) return x === y ? a.id.localeCompare(b.id) : x === null ? 1 : -1;
      const order = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y));
      return (query.direction === 'asc' ? order : -order) || a.id.localeCompare(b.id);
    });
    const pages = Math.max(1, Math.ceil(rows.length / query.pageSize));
    query.page = Math.min(query.page, pages);
    result = { rows: rows.slice((query.page - 1) * query.pageSize, query.page * query.pageSize), total: rows.length, page: query.page, pages };
    pageDraft = query.page;
  }
  function changeQuery() { query.page = 1; pageDraft = 1; pageError = ''; load(); }
  function navigate(page: number) { query.page = page; pageDraft = page; pageError = ''; load(); }
  function jump(event: SubmitEvent) {
    event.preventDefault();
    if (!Number.isInteger(pageDraft) || pageDraft < 1 || pageDraft > result.pages) { pageError = `Enter a page from 1 to ${result.pages}.`; return; }
    navigate(pageDraft);
  }
  async function select(job: Job, event: MouseEvent) {
    selectedButton = event.currentTarget as HTMLButtonElement;
    selected = job; detailOpen = true;
    await tick(); detailHeading?.focus();
  }
  async function closeDetail() { detailOpen = false; await tick(); if (selectedButton?.isConnected) selectedButton.focus(); else document.querySelector<HTMLButtonElement>('[data-job]')?.focus(); }
  async function status(value: JobStatus) {
    if (!selected || updating) return;
    const job = selected;
    updating = true; error = '';
    try {
      const result = await api.request<{applied_at: string | null}>(`/api/jobs/${job.id}/applied`, {status: value === 'Applied' ? 'applied' : 'not_applied'});
      const updated = { ...job, status: value, appliedAt: result.applied_at };
      inventory = inventory.map(item => item.id === job.id ? updated : item);
      if (selected?.id === job.id) selected = updated;
      load();
    } catch (reason) { error = (reason as Error).message; }
    finally { updating = false; }
  }
  async function evaluate() {
    if (!selected || updating) return;
    updating = true; error = '';
    try { await api.request(`/api/jobs/${selected.id}/evaluate`, {}); await refresh(); }
    catch (reason) { error = (reason as Error).message; }
    finally { updating = false; }
  }
  async function refresh() {
    try {
      const data = await api.request<{jobs: {id: string; title: string; company: string; locations: string[]; source_timestamp: string | null; first_seen: number; deadline: string | null; applied_at: string | null; description: string; application_url: string; resume: {download_path: string | null}; fit: number | null; eligible: boolean | null; evaluation: Evaluation}[]; scope: {raw_collected: number; limit: number}}>('/api/jobs');
      inventory = data.jobs.map(job => ({id: job.id, title: job.title, company: job.company, location: job.locations.join(', ') || null, postedAt: job.source_timestamp, firstObservedAt: new Date(job.first_seen * 1000).toISOString(), deadline: job.deadline, score: job.fit, evaluation: job.evaluation, eligibility: job.evaluation.state === 'error' ? 'Evaluation error' : job.evaluation.state !== 'complete' ? 'Pending' : job.eligible === true ? 'Eligible' : 'Needs review', status: job.applied_at ? 'Applied' : 'To review', appliedAt: job.applied_at, description: job.description, applicationUrl: job.application_url, resumeUrl: job.resume.download_path}));
      truncated = data.scope.raw_collected > data.scope.limit;
      load(); selected = inventory.find(job => job.id === selected?.id) ?? result.rows[0] ?? null;
    } catch (reason) { error = (reason as Error).message; }
    finally { loading = false; }
  }
  onMount(() => { refresh(); const interval = setInterval(() => { if (!updating) refresh(); }, 5000); return () => clearInterval(interval); });
</script>

<svelte:window onkeydown={(event) => { if (event.key === 'Escape' && detailOpen) closeDetail(); }} />
<section class="search-hero">
  <p class="eyebrow">YOUR INTERNSHIP SEARCH</p>
  <h1>Find your next chapter.</h1>
  <p class="intro">A clearer view of the opportunities ahead.</p>
  <form class="search-form" onsubmit={(event) => { event.preventDefault(); query.search = searchDraft; changeQuery(); }}>
    <label class="search-field"><span aria-hidden="true">⌕</span><span class="sr-only">Role, company, or location</span><input bind:value={searchDraft} placeholder="Role, company, or location" type="search" /></label>
    <button class="primary" type="submit">Search jobs <span aria-hidden="true">→</span></button>
  </form>
</section>
<section class="search-progress"><p>Showing stored opportunities. Jev assessments use your saved profile and tested connection. Configure discovery through operator settings. <a href="/settings/">View settings</a></p></section>
{#if truncated}<p role="status">This view contains up to 1,000 recent or applied jobs. Full server pagination is not yet available.</p>{/if}
<section class="jobs-toolbar" aria-label="Job filters and sorting">
  <div class="status-filters" aria-label="Application status">
    {#each ['All', 'To review', 'Applied'] as value}
      <button aria-pressed={query.status === value} class:chosen={query.status === value} onclick={() => { query.status = value as JobsQuery['status']; changeQuery(); }}>{value === 'All' ? 'All jobs' : value}</button>
    {/each}
  </div>
  <div class="sort-controls">
    <label>Sort by <select bind:value={query.sort} onchange={changeQuery} aria-label="Sort field">
      <option value="postedAt">Date posted</option><option value="firstObservedAt">First observed</option><option value="company">Company</option><option value="title">Role title</option><option value="location">Location</option><option value="deadline">Deadline</option><option value="score">Match score</option>
    </select></label>
    <button aria-label="Reverse sort direction" class="small-button" onclick={() => { query.direction = query.direction === 'desc' ? 'asc' : 'desc'; changeQuery(); }}>{query.direction === 'desc' ? '↓ Descending' : '↑ Ascending'}</button>
  </div>
</section>
<div class="results-heading"><h2>{result.total.toLocaleString()} opportunities</h2><span class="muted" role="status">{loading ? 'Loading jobs…' : `Page ${result.page} of ${result.pages}`}</span></div>
{#if error}<p role="alert" class="error">{error}</p>{/if}
<div class="jobs-workspace" class:has-selection={!!selected} class:detail-open={detailOpen}>
  <section class="jobs-list" aria-label="Job results" aria-busy={loading}>
    <div class="job-cards">
      {#each result.rows as job (job.id)}
        <button class="job-card" class:selected={selected?.id === job.id} aria-pressed={selected?.id === job.id} data-job={job.id} onclick={(event) => select(job, event)}>
          <span class="job-card-top"><span class="job-card-company">{job.company}</span><span class="score-pill">{job.score === null ? 'Unscored' : `${job.score} match`}</span></span>
          <strong class="job-title">{job.title}</strong>
          <span class="job-location">{job.location ?? 'Location not provided'}</span>
          <span class="job-dates"><span>Posted {formatDate(job.postedAt)}</span><span>First observed {formatDate(job.firstObservedAt)}</span></span>
          <span class="job-meta"><span class:review={job.eligibility === 'Needs review'} class:eligible={job.eligibility === 'Eligible'} class="eligibility">{job.eligibility}</span><span>{job.status}{job.appliedAt ? ` · ${formatDate(job.appliedAt)}` : ''}</span></span>
        </button>
      {:else}<div class="empty-state"><h3>{loading ? 'Loading opportunities…' : 'No opportunities yet'}</h3><p>Your stored jobs will appear here. If you already have jobs, try another filter. A fresh workspace starts empty.</p></div>{/each}
    </div>
    {#if result.total > 0}<div class="pagination">
      <div class="pagination-summary">{result.total ? `${(result.page - 1) * query.pageSize + 1}–${Math.min(result.page * query.pageSize, result.total)}` : '0'} of {result.total.toLocaleString()}<label>Rows <select aria-label="Rows per page" bind:value={query.pageSize} onchange={changeQuery}><option value={25}>25</option><option value={50}>50</option><option value={100}>100</option></select></label></div>
      <div class="page-buttons"><button class="small-button" onclick={() => navigate(result.page - 1)} disabled={result.page <= 1 || loading}>Previous</button><form onsubmit={jump} novalidate><label>Page <input aria-label="Page number" type="number" min="1" max={result.pages} bind:value={pageDraft} aria-invalid={!!pageError} aria-describedby={pageError ? 'page-error' : undefined} /></label><span> / {result.pages}</span><button class="small-button" type="submit" disabled={loading}>Go</button></form><button class="small-button" onclick={() => navigate(result.page + 1)} disabled={result.page >= result.pages || loading}>Next</button></div>
      {#if pageError}<p id="page-error" class="error" role="alert">{pageError}</p>{/if}
    </div>{/if}
  </section>
  {#if selected}<aside class="job-detail" aria-label="Selected job details">
      <button class="back-button" onclick={closeDetail}>← Back to results</button>
      <div class="detail-top"><h2 bind:this={detailHeading} tabindex="-1">{selected.title}</h2><span class="eligibility" class:review={selected.eligibility === 'Needs review'} class:eligible={selected.eligibility === 'Eligible'}>{selected.eligibility}</span></div>
      <p class="detail-company">{selected.company}</p><p class="muted">{selected.location ?? 'Location not provided'}</p>
      <div class="detail-actions"><button class="primary" disabled={updating} onclick={() => status(selected?.status === 'Applied' ? 'To review' : 'Applied')}>{selected.status === 'Applied' ? 'Undo applied' : 'Mark as applied'}</button></div>
      <p class="status-note" role="status">Application status: <strong>{selected.status}</strong>{selected.appliedAt ? ` · Applied ${formatDate(selected.appliedAt)}` : ''}. Mark applied only after you submit.</p>
      <dl class="detail-facts"><div><dt>Match score</dt><dd>{selected.score === null ? 'Not evaluated' : `${selected.score} / 100`}</dd></div><div><dt>Posted</dt><dd>{formatDate(selected.postedAt)}</dd></div><div><dt>First observed</dt><dd>{formatDate(selected.firstObservedAt)}</dd></div><div><dt>Deadline</dt><dd>{formatDate(selected.deadline)}</dd></div></dl>
      <div class="detail-copy"><h3>About this role</h3><p>{selected.description}</p><h3>Jev assessment</h3>
        <button class="small-button" disabled={updating || selected.status === 'Applied' || ['queued', 'evaluating'].includes(selected.evaluation?.state ?? '')} onclick={evaluate}>Evaluate job</button>
        <p role="status">{selected.evaluation?.state ?? 'pending'}{selected.evaluation?.error ? ` · ${selected.evaluation.error.replaceAll('_', ' ')}` : ''}</p>
        {#if selected.evaluation?.result}
          {@const assessment = selected.evaluation.result}
          <p><strong>{assessment.recommendation === 'review' ? 'Needs review' : 'Recommended'}</strong>. Fit describes alignment with the rubric, not your probability of an interview. Model rejections remain reviewable because automatic rejection has not passed validation.</p>
          <h3>Eligibility criteria</h3>
          {#each Object.entries(assessment.criteria) as [name, criterion]}
            <details><summary>{name.replaceAll('_', ' ')} · {criterion.outcome.replaceAll('_', ' ')}</summary>
              <p>Distribution confidence {Math.round(criterion.confidence * 100)}% · evidence selection {Math.round(criterion.evidence_probability * 100)}%. Confidence describes model certainty; it does not establish correctness.</p>
              <p>Evidence {criterion.evidence_id}: {assessment.evidence[criterion.evidence_id] ?? 'No supporting posting evidence selected.'}</p>
              <p>{Object.entries(criterion.probabilities).map(([outcome, probability]) => `${outcome.replaceAll('_', ' ')} ${Math.round(probability * 100)}%`).join(' · ')}</p>
            </details>
          {/each}
          <h3>Fit dimensions</h3>
          {#each Object.entries(assessment.dimensions) as [name, dimension]}<p>{name}: {dimension.normalized.toFixed(1)} / 100 · weight {Math.round(dimension.weight * 100)}% · confidence {Math.round(dimension.confidence * 100)}%</p>{/each}
          {#if assessment.uncertainty.length}<h3>Uncertainty</h3><p>{assessment.uncertainty.map(value => value.replaceAll('_', ' ')).join(', ')}</p>{/if}
          <details><summary>Confirmed candidate evidence</summary>
            {#each Object.entries(assessment.candidate_evidence) as [id, text]}<p>{id}: {text}</p>{:else}<p>No confirmed evidence was supplied.</p>{/each}
          </details>
          <details><summary>Assessment provenance and usage</summary><p>Profile revision {assessment.profile_revision}; connection revision {assessment.connection_revision}. Selected model {assessment.selected_model}; effective model {assessment.effective_model}.</p><p class="revision-text">Rubric {assessment.rubric_revision}. Job {assessment.job_revision}.</p><p>Input tokens {assessment.input_tokens}; output tokens {assessment.output_tokens}.</p></details>
        {:else}<p>{selected.evaluation?.state === 'stale' ? 'The saved assessment uses older inputs. The matcher will queue a fresh assessment when configuration is ready.' : 'No current assessment is available. Save your profile and successfully test Jev in Settings before evaluating.'}</p>{/if}
        {#if selected.evaluation?.attempts?.length}
          <details><summary>Evaluation attempts</summary>
            {#each selected.evaluation.attempts as attempt}<p>{new Date(attempt.started * 1000).toLocaleString()}: {attempt.status.replaceAll('_', ' ')}. Input tokens {attempt.input_tokens ?? 'unknown'}; output tokens {attempt.output_tokens ?? 'unknown'}.</p>{/each}
            <p>Retries are bounded to three provider attempts for these inputs. Failed attempts can have unknown billed usage.</p>
          </details>
        {/if}</div>
      <div class="detail-footer"><a href={selected.applicationUrl} target="_blank" rel="noopener noreferrer">Open original application ↗</a>{#if selected.resumeUrl} · <a href={selected.resumeUrl}>Download résumé</a>{/if}<br />Opening these links does not mark the job as applied.</div>
  </aside>{/if}
</div>

<style>details {margin: .8rem 0;} summary {cursor:pointer;} .revision-text {overflow-wrap:anywhere;}</style>
