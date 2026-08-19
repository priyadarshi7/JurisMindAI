// Maps the free-text `progress_detail` strings src/graph/pipeline.py emits
// (docs/16 Application: real per-stage progress over SSE) to a discrete
// pipeline stage for the stepper UI. Matched by prefix, not exact string —
// a wording tweak on the backend degrades to "stays on the same stage,
// shows the raw text as the sub-label" rather than breaking the stepper.

export interface PipelineStage {
  key: string
  label: string
}

export const PIPELINE_STAGES: PipelineStage[] = [
  { key: 'plan', label: 'Planning' },
  { key: 'decompose', label: 'Decomposing' },
  { key: 'research', label: 'Researching' },
  { key: 'synthesize', label: 'Synthesizing' },
  { key: 'review', label: 'Reviewing' },
  { key: 'validate', label: 'Validating citations' },
]

const STAGE_PREFIXES: [string, string][] = [
  ['Planning', 'plan'],
  ['Decomposing', 'decompose'],
  ['Researching sub-question', 'research'],
  ['Retrieving', 'research'],
  ['Extracting evidence', 'research'],
  ['Verifying evidence', 'research'],
  ['Checking for contradictions', 'research'],
  ['Synthesizing', 'synthesize'],
  ['Reviewing draft', 'review'],
  ['Validating citations', 'validate'],
]

export function stageKeyFor(progressDetail: string): string | null {
  const match = STAGE_PREFIXES.find(([prefix]) => progressDetail.startsWith(prefix))
  return match ? match[1] : null
}

export function stageIndexFor(stageKey: string): number {
  return PIPELINE_STAGES.findIndex((stage) => stage.key === stageKey)
}
