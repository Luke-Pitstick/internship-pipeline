<script lang="ts">
  import SearchRun from './SearchRun.svelte';
  import type { SavedSource } from '#lib/source-settings.ts';

  let {searches, ready, busy, allowRun, onedit, onaction}: {
    searches: SavedSource[]; ready: boolean; busy: boolean; allowRun: boolean;
    onedit: (search: SavedSource) => void;
    onaction: (search: SavedSource, action: 'pause' | 'delete') => void;
  } = $props();
  const providers = [
    {id:'jobspy', label:'Job site searches'},
    {id:'greenhouse', label:'Greenhouse boards'},
    {id:'lever', label:'Lever boards'},
    {id:'ashby', label:'Ashby boards'},
  ];
  const pageSize = 10;
  let query = $state('');
  let status = $state('all');
  let sort = $state('name');
  let expanded = $state(new Set<string>());
  let runDetails = $state(new Set<string>());
  let pages = $state<Record<string, number>>({});
  const filtering = $derived(!!query.trim() || status !== 'all');
  const matches = $derived.by(() => {
    const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    return searches.filter(search => {
      const text = [search.name, search.source, search.board, search.search_term, search.location, search.country, ...search.sites].join(' ').toLocaleLowerCase();
      return terms.every(term => text.includes(term)) && (status === 'all' || search.paused === (status === 'paused'));
    }).sort((a, b) => {
      if (sort === 'next') return (a.paused ? Infinity : a.next_run ?? Infinity) - (b.paused ? Infinity : b.next_run ?? Infinity) || a.name.localeCompare(b.name);
      if (sort === 'success') return (b.last_success ?? 0) - (a.last_success ?? 0) || a.name.localeCompare(b.name);
      return a.name.localeCompare(b.name);
    });
  });
  const groups = $derived(providers.map(provider => {
    const items = matches.filter(search => search.source === provider.id);
    const page = Math.min(pages[provider.id] ?? 0, Math.max(0, Math.ceil(items.length / pageSize) - 1));
    return {...provider, items, page, visible:items.slice(page * pageSize, (page + 1) * pageSize)};
  }).filter(group => group.items.length));
  const activeCount = $derived(searches.filter(search => !search.paused).length);

  function toggle(set: Set<string>, id: string) {
    const next = new Set(set);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  }
  function clearFilters() { query = ''; status = 'all'; pages = {}; }
  function filtersChanged() { pages = {}; expanded = new Set(providers.map(provider => provider.id)); }
  const date = (value: number | null) => value ? new Date(value * 1000).toLocaleString() : 'None';
</script>

