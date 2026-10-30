import { ref, computed } from 'vue'
import { apiFetch } from '../services/apiClient'

export interface ScoreAnnotation {
  id: string
  job_id: string
  user_id?: string | null
  author_name: string
  measure_number: number
  staff_index: number
  annotation_type: 'comment' | 'fingering' | 'rehearsal' | 'technique'
  content: string
  color: string
  is_resolved: boolean
  created_at: string
  updated_at: string
}

export function useScoreAnnotations() {
  const annotations = ref<ScoreAnnotation[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const activeCategoryFilter = ref<'all' | 'comment' | 'fingering' | 'rehearsal' | 'technique'>('all')

  const filteredAnnotations = computed(() => {
    if (activeCategoryFilter.value === 'all') {
      return annotations.value
    }
    return annotations.value.filter(a => a.annotation_type === activeCategoryFilter.value)
  })

  const annotationsByMeasure = computed(() => {
    const map = new Map<number, ScoreAnnotation[]>()
    for (const ann of annotations.value) {
      const list = map.get(ann.measure_number) || []
      list.push(ann)
      map.set(ann.measure_number, list)
    }
    return map
  })

  const unresolvedCount = computed(() => {
    return annotations.value.filter(a => !a.is_resolved).length
  })

  const fetchAnnotations = async (jobId: string, shareToken?: string) => {
    if (!jobId) return
    isLoading.value = true
    error.value = null
    try {
      const query = shareToken ? `?share_token=${encodeURIComponent(shareToken)}` : ''
      const res = await apiFetch(`/api/jobs/${jobId}/annotations${query}`)
      if (res.ok) {
        annotations.value = await res.json()
      } else {
        const data = await res.json().catch(() => ({}))
        error.value = data.detail || 'Failed to fetch annotations'
      }
    } catch (err: any) {
      error.value = err.message || 'Network error fetching annotations'
    } finally {
      isLoading.value = false
    }
  }

  const addAnnotation = async (
    jobId: string,
    payload: {
      measure_number: number
      staff_index?: number
      annotation_type?: 'comment' | 'fingering' | 'rehearsal' | 'technique'
      content: string
      color?: string
    },
    shareToken?: string,
  ): Promise<ScoreAnnotation | null> => {
    try {
      const query = shareToken ? `?share_token=${encodeURIComponent(shareToken)}` : ''
      const res = await apiFetch(`/api/jobs/${jobId}/annotations${query}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          measure_number: payload.measure_number,
          staff_index: payload.staff_index || 0,
          annotation_type: payload.annotation_type || 'comment',
          content: payload.content,
          color: payload.color || '#6366f1',
        }),
      })

      if (res.ok) {
        const newAnn: ScoreAnnotation = await res.json()
        annotations.value = [...annotations.value, newAnn]
        return newAnn
      }
      return null
    } catch (err) {
      console.error('Failed to create annotation:', err)
      return null
    }
  }

  const updateAnnotation = async (
    jobId: string,
    annotationId: string,
    update: {
      content?: string
      annotation_type?: 'comment' | 'fingering' | 'rehearsal' | 'technique'
      color?: string
      is_resolved?: boolean
    },
  ): Promise<boolean> => {
    try {
      const res = await apiFetch(`/api/jobs/${jobId}/annotations/${annotationId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(update),
      })

      if (res.ok) {
        const updatedAnn: ScoreAnnotation = await res.json()
        annotations.value = annotations.value.map(a => (a.id === annotationId ? updatedAnn : a))
        return true
      }
      return false
    } catch (err) {
      console.error('Failed to update annotation:', err)
      return false
    }
  }

  const deleteAnnotation = async (jobId: string, annotationId: string): Promise<boolean> => {
    try {
      const res = await apiFetch(`/api/jobs/${jobId}/annotations/${annotationId}`, {
        method: 'DELETE',
      })

      if (res.ok) {
        annotations.value = annotations.value.filter(a => a.id !== annotationId)
        return true
      }
      return false
    } catch (err) {
      console.error('Failed to delete annotation:', err)
      return false
    }
  }

  return {
    annotations,
    filteredAnnotations,
    annotationsByMeasure,
    unresolvedCount,
    isLoading,
    error,
    activeCategoryFilter,
    fetchAnnotations,
    addAnnotation,
    updateAnnotation,
    deleteAnnotation,
  }
}
