import type { JobResponse, JobStatus, JobSummary } from './types'

const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8000'

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    throw new ApiError(`could not reach the API at ${API_BASE_URL} — is it running?`)
  }
  if (!response.ok) {
    const body = await response.text().catch(() => '')
    throw new ApiError(`${response.status} ${response.statusText}${body ? `: ${body}` : ''}`)
  }
  return (await response.json()) as T
}

export function createJob(query: string): Promise<JobResponse> {
  return request<JobResponse>('/jobs', {
    method: 'POST',
    body: JSON.stringify({ query }),
  })
}

export function getJob(jobId: string): Promise<JobResponse> {
  return request<JobResponse>(`/jobs/${jobId}`)
}

export async function deleteJob(jobId: string): Promise<void> {
  // A 204 response has no body — request<T>()'s unconditional response.json()
  // would throw on it, so this bypasses that helper rather than special-case
  // an empty-body path into it.
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/jobs/${jobId}`, { method: 'DELETE' })
  } catch {
    throw new ApiError(`could not reach the API at ${API_BASE_URL} — is it running?`)
  }
  if (!response.ok) {
    const body = await response.text().catch(() => '')
    throw new ApiError(`${response.status} ${response.statusText}${body ? `: ${body}` : ''}`)
  }
}

export function listJobs(params?: { limit?: number; offset?: number }): Promise<JobSummary[]> {
  const query = new URLSearchParams()
  if (params?.limit !== undefined) query.set('limit', String(params.limit))
  if (params?.offset !== undefined) query.set('offset', String(params.offset))
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return request<JobSummary[]>(`/jobs${suffix}`)
}

interface StreamJobHandlers {
  onStatus: (status: JobStatus) => void
  onProgress: (detail: string) => void
  onConnectionError: () => void
}

/**
 * Subscribes to a job's status transitions and per-stage progress over SSE.
 * Returns an unsubscribe function — always call it on cleanup, the
 * connection otherwise outlives the component.
 */
export function streamJobStatus(jobId: string, handlers: StreamJobHandlers): () => void {
  const source = new EventSource(`${API_BASE_URL}/jobs/${jobId}/stream`)

  source.addEventListener('status', (event) => {
    handlers.onStatus((event as MessageEvent<string>).data as JobStatus)
  })
  source.addEventListener('progress', (event) => {
    handlers.onProgress((event as MessageEvent<string>).data)
  })
  // Native EventSource connection failure (network drop, server restart) —
  // distinct from the server's own named "status"/"progress" SSE events.
  source.onerror = () => {
    handlers.onConnectionError()
  }

  return () => source.close()
}
