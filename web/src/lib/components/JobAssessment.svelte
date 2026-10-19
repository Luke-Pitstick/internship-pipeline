<script lang="ts">
  import type { Job } from '#lib/jobs.ts';
  let { job, updating, onretry }: {job: Job; updating: boolean; onretry: () => void} = $props();
</script>
<section class="assessment" aria-label="Jev assessment">
  <h3>Jev assessment</h3>
  {#if job.evaluation?.state === 'error'}<button class="small-button" disabled={updating || job.status === 'Applied'} onclick={onretry}>Retry evaluation</button>
  {:else if job.evaluation?.state !== 'complete'}<p>Match scoring runs automatically while you browse.</p>{/if}
  {#if job.evaluation?.retry_at && job.evaluation.error === 'evaluation_budget_exhausted'}<p>Scoring resumes automatically at {new Date(job.evaluation.retry_at*1000).toLocaleString()} when model capacity is available.</p>{/if}
  <p role="status">{job.evaluation?.state ?? 'pending'}{job.evaluation?.error ? ` · ${job.evaluation.error.replaceAll('_', ' ')}` : ''}</p>
  {#if job.evaluation?.result}
    {@const assessment = job.evaluation.result}
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
    {#if assessment.uncertainty.length}<h3>Gaps and uncertainty</h3><p>{assessment.uncertainty.map(value => value.replaceAll('_', ' ')).join(', ')}</p>{/if}
    <details><summary>Confirmed candidate evidence</summary>
      {#each Object.entries(assessment.candidate_evidence) as [id, text]}<p>{id}: {text}</p>{:else}<p>No confirmed evidence was supplied.</p>{/each}
    </details>
    <details><summary>Assessment provenance and usage</summary><p>Profile revision {assessment.profile_revision}; connection revision {assessment.connection_revision}. Selected model {assessment.selected_model}; effective model {assessment.effective_model}.</p><p class="revision-text">Rubric {assessment.rubric_revision}. Job {assessment.job_revision}.</p><p>Input tokens {assessment.input_tokens}; output tokens {assessment.output_tokens}.</p></details>
  {:else}<p>{job.evaluation?.state === 'stale' ? 'The saved assessment uses older inputs. The matcher will queue a fresh assessment when configuration is ready.' : 'No current assessment is available. Save your profile and successfully test Jev in Settings before evaluating.'}</p>{/if}
  {#if job.evaluation?.attempts?.length}
    <details><summary>Evaluation attempts</summary>
      {#each job.evaluation.attempts as attempt}<p>{new Date(attempt.started * 1000).toLocaleString()}: {attempt.status.replaceAll('_', ' ')}. Input tokens {attempt.input_tokens ?? 'unknown'}; output tokens {attempt.output_tokens ?? 'unknown'}.</p>{/each}
      <p>Retries are bounded to three provider attempts for these inputs. Failed attempts can have unknown billed usage.</p>
    </details>
  {/if}
</section>
<style>
  .assessment { color:var(--muted); font-size:14px; line-height:1.65; overflow-wrap:anywhere; }
  h3 { color:var(--ink); margin:24px 0 12px; font-size:16px; }
  h3:first-child { margin-top:0; }
  details { border-bottom:1px solid var(--border); padding:4px 0; }
  p { margin:12px 0; }
  .revision-text { overflow-wrap:anywhere; }
</style>
