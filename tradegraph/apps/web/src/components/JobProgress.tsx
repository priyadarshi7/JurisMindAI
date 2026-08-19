import { Check } from 'lucide-react'
import type { JobStatus } from '../types'
import { PIPELINE_STAGES, stageIndexFor, stageKeyFor } from '../lib/progressStages'

interface JobProgressProps {
  status: JobStatus
  progressLog: string[]
}

export function JobProgress({ status, progressLog }: JobProgressProps) {
  if (status === 'failed') {
    return (
      <div className="flex items-center gap-2 text-sm font-medium text-rose-400">
        <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
        Research failed
      </div>
    )
  }

  const latest = progressLog[progressLog.length - 1]
  const latestStageKey = latest ? stageKeyFor(latest) : null
  const currentStageIndex =
    latestStageKey !== null
      ? stageIndexFor(latestStageKey)
      : status === 'succeeded'
        ? PIPELINE_STAGES.length - 1
        : -1

  return (
    <div className="space-y-3">
      <ol className="flex items-stretch border border-hairline text-[12px]">
        {PIPELINE_STAGES.map((stage, index) => {
          const done = status === 'succeeded' || currentStageIndex > index
          const active = !done && currentStageIndex === index
          return (
            <li
              key={stage.key}
              className={`flex flex-1 items-center gap-1.5 border-r border-hairline px-3 py-2 last:border-r-0 ${
                active ? 'bg-surface-2' : ''
              }`}
            >
              <span
                className={`flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full text-[9px] ${
                  done
                    ? 'bg-emerald-500 text-surface-0'
                    : active
                      ? 'bg-accent text-surface-0'
                      : 'border border-hairline-strong text-ink-2'
                }`}
              >
                {done ? <Check className="h-2.5 w-2.5" aria-hidden="true" /> : index + 1}
              </span>
              <span
                className={`truncate font-medium tracking-tight ${
                  done || active ? 'text-ink-0' : 'text-ink-2'
                }`}
              >
                {stage.label}
              </span>
              {active && <span className="ml-auto h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent" />}
            </li>
          )
        })}
      </ol>

      {progressLog.length > 0 && (
        <div className="border border-hairline bg-surface-1 px-3 py-2.5" role="status" aria-live="polite">
          <p className="text-[13px] text-ink-0">{latest}</p>
          {progressLog.length > 1 && (
            <ul className="mt-1.5 space-y-0.5 border-t border-hairline pt-1.5">
              {progressLog
                .slice(0, -1)
                .slice(-4)
                .reverse()
                .map((entry, index) => (
                  <li key={index} className="text-[12px] text-ink-2">
                    {entry}
                  </li>
                ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
