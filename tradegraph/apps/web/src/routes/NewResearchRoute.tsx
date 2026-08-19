import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { QueryForm } from '../components/QueryForm'
import { useCreateJob } from '../lib/queryClient'
import { COMPOSER_MODE_COPY, EXAMPLE_QUERIES } from '../lib/theme'
import type { ComposerMode } from '../lib/theme'

function isComposerMode(value: string | null): value is ComposerMode {
  return value !== null && value in COMPOSER_MODE_COPY
}

export function NewResearchRoute() {
  const [query, setQuery] = useState('')
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const createJob = useCreateJob()

  const modeParam = searchParams.get('mode')
  const mode: ComposerMode = isComposerMode(modeParam) ? modeParam : 'general'
  const copy = COMPOSER_MODE_COPY[mode]

  const handleSubmit = async (value: string) => {
    const job = await createJob.mutateAsync(value)
    navigate(`/research/${job.job_id}`)
  }

  return (
    <div className="mx-auto max-w-2xl px-8 py-12">
      <p className="text-[11px] font-medium uppercase tracking-wide text-accent">{copy.label}</p>
      <h1 className="mt-1 font-serif text-2xl text-ink-0">Describe the matter</h1>
      <p className="mt-2 text-sm text-ink-1">
        Every claim in the resulting report traces to a cited provision or judgment — or the
        system states plainly that the corpus doesn't cover it.
      </p>

      <div className="mt-8">
        <QueryForm
          value={query}
          onChange={setQuery}
          placeholder={copy.placeholder}
          onSubmit={handleSubmit}
          disabled={createJob.isPending}
        />
        {createJob.isError && (
          <p className="mt-3 text-sm text-rose-400">
            {createJob.error instanceof Error
              ? createJob.error.message
              : 'Failed to start research.'}
          </p>
        )}
      </div>

      <div className="mt-10">
        <h2 className="text-[11px] font-medium uppercase tracking-wide text-ink-2">
          Example matters
        </h2>
        <div className="mt-2.5 flex flex-col divide-y divide-hairline border-t border-hairline">
          {EXAMPLE_QUERIES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setQuery(example)}
              className="py-3 text-left text-sm text-ink-1 transition hover:text-ink-0"
            >
              {example}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
