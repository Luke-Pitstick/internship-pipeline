<script lang="ts">
  let { name }: { name: 'search' | 'external' | 'back' | 'ascending' | 'descending' } = $props();
</script>

<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  {#if name === 'search'}<circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4" />
  {:else if name === 'external'}<path d="M14 4h6v6M20 4 10 14M10 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5" />
  {:else if name === 'back'}<path d="m10 5-7 7 7 7M3 12h18" />
  {:else if name === 'ascending'}<path d="M12 20V4m-6 6 6-6 6 6" />
  {:else}<path d="M12 4v16m-6-6 6 6 6-6" />{/if}
</svg>
