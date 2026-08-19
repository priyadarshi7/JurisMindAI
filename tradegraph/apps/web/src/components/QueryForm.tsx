import type { FormEvent } from 'react'
import { ArrowUp } from 'lucide-react'

interface QueryFormProps {
  value: string
  onChange: (value: string) => void
  onSubmit: (query: string) => void
  disabled: boolean
  placeholder?: string
}

export function QueryForm({ value, onChange, onSubmit, disabled, placeholder }: QueryFormProps) {
  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    const trimmed = value.trim()
    if (!trimmed) return
    onSubmit(trimmed)
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <label htmlFor="query" className="sr-only">
        Describe the situation
      </label>
      <div className="rounded-sm border border-hairline bg-surface-1 focus-within:border-hairline-strong">
        <textarea
          id="query"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          rows={5}
          placeholder={placeholder ?? 'Describe the matter…'}
          className="w-full resize-none bg-transparent px-4 py-3.5 text-[15px] text-ink-0 outline-none placeholder:text-ink-2 disabled:opacity-50"
        />
        <div className="flex items-center justify-between border-t border-hairline px-4 py-2">
          <span className="text-[11px] text-ink-2">
            Grounded in the ingested corpus — no citation, no claim.
          </span>
          <button
            type="submit"
            disabled={disabled || !value.trim()}
            className="flex items-center gap-1.5 rounded-sm bg-accent px-3 py-1.5 text-[13px] font-medium text-surface-0 transition hover:bg-accent-muted disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-ink-2"
          >
            {disabled ? 'Researching…' : 'Research'}
            {!disabled && <ArrowUp className="h-3.5 w-3.5" aria-hidden="true" />}
          </button>
        </div>
      </div>
    </form>
  )
}