<section class="source-library" aria-labelledby="saved-sources-heading" aria-busy={!ready}>
  <h3 id="saved-sources-heading">Saved sources</h3>
  <p class="field-help">{ready ? `${searches.length} sources · ${activeCount} active · ${searches.length - activeCount} paused` : 'Loading sources…'}</p>
  {#if searches.length}
    <div class="library-controls">
      <div class="search-control"><label for="find-source">Find a source</label><input id="find-source" type="search" placeholder="Name, company, role or location…" bind:value={query} oninput={filtersChanged} /></div>
      <div><label for="source-status">Status</label><select id="source-status" bind:value={status} onchange={filtersChanged}><option value="all">All sources</option><option value="active">Active</option><option value="paused">Paused</option></select></div>
      <div><label for="source-sort">Sort sources</label><select id="source-sort" bind:value={sort} onchange={() => pages = {}}><option value="name">Name A–Z</option><option value="next">Next scheduled run</option><option value="success">Last successful run</option></select></div>
    </div>
    {#if filtering}<p class="filter-result" role="status">{matches.length} of {searches.length} sources match <button type="button" class="subtle" onclick={clearFilters}>Clear filters</button></p>{/if}
    {#each groups as group (group.id)}
      {@const open = expanded.has(group.id)}
      <section class="source-group" aria-label={group.label}>
        <h4><button type="button" class="group-toggle" aria-expanded={open} aria-controls={`source-group-${group.id}`} onclick={() => expanded = toggle(expanded, group.id)}>
          <svg class:expanded={open} viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="m7 4 6 6-6 6" /></svg>
          <span>{group.label}</span><span class="group-count">{group.items.length}</span>
        </button></h4>
        {#if open}
          <div id={`source-group-${group.id}`}>
            {#each group.visible as source (source.id)}
              <section class="source-row" aria-label={source.name}>
                <div class="row-heading"><h5>{source.name}</h5><span class="source-status" class:paused={source.paused}>{source.paused ? 'Paused' : 'Active'}</span></div>
                <p class="source-description">{source.source === 'jobspy' ? [source.search_term, source.location || source.country].filter(Boolean).join(' · ') : source.board}</p>
                <div class="row-actions">
                  <button type="button" class="secondary" aria-label={`Edit ${source.name}`} disabled={busy} onclick={() => onedit(source)}>Edit</button>
                  <button type="button" class="secondary" aria-label={`${source.paused ? 'Resume' : 'Pause'} ${source.name}`} disabled={busy} onclick={() => onaction(source, 'pause')}>{source.paused ? 'Resume' : 'Pause'}</button>
                  <button type="button" class="subtle" aria-expanded={runDetails.has(source.id)} aria-controls={`source-details-${source.id}`} onclick={() => runDetails = toggle(runDetails, source.id)}>Details<span class="sr-only"> for {source.name}</span></button>
                </div>
                {#if runDetails.has(source.id)}
                  <div class="source-details" id={`source-details-${source.id}`}>
                    <p class="field-help">{source.source === 'jobspy' ? source.sites.join(', ') : source.source} · {source.daily_at ? `Daily at ${source.daily_at} (${source.timezone})` : 'Manual only'}</p>
                    <p class="field-help">Last success: {date(source.last_success)}<br />Next run: {source.paused ? 'Paused' : date(source.next_run)}</p>
                    {#if allowRun}<SearchRun searchId={source.id} disabled={source.paused || busy} />{/if}
                    <button type="button" class="subtle" disabled={busy} aria-label={`Delete ${source.name}`} onclick={() => {if (confirm(`Delete “${source.name}”? Its run history will be kept.`)) onaction(source, 'delete');}}>Delete source</button>
                  </div>
                {/if}
              </section>
            {/each}
            {#if group.items.length > pageSize}
              <nav class="pagination" aria-label={`${group.label} pages`}>
                <span>{group.page * pageSize + 1}–{Math.min((group.page + 1) * pageSize, group.items.length)} of {group.items.length}</span>
                <button type="button" class="secondary" disabled={group.page === 0} onclick={() => pages[group.id] = group.page - 1}>Previous</button>
                <button type="button" class="secondary" disabled={(group.page + 1) * pageSize >= group.items.length} onclick={() => pages[group.id] = group.page + 1}>Next</button>
              </nav>
            {/if}
          </div>
        {/if}
      </section>
    {/each}
    {#if !matches.length}<p class="empty-state">No sources match. Try a different name, company, role or location.</p>{/if}
  {:else if ready}<p class="empty-state">No saved sources yet. Add a job site search or company board below.</p>{/if}
</section>

<style>
  .source-library { margin-bottom: 24px; }
  h3 { margin: 0 0 8px; }
  .library-controls { display: flex; gap: 12px; flex-wrap: wrap; margin: 20px 0; }
  .library-controls > div { flex: 1; min-width: 150px; }
  .library-controls .search-control { flex: 2; min-width: 200px; }
  label { display: block; margin-bottom: 6px; font-weight: 600; font-size: 13px; }
  input, select { width: 100%; min-height: 44px; }
  .source-group { border-top: 1px solid var(--border); }
  .source-group:last-of-type { border-bottom: 1px solid var(--border); }
  h4 { margin: 0; }
  .group-toggle { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 56px; padding: 12px 0; text-align: left; font-weight: 600; }
  .group-toggle:hover { background: var(--surface-subtle); }
  svg { flex-shrink: 0; }
  svg.expanded { transform: rotate(90deg); }
  .group-count { margin-left: auto; color: var(--muted); font-weight: 400; font-variant-numeric: tabular-nums; }
  .source-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: 20px; row-gap: 4px; padding: 16px 0 16px 28px; border-top: 1px solid var(--border); }
  .row-heading { grid-column: 1; display: flex; align-items: baseline; gap: 12px; }
  h5 { margin: 0; font-size: 14px; overflow-wrap: anywhere; }
  .source-status { margin-left: auto; flex-shrink: 0; color: var(--accent); font-size: 12px; font-weight: 600; }
  .source-status.paused { color: var(--muted); }
  p { overflow-wrap: anywhere; }
  .source-description { grid-column: 1; margin: 0; color: var(--muted); font-size: 13px; }
  .row-actions { grid-column: 2; grid-row: 1 / span 2; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  button { min-height: 44px; }
  .source-details { grid-column: 1 / -1; padding-top: 16px; }
  .source-details p { margin: 0 0 12px; }
  .pagination { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 16px 0 16px 28px; }
  .pagination span { margin-right: auto; color: var(--muted); font-size: 13px; font-variant-numeric: tabular-nums; }
  .filter-result { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: var(--muted); font-size: 13px; }
  .empty-state { padding: 20px 0; color: var(--muted); }
  @media (max-width: 600px) {
    .library-controls .search-control { flex-basis: 100%; }
    .library-controls > div { min-width: 0; flex-basis: calc(50% - 6px); }
    input, select { font-size: 16px; }
    .source-row { display: block; }
    .source-description { margin: 4px 0 12px; }
    .source-row, .pagination { padding-left: 0; }
  }
</style>
