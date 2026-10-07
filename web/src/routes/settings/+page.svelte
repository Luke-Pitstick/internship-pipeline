<script lang="ts">
  import { page } from '$app/state';
  import SettingsWorkspace from '#lib/components/SettingsWorkspace.svelte';
</script>
<svelte:head><title>Settings · Internship Pipeline</title></svelte:head>
{#if page.url.searchParams.has('setup')}<p class="intro">Changes are saved in your workspace. <a href="/setup/">Return to guided setup</a> to review them and continue.</p>{/if}
<SettingsWorkspace />
