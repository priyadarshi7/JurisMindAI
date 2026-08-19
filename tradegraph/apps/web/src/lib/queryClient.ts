import { QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createJob, deleteJob, getJob, listJobs } from '../api'
import type { JobResponse } from '../types'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // A job's own SSE stream (see api.ts::streamJobStatus) is the source
      // of truth while it's running — this cache exists for the history
      // sidebar and for landing on a report page directly (shared link,
      // refresh), not for polling a running job itself.
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
})

export const jobKeys = {
  all: ['jobs'] as const,
  history: () => [...jobKeys.all, 'history'] as const,
  detail: (jobId: string) => [...jobKeys.all, 'detail', jobId] as const,
}

export function useJob(jobId: string | undefined) {
  return useQuery({
    queryKey: jobId ? jobKeys.detail(jobId) : jobKeys.detail('none'),
    queryFn: () => getJob(jobId as string),
    enabled: Boolean(jobId),
  })
}

export function useJobHistory(params?: { limit?: number }) {
  return useQuery({
    queryKey: jobKeys.history(),
    queryFn: () => listJobs(params),
    staleTime: 10_000,
  })
}

export function useCreateJob() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (query: string) => createJob(query),
    onSuccess: (job: JobResponse) => {
      client.setQueryData(jobKeys.detail(job.job_id), job)
      void client.invalidateQueries({ queryKey: jobKeys.history() })
    },
  })
}

export function useDeleteJob() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => deleteJob(jobId),
    onSuccess: (_data, jobId) => {
      client.removeQueries({ queryKey: jobKeys.detail(jobId) })
      void client.invalidateQueries({ queryKey: jobKeys.history() })
    },
  })
}
