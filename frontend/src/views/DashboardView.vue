<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import ScoreViewer from '../components/ScoreViewer.vue'
import ScoreCreationModal from '../components/ScoreCreationModal.vue'
import { userQuota, fetchUserQuota, isPlanModalOpen } from '../composables/useQuota'
import { showToast, dispatchDesktopNotification } from '../composables/useToast'
import { t, currentLocale } from '../i18n'
import { saveScoreOffline, getOfflineScore } from '../services/offlineCache'
import { apiFetch, clearAuthSession, resolveApiUrl } from '../services/apiClient'
import { useNativePlatform, mobileWorkspaceTab, activeProcessingCount } from '../composables/useNativePlatform'
import { useScoreScanner } from '../composables/useScoreScanner'


const router = useRouter()
const route = useRoute()
const completedJobIds = new Set<string>()
const { isMobile, triggerHapticLight } = useNativePlatform()
const {
  scannedPages,
  isCapturing: isScanning,
  scannerError: scanError,
  capturePhoto,
  removePage,
  rotatePage,
  clearPages,
  generateUploadFile,
} = useScoreScanner()
const mobileScanTitle = ref('')

interface JobResponse {
  id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  original_filename: string
  file_path?: string | null
  result_file_path: string | null
  error_message: string | null
  page_count?: number
  file_size_bytes?: number
  created_at?: string
  updated_at?: string
}

const selectedFile = ref<File | null>(null)
const isDragging = ref(false)
const currentJob = ref<JobResponse | null>(null)
const musicXmlContent = ref<string | null>(null)
const isLoadingScoreNotation = ref(false)
const isUploading = ref(false)
const errorMessage = ref<string | null>(null)
const quotaWarning = ref<string | null>(null)
const isSubmittingUpload = ref(false)

// Creation Wizard State
const isCreationModalOpen = ref(false)
const isSavingNewScore = ref(false)

// URL Import & Restricted Environment (DLP) State
const isUrlImportModalOpen = ref(false)
const urlInput = ref('')
const urlTitleInput = ref('')
const isImportingUrl = ref(false)
const urlImportError = ref<string | null>(null)
const isDlpHelpModalOpen = ref(false)

// Score Library Drawer & Workspace Grid State
const isLibraryOpen = ref(false)
const pastJobs = ref<JobResponse[]>([])
const isLoadingJobs = ref(false)
const librarySearchQuery = ref('')
const libraryStatusFilter = ref<'all' | 'completed' | 'processing' | 'failed'>('all')
const librarySortBy = ref<'newest' | 'title'>('newest')

const filteredJobs = computed(() => {
  const query = librarySearchQuery.value.trim().toLowerCase()
  const filter = libraryStatusFilter.value

  const list = pastJobs.value.filter((job) => {
    if (query && !job.original_filename.toLowerCase().includes(query)) {
      return false
    }
    if (filter === 'completed') return job.status === 'completed'
    if (filter === 'processing') return job.status === 'processing' || job.status === 'pending'
    if (filter === 'failed') return job.status === 'failed'
    return true
  })

  return [...list].sort((a, b) => {
    if (librarySortBy.value === 'title') {
      return a.original_filename.localeCompare(b.original_filename)
    }
    const timeA = a.created_at ? new Date(a.created_at).getTime() : 0
    const timeB = b.created_at ? new Date(b.created_at).getTime() : 0
    return timeB - timeA
  })
})

// Cleanup & Confirmation State
const showConfirmModal = ref(false)
const jobPendingDelete = ref<JobResponse | null>(null)
const isDeleting = ref(false)

// Background Transcription & Multitasking State (Track P1)
const activeTranscriptionJob = ref<JobResponse | null>(null)
const isUploadCardMinimized = ref(false)
const isUploadCardDismissed = ref(false)
const progressDetail = ref<string>('')
const isStudioModeActive = ref(false)

let pollTimer: number | null = null
let eventSource: EventSource | null = null
let backgroundJobsTimer: number | null = null

const processingJobsCount = computed(() => {
  const inLibrary = pastJobs.value.filter(j => j.status === 'processing' || j.status === 'pending').length
  if (isUploading.value) {
    if (activeTranscriptionJob.value) {
      const alreadyInLib = pastJobs.value.some(j => j.id === activeTranscriptionJob.value?.id)
      return alreadyInLib ? inLibrary : inLibrary + 1
    }
    return inLibrary + 1
  }
  return inLibrary
})

watch(
  processingJobsCount,
  (count) => {
    activeProcessingCount.value = count
  },
  { immediate: true }
)

const handleUnauthorized = () => {
  clearAuthSession()
  router.push({ name: 'Login' })
}

const fetchUserJobs = async () => {
  isLoadingJobs.value = true
  try {
    const res = await apiFetch('/api/jobs')
    if (res.status === 401) {
      handleUnauthorized()
      return
    }
    if (res.ok) {
      pastJobs.value = await res.json()
      if (pastJobs.value.some(j => j.status === 'processing' || j.status === 'pending')) {
        startBackgroundJobsPolling()
      }
    }
  } catch (err) {
    console.error('Failed to load past jobs:', err)
  } finally {
    isLoadingJobs.value = false
  }
}

const checkFileQuota = (file: File) => {
  if (userQuota.value) {
    const remainingBytes = userQuota.value.storage.limit_bytes - userQuota.value.storage.used_bytes
    if (file.size > remainingBytes) {
      const fileMb = (file.size / (1024 * 1024)).toFixed(1)
      const remainingMb = Math.max(0, remainingBytes / (1024 * 1024)).toFixed(1)
      quotaWarning.value = `This file (${fileMb} MB) exceeds your remaining storage (${remainingMb} MB available on ${userQuota.value.tier_name}). Upgrade your plan to expand storage.`
    } else {
      quotaWarning.value = null
    }
  }
}

const ALLOWED_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.bmp']

const validateAndSelectFile = (file: File): boolean => {
  const ext = '.' + (file.name.split('.').pop() || '').toLowerCase()
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    const msg = `Unsupported file type "${ext}". NoteSight supports PDF, PNG, JPG, TIFF, and BMP.`
    errorMessage.value = msg
    showToast({
      title: 'Unsupported File Type',
      message: msg,
      type: 'error',
      duration: 6000,
    })
    return false
  }
  selectedFile.value = file
  errorMessage.value = null
  checkFileQuota(file)
  return true
}

const handleFileSelect = (event: Event) => {
  const target = event.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    validateAndSelectFile(target.files[0])
  }
}

const handleDrop = (event: DragEvent) => {
  isDragging.value = false
  if (event.dataTransfer?.files && event.dataTransfer.files.length > 0) {
    validateAndSelectFile(event.dataTransfer.files[0])
  }
}

const clearSelectedFile = () => {
  selectedFile.value = null
  quotaWarning.value = null
}

const handleJobCompleted = async (jobId: string, finalJob: JobResponse) => {
  if (completedJobIds.has(jobId)) {
    return
  }
  completedJobIds.add(jobId)
  stopPolling()
  isUploading.value = false
  const finished: JobResponse = {
    ...(activeTranscriptionJob.value || {}),
    ...finalJob,
    id: jobId,
    status: 'completed',
  }
  activeTranscriptionJob.value = null
  progressDetail.value = ''
  await fetchUserJobs()
  await fetchUserQuota()

  dispatchDesktopNotification('NoteSight: Transcription Complete', {
    body: `"${finished.original_filename}" transcription is ready in your library.`
  })

  // If user is currently NOT viewing another score:
  if (!currentJob.value || !musicXmlContent.value) {
    musicXmlContent.value = null
    currentJob.value = finished
    await fetchMusicXml(jobId)
    showToast({
      title: 'Transcription Complete',
      message: `"${finished.original_filename}" is now open in the studio.`,
      type: 'success',
      duration: 6000,
    })
  } else {
    // User is active in another score or composing from scratch!
    showToast({
      title: 'Transcription Complete',
      message: `"${finished.original_filename}" is ready in your Score Library.`,
      type: 'success',
      actionLabel: 'Open Score',
      duration: 12000,
      onAction: async () => {
        await loadJobIntoViewer(finished)
      }
    })
  }
}

const handleJobFailed = async (_jobId: string, message: string) => {
  stopPolling()
  isUploading.value = false
  activeTranscriptionJob.value = null
  progressDetail.value = ''
  const failReason = message || 'Score recognition failed.'
  errorMessage.value = failReason
  showToast({
    title: 'Transcription Failed',
    message: failReason,
    type: 'error',
    duration: 8000,
  })
  await fetchUserJobs()
}

const startUpload = async () => {
  if (!selectedFile.value || isSubmittingUpload.value) return
  isSubmittingUpload.value = true
  isUploading.value = true
  isUploadCardMinimized.value = false
  isUploadCardDismissed.value = false
  errorMessage.value = null
  activeTranscriptionJob.value = null
  progressDetail.value = 'Uploading file to server...'
  mobileWorkspaceTab.value = 'library'

  if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission().catch(() => {})
  }

  const formData = new FormData()
  formData.append('file', selectedFile.value)

  try {
    const response = await apiFetch('/api/upload', {
      method: 'POST',
      body: formData,
    })

    if (response.status === 401) {
      handleUnauthorized()
      return
    }

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}))
      throw new Error(errData.detail || 'Upload failed')
    }

    const jobData: JobResponse = await response.json()
    activeTranscriptionJob.value = jobData
    selectedFile.value = null
    startPolling(jobData.id)
    startBackgroundJobsPolling()
    await fetchUserJobs()
    await fetchUserQuota()
  } catch (err: any) {
    errorMessage.value = err.message || 'An error occurred during upload'
    isUploading.value = false
    activeTranscriptionJob.value = null
    progressDetail.value = ''
  } finally {
    isSubmittingUpload.value = false
  }
}

const handleSubmitScannedPages = async () => {
  if (scannedPages.value.length === 0) return
  triggerHapticLight()
  const file = await generateUploadFile(mobileScanTitle.value)
  if (!file) return
  selectedFile.value = file
  clearPages()
  mobileScanTitle.value = ''
  mobileWorkspaceTab.value = 'library'
  await startUpload()
}

const handleUrlImport = async () => {
  const url = urlInput.value.trim()
  if (!url) {
    urlImportError.value = t('dashboard.importUrlPlaceholder')
    return
  }

  isImportingUrl.value = true
  urlImportError.value = null

  try {
    const response = await apiFetch('/api/scores/import-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url,
        title: urlTitleInput.value.trim() || undefined,
      }),
    })

    if (response.status === 401) {
      handleUnauthorized()
      return
    }

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}))
      throw new Error(errData.detail || 'Failed to import score from URL')
    }

    const jobData: JobResponse = await response.json()
    isUrlImportModalOpen.value = false
    urlInput.value = ''
    urlTitleInput.value = ''
    isUploading.value = true
    isUploadCardMinimized.value = false
    isUploadCardDismissed.value = false
    activeTranscriptionJob.value = jobData
    mobileWorkspaceTab.value = 'library'
    startPolling(jobData.id)
    await fetchUserJobs()
    await fetchUserQuota()
  } catch (err: any) {
    urlImportError.value = err.message || 'Failed to download and import score from URL'
  } finally {
    isImportingUrl.value = false
  }
}

const handleGlobalPaste = (event: ClipboardEvent) => {
  const target = event.target as HTMLElement | null
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
    return
  }

  if (!event.clipboardData || !event.clipboardData.items) {
    return
  }

  for (let i = 0; i < event.clipboardData.items.length; i++) {
    const item = event.clipboardData.items[i]
    if (item.type.indexOf('image') !== -1) {
      const blob = item.getAsFile()
      if (blob) {
        event.preventDefault()
        const now = new Date()
        const timestamp = now.toISOString().replace(/[-:T.]/g, '').slice(0, 14)
        const ext = item.type === 'image/jpeg' ? '.jpg' : '.png'
        const pastedFile = new File([blob], `pasted_score_${timestamp}${ext}`, { type: item.type })
        
        const success = validateAndSelectFile(pastedFile)
        if (success) {
          showToast({
            title: t('dashboard.scorePastedSuccess'),
            message: pastedFile.name,
            type: 'info',
            duration: 4000,
          })
        }
        return
      }
    }
  }
}

const MAX_POLL_COUNT = 300 // 15-minute watchdog timeout (matching 900s backend limit)

const startPolling = async (jobId: string) => {
  stopPolling()
  let pollAttempts = 0
  const token = localStorage.getItem('token')

  const startHttpFallbackPolling = () => {
    if (pollTimer !== null) return
    pollTimer = window.setInterval(async () => {
      pollAttempts += 1
      if (pollAttempts > MAX_POLL_COUNT) {
        stopPolling()
        isUploading.value = false
        activeTranscriptionJob.value = null
        progressDetail.value = ''
        errorMessage.value = 'Processing timed out after 15 minutes. Please check your score library for updates.'
        showToast({
          title: 'Processing Timeout',
          message: 'Transcription is taking longer than expected. Check your Score Library shortly.',
          type: 'warning',
        })
        return
      }

      try {
        const response = await apiFetch(`/api/jobs/${jobId}`)
        if (response.status === 401) {
          stopPolling()
          handleUnauthorized()
          return
        }
        if (!response.ok) return

        const job: JobResponse = await response.json()
        if (activeTranscriptionJob.value) {
          activeTranscriptionJob.value = { ...activeTranscriptionJob.value, ...job }
        }

        const matchIdx = pastJobs.value.findIndex(j => j.id === jobId)
        if (matchIdx !== -1) {
          pastJobs.value[matchIdx] = { ...pastJobs.value[matchIdx], ...job }
        }

        if (job.status === 'completed') {
          await handleJobCompleted(jobId, job)
        } else if (job.status === 'failed') {
          await handleJobFailed(jobId, job.error_message || '')
        }
      } catch (err) {
        console.error('Polling error:', err)
      }
    }, 3000)
  }

  // 1. Primary real-time transport: Server-Sent Events (SSE)
  if (typeof window !== 'undefined' && 'EventSource' in window && token) {
    try {
      let queryToken = token
      try {
        const ticketRes = await apiFetch('/api/auth/stream-ticket', {
          method: 'POST',
        })
        if (ticketRes.ok) {
          const ticketData = await ticketRes.json()
          if (ticketData?.ticket) {
            queryToken = ticketData.ticket
          }
        }
      } catch (ticketErr) {
        console.warn('Failed to acquire stream ticket, falling back to access token:', ticketErr)
      }

      eventSource = new EventSource(resolveApiUrl(`/api/jobs/${jobId}/stream?token=${encodeURIComponent(queryToken)}`))

      eventSource.onmessage = async (event) => {
        try {
          const payload = JSON.parse(event.data)
          if (!payload || !payload.status) return

          if (payload.page !== undefined && payload.total_pages) {
            progressDetail.value = payload.page > 0
              ? `Recognizing page ${payload.page} of ${payload.total_pages}...`
              : `Preparing ${payload.total_pages} page${payload.total_pages > 1 ? 's' : ''}...`
          }

          if (activeTranscriptionJob.value) {
            activeTranscriptionJob.value = { ...activeTranscriptionJob.value, ...payload }
          }

          // Update matching entry in pastJobs in real-time
          const matchIdx = pastJobs.value.findIndex(j => j.id === jobId)
          if (matchIdx !== -1) {
            pastJobs.value[matchIdx] = { ...pastJobs.value[matchIdx], ...payload }
          }

          if (payload.status === 'completed') {
            await handleJobCompleted(jobId, payload)
          } else if (payload.status === 'failed') {
            await handleJobFailed(jobId, payload.error_message)
          }
        } catch (err) {
          console.warn('Error handling SSE message:', err)
        }
      }

      eventSource.onerror = () => {
        if (eventSource) {
          eventSource.close()
          eventSource = null
        }
        // Fallback to polling on disconnect or stream error
        startHttpFallbackPolling()
      }
    } catch (e) {
      console.warn('Could not initialize EventSource stream:', e)
      startHttpFallbackPolling()
    }
  } else {
    startHttpFallbackPolling()
  }
}

const fetchMusicXml = async (jobId: string) => {
  isLoadingScoreNotation.value = true
  errorMessage.value = null
  try {
    try {
      const response = await apiFetch(`/api/jobs/${jobId}/download`)
      if (response.status === 401) {
        handleUnauthorized()
        return
      }
      if (response.ok) {
        musicXmlContent.value = await response.text()
        errorMessage.value = null
        // Persist in local offline cache for mobile rehearsals
        saveScoreOffline({
          id: jobId,
          title: currentJob.value?.original_filename || 'Score',
          xml: musicXmlContent.value,
        }).catch(() => {})
        return
      } else {
        const errData = await response.json().catch(() => ({}))
        if (errData?.detail) {
          console.warn(`Download failed (${response.status}):`, errData.detail)
        }
      }
    } catch (err) {
      console.warn('Network fetch failed, attempting offline cache recovery:', err)
    }

    // Fallback to offline cache
    try {
      const cached = await getOfflineScore(jobId)
      if (cached) {
        musicXmlContent.value = cached.xml
        errorMessage.value = null
        showToast({
          title: 'Offline Rehearsal Mode',
          message: 'Loaded score from local offline cache.',
          type: 'info',
          duration: 5000,
        })
        return
      }
    } catch {
      // Ignore cache lookup failure
    }

    musicXmlContent.value = null
    errorMessage.value = 'Unable to retrieve sheet music notation.'
  } finally {
    isLoadingScoreNotation.value = false
  }
}

const startBackgroundJobsPolling = () => {
  if (backgroundJobsTimer !== null) return
  backgroundJobsTimer = window.setInterval(async () => {
    const hasUnfinished = pastJobs.value.some(j => j.status === 'processing' || j.status === 'pending')
    if (!hasUnfinished && !isUploading.value) {
      stopBackgroundJobsPolling()
      return
    }
    try {
      const res = await apiFetch('/api/jobs')
      if (res.ok) {
        const freshJobs: JobResponse[] = await res.json()
        for (const fj of freshJobs) {
          if (fj.status === 'completed' && !completedJobIds.has(fj.id)) {
            const oldJob = pastJobs.value.find(j => j.id === fj.id)
            if (oldJob && (oldJob.status === 'processing' || oldJob.status === 'pending')) {
              if (fj.id !== activeTranscriptionJob.value?.id) {
                completedJobIds.add(fj.id)
                showToast({
                  title: 'Transcription Complete',
                  message: `"${fj.original_filename}" is ready in your Score Library.`,
                  type: 'success',
                  actionLabel: 'Open Score',
                  duration: 8000,
                  onAction: async () => {
                    await loadJobIntoViewer(fj)
                  }
                })
                dispatchDesktopNotification('NoteSight: Transcription Complete', {
                  body: `"${fj.original_filename}" transcription is ready in your library.`
                })
              }
            }
          }
        }
        pastJobs.value = freshJobs
      }
    } catch {
      // Ignore background refresh errors
    }
  }, 5000)
}

const stopBackgroundJobsPolling = () => {
  if (backgroundJobsTimer !== null) {
    clearInterval(backgroundJobsTimer)
    backgroundJobsTimer = null
  }
}

const stopPolling = () => {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const resetApp = () => {
  if (!isUploading.value) {
    stopPolling()
    progressDetail.value = ''
  }
  isStudioModeActive.value = false
  isLibraryOpen.value = false
  selectedFile.value = null
  currentJob.value = null
  musicXmlContent.value = null
  isLoadingScoreNotation.value = false
  errorMessage.value = null
  quotaWarning.value = null
}

const handleScoreTitleUpdated = (newTitle: string) => {
  if (currentJob.value) {
    const ext = currentJob.value.original_filename.includes('.')
      ? '.' + currentJob.value.original_filename.split('.').pop()
      : '.musicxml'
    const newFilename = `${newTitle}${ext}`
    currentJob.value.original_filename = newFilename

    const found = pastJobs.value.find(j => j.id === currentJob.value?.id)
    if (found) {
      found.original_filename = newFilename
    }
  }
}

// Rename Score Modal State
const isRenameModalOpen = ref(false)
const jobToRename = ref<JobResponse | null>(null)
const renameTitleInput = ref('')
const isRenamingJob = ref(false)

const openRenameModal = (job: JobResponse) => {
  jobToRename.value = job
  renameTitleInput.value = job.original_filename.replace(/\.[^/.]+$/, '')
  isRenameModalOpen.value = true
}

const handleConfirmRename = async () => {
  if (!jobToRename.value || !renameTitleInput.value.trim()) return
  const newTitle = renameTitleInput.value.trim()
  isRenamingJob.value = true
  try {
    const res = await apiFetch(`/api/jobs/${jobToRename.value.id}/rename`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: newTitle }),
    })
    if (res.ok) {
      const updated = await res.json()
      const idx = pastJobs.value.findIndex(j => j.id === jobToRename.value?.id)
      if (idx !== -1) {
        pastJobs.value[idx].original_filename = updated.original_filename
      }
      if (currentJob.value?.id === jobToRename.value.id) {
        currentJob.value.original_filename = updated.original_filename
      }
      showToast({
        title: 'Score Renamed',
        message: `Score renamed to "${newTitle}".`,
        type: 'success',
      })
      isRenameModalOpen.value = false
    } else {
      const err = await res.json().catch(() => ({}))
      showToast({
        title: 'Rename Failed',
        message: err.detail || 'Could not rename score.',
        type: 'error',
      })
    }
  } catch (err) {
    showToast({
      title: 'Rename Failed',
      message: 'Network communication error.',
      type: 'error',
    })
  } finally {
    isRenamingJob.value = false
  }
}

const handleScoreCreated = async ({ title, composer, musicXml }: { title: string; composer: string; musicXml: string }) => {
  isCreationModalOpen.value = false
  musicXmlContent.value = musicXml
  selectedFile.value = null
  errorMessage.value = null

  const token = localStorage.getItem('token')
  if (token) {
    try {
      isSavingNewScore.value = true
      const res = await apiFetch('/api/jobs/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          composer,
          musicxml: musicXml
        })
      })
      if (res.ok) {
        const createdJob: JobResponse = await res.json()
        currentJob.value = createdJob
        await fetchUserJobs()
        await fetchUserQuota()
      } else {
        const err = await res.json().catch(() => ({}))
        console.warn('Failed to persist created score:', err)
        currentJob.value = {
          id: `custom-${Date.now()}`,
          status: 'completed',
          original_filename: `${title}.musicxml`,
          file_path: null,
          result_file_path: null,
          error_message: null
        }
      }
    } catch (e) {
      console.error('Score creation request error:', e)
      currentJob.value = {
        id: `custom-${Date.now()}`,
        status: 'completed',
        original_filename: `${title}.musicxml`,
        file_path: null,
        result_file_path: null,
        error_message: null
      }
    } finally {
      isSavingNewScore.value = false
    }
  } else {
    currentJob.value = {
      id: `custom-${Date.now()}`,
      status: 'completed',
      original_filename: `${title}.musicxml`,
      file_path: null,
      result_file_path: null,
      error_message: null
    }
  }
}

const retryingJobId = ref<string | null>(null)

const isJobStalled = (job: JobResponse): boolean => {
  if (job.status !== 'processing' && job.status !== 'pending') return false
  if (!job.created_at) return false
  const ageMs = Date.now() - new Date(job.created_at).getTime()
  return ageMs > 5 * 60 * 1000 // 5 minutes
}

const retryJob = async (job: JobResponse, force: boolean = false) => {
  if (retryingJobId.value) return
  retryingJobId.value = job.id

  try {
    const url = force || isJobStalled(job) ? `/api/jobs/${job.id}/retry?force=true` : `/api/jobs/${job.id}/retry`
    const response = await apiFetch(url, {
      method: 'POST',
    })

    if (response.status === 401) {
      handleUnauthorized()
      return
    }

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}))
      throw new Error(errData.detail || 'Failed to retry transcription')
    }

    const updatedJob: JobResponse = await response.json()

    // Update job in pastJobs
    const matchIdx = pastJobs.value.findIndex(j => j.id === job.id)
    if (matchIdx !== -1) {
      pastJobs.value[matchIdx] = updatedJob
    }

    // Set as active transcription and start polling/SSE
    isUploading.value = true
    isUploadCardDismissed.value = false
    isUploadCardMinimized.value = false
    errorMessage.value = null
    activeTranscriptionJob.value = updatedJob
    progressDetail.value = 'Restarting transcription...'

    startPolling(updatedJob.id)

    showToast({
      title: 'Transcription Restarted',
      message: `Retrying recognition for "${job.original_filename}"...`,
      type: 'info',
      duration: 5000,
    })
  } catch (err: any) {
    showToast({
      title: 'Retry Failed',
      message: err.message || 'Could not restart transcription.',
      type: 'error',
      duration: 6000,
    })
  } finally {
    retryingJobId.value = null
  }
}

const requestDeleteJob = (job: JobResponse) => {
  jobPendingDelete.value = job
  showConfirmModal.value = true
}

const requestCleanEditorScore = () => {
  if (!currentJob.value) return
  jobPendingDelete.value = currentJob.value
  showConfirmModal.value = true
}

const cancelDelete = () => {
  showConfirmModal.value = false
  jobPendingDelete.value = null
}

const confirmDelete = async () => {
  if (!jobPendingDelete.value) return
  const target = jobPendingDelete.value
  isDeleting.value = true

  try {
    const isBackendJob = target.id && target.id.length >= 32 && !target.id.startsWith('sample-')
    if (isBackendJob) {
      const res = await apiFetch(`/api/jobs/${target.id}`, {
        method: 'DELETE',
      })
      if (res.status === 401) {
        handleUnauthorized()
        return
      }
    }

    pastJobs.value = pastJobs.value.filter(j => j.id !== target.id)
    await fetchUserQuota()

    if (currentJob.value?.id === target.id) {
      resetApp()
    }
  } catch (err) {
    console.error('Failed to delete score job:', err)
  } finally {
    isDeleting.value = false
    showConfirmModal.value = false
    jobPendingDelete.value = null
  }
}

const loadJobIntoViewer = async (job: JobResponse) => {
  if (job.status !== 'completed') return
  errorMessage.value = null
  musicXmlContent.value = null
  currentJob.value = job
  isUploading.value = false
  isLibraryOpen.value = false
  await fetchMusicXml(job.id)
}

const loadDemoScore = async (type: 'staff' | 'twinkle' | 'beethoven' | 'bach') => {
  errorMessage.value = null
  if (type === 'bach' || type === 'twinkle') {
    try {
      isUploading.value = true
      let res = await fetch('/samples/bach_prelude.musicxml')
      if (!res.ok) {
        res = await fetch('/samples/twinkle.musicxml')
      }
      if (!res.ok) throw new Error('Could not load sample file')
      const xml = await res.text()
      currentJob.value = {
        id: 'sample-bach',
        status: 'completed',
        original_filename: 'Johann_Sebastian_Bach_Prelude_in_C_Major_BWV_846.musicxml',
        result_file_path: '/samples/bach_prelude.musicxml',
        error_message: null,
      }
      musicXmlContent.value = xml
      showToast({
        title: 'Demo Score Loaded',
        message: 'J. S. Bach: Prelude in C Major loaded into Studio.',
        type: 'success',
        duration: 4000,
      })
    } catch (err: any) {
      errorMessage.value = err.message || 'Failed to load demo score'
      showToast({
        title: 'Demo Load Failed',
        message: err.message || 'Failed to load demo score',
        type: 'error',
        duration: 5000,
      })
    } finally {
      isUploading.value = false
    }
  } else if (type === 'beethoven' || type === 'staff') {
    try {
      isUploading.value = true
      let res = await fetch('/samples/beethoven_ode_to_joy.png')
      if (!res.ok) {
        res = await fetch('/samples/simple_staff.png')
      }
      if (!res.ok) throw new Error('Could not load sample file')
      const blob = await res.blob()
      const sampleFile = new File([blob], 'Beethoven_Ode_to_Joy.png', { type: 'image/png' })
      selectedFile.value = sampleFile
      await startUpload()
    } catch (err: any) {
      errorMessage.value = err.message || 'Failed to test demo score'
      showToast({
        title: 'Demo Upload Failed',
        message: err.message || 'Failed to test demo score',
        type: 'error',
        duration: 5000,
      })
      isUploading.value = false
    }
  }
}


const downloadFile = async (url: string, filename: string) => {
  try {
    const response = await apiFetch(url)
    if (response.status === 401) {
      handleUnauthorized()
      return
    }
    if (!response.ok) throw new Error('Download failed')
    const blob = await response.blob()
    const downloadUrl = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = downloadUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(downloadUrl)
  } catch (err: any) {
    errorMessage.value = err.message || 'Download error'
  }
}

const triggerBlobDownload = (blob: Blob, filename: string) => {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

const downloadMidiFromXml = async (xmlString: string, filename: string) => {
  const formData = new FormData()
  const blob = new Blob([xmlString], { type: 'application/vnd.recordare.musicxml+xml' })
  formData.append('file', blob, filename.replace(/\.mid$/, '.musicxml'))

  const response = await apiFetch('/api/convert/xml-to-midi', {
    method: 'POST',
    body: formData,
  })
  if (!response.ok) throw new Error('MIDI generation failed')
  const midiBlob = await response.blob()
  triggerBlobDownload(midiBlob, filename)
}

const downloadPdfFromXml = async (xmlString: string, filename: string) => {
  const formData = new FormData()
  const blob = new Blob([xmlString], { type: 'application/vnd.recordare.musicxml+xml' })
  formData.append('file', blob, filename.replace(/\.pdf$/, '.musicxml'))

  const response = await apiFetch('/api/convert/xml-to-pdf', {
    method: 'POST',
    body: formData,
  })
  if (!response.ok) throw new Error('PDF generation failed')
  const pdfBlob = await response.blob()
  triggerBlobDownload(pdfBlob, filename)
}

const handleMusicXmlDownload = () => {
  if (!currentJob.value) return
  const filename = `${currentJob.value.original_filename.replace(/\.[^/.]+$/, '')}.musicxml`
  if (musicXmlContent.value) {
    const blob = new Blob([musicXmlContent.value], { type: 'application/vnd.recordare.musicxml+xml' })
    triggerBlobDownload(blob, filename)
    return
  }
  downloadFile(`/api/jobs/${currentJob.value.id}/download`, filename)
}

const handlePdfDownload = async () => {
  if (!currentJob.value) return
  const filename = `${currentJob.value.original_filename.replace(/\.[^/.]+$/, '')}.pdf`

  if (currentJob.value.id.startsWith('sample-') || currentJob.value.id === 'sample-twinkle') {
    if (musicXmlContent.value) {
      try {
        await downloadPdfFromXml(musicXmlContent.value, filename)
        return
      } catch (err: any) {
        console.warn('Direct PDF conversion failed, trying job endpoint:', err)
      }
    }
  }

  try {
    await downloadFile(`/api/jobs/${currentJob.value.id}/export/pdf`, filename)
  } catch (err: any) {
    if (musicXmlContent.value) {
      await downloadPdfFromXml(musicXmlContent.value, filename)
    } else {
      errorMessage.value = err.message || 'PDF export failed'
    }
  }
}

const handleMidiDownload = async () => {
  if (!currentJob.value) return
  const filename = `${currentJob.value.original_filename.replace(/\.[^/.]+$/, '')}.mid`

  if (currentJob.value.id.startsWith('sample-') || currentJob.value.id === 'sample-twinkle') {
    if (musicXmlContent.value) {
      try {
        await downloadMidiFromXml(musicXmlContent.value, filename)
        return
      } catch (err: any) {
        console.warn('Direct MIDI conversion failed, trying job endpoint:', err)
      }
    }
  }

  try {
    await downloadFile(`/api/jobs/${currentJob.value.id}/export/midi`, filename)
  } catch (err: any) {
    if (musicXmlContent.value) {
      await downloadMidiFromXml(musicXmlContent.value, filename)
    } else {
      errorMessage.value = err.message || 'MIDI export failed'
    }
  }
}

const formatJobTime = (isoString?: string) => {
  if (!isoString) return ''
  try {
    const date = new Date(isoString)
    return date.toLocaleDateString(currentLocale.value, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return ''
  }
}

const handleOpenLibraryEvent = () => {
  isLibraryOpen.value = true
}

const handleCloseScoreEvent = () => {
  resetApp()
}

watch(isLibraryOpen, (isOpen) => {
  if (isOpen) {
    fetchUserJobs()
  }
})

onMounted(() => {
  fetchUserJobs()
  fetchUserQuota()
  window.addEventListener('notesight:open-library', handleOpenLibraryEvent)
  window.addEventListener('notesight:close-score', handleCloseScoreEvent)
  window.addEventListener('paste', handleGlobalPaste)

  // Handle Stripe Hosted Checkout return redirects
  if (route.query.payment === 'success' || route.query.mock_payment === 'success') {
    const rawTier = (route.query.tier as string) || 'pro'
    const tierDisplay = rawTier.charAt(0).toUpperCase() + rawTier.slice(1)
    fetchUserQuota()
    showToast({
      title: 'Subscription Activated! 🎉',
      message: `Welcome to NoteSight ${tierDisplay}! Your account limits and storage capacity have been upgraded.`,
      type: 'success',
      duration: 8000,
    })
    router.replace({ query: {} })
  } else if (route.query.payment === 'cancelled') {
    showToast({
      title: 'Checkout Cancelled',
      message: 'No payment was processed. Your current plan was kept unchanged.',
      type: 'info',
      duration: 6000,
    })
    router.replace({ query: {} })
  }
})

onUnmounted(() => {
  stopPolling()
  stopBackgroundJobsPolling()
  window.removeEventListener('notesight:open-library', handleOpenLibraryEvent)
  window.removeEventListener('notesight:close-score', handleCloseScoreEvent)
  window.removeEventListener('paste', handleGlobalPaste)
})
</script>

<template>
  <div class="dashboard-view" :class="{ 'is-wide-canvas': currentJob && currentJob.status === 'completed', 'is-studio-active': isStudioModeActive }">
    <!-- Top Action Bar -->
    <div
      v-if="!isStudioModeActive && !(currentJob && currentJob.status === 'completed') && (!isMobile || mobileWorkspaceTab === 'create')"
      class="dashboard-topbar"
    >
      <div class="topbar-title-group">
        <h1 class="page-title">{{ isMobile && mobileWorkspaceTab === 'create' ? t('dashboard.newScore') : t('dashboard.topbarTitle') }}</h1>
        <p class="page-subtitle">{{ t('dashboard.topbarSubtitle') }}</p>
      </div>

      <div v-if="!isMobile" class="topbar-actions">
        <div v-if="userQuota" class="topbar-quota-pills">
          <span class="format-pill">
            {{ t('dashboard.pagesThisMonth', { used: userQuota.pages.processed_this_month, limit: userQuota.pages.monthly_limit }) }}
          </span>
          <span class="format-pill">
            {{ t('dashboard.storageUsed', { used: userQuota.storage.used_mb, limit: userQuota.storage.limit_mb }) }}
          </span>
        </div>

        <button
          type="button"
          class="dlp-help-trigger"
          @click="isDlpHelpModalOpen = true"
        >
          <svg class="dlp-help-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="16" x2="12" y2="12"></line>
            <line x1="12" y1="8" x2="12.01" y2="8"></line>
          </svg>
          <span>{{ t('dashboard.dlpHelpLink') }}</span>
        </button>
      </div>
    </div>

    <!-- Error Alert -->
    <div v-if="errorMessage" class="alert-box error">
      <div class="alert-msg">
        <svg class="alert-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>
        <span>{{ errorMessage }}</span>
      </div>
      <div class="alert-right-actions">
        <button 
          v-if="errorMessage.toLowerCase().includes('quota') || errorMessage.toLowerCase().includes('limit') || errorMessage.toLowerCase().includes('upgrade')"
          class="alert-upgrade-btn"
          @click="isPlanModalOpen = true"
        >
          {{ t('common.upgradePlan') }}
        </button>
        <button class="close-btn" @click="errorMessage = null">✕</button>
      </div>
    </div>

    <!-- Pre-Upload Quota Warning Alert -->
    <div v-if="quotaWarning" class="alert-box warning">
      <div class="alert-msg">
        <svg class="alert-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
          <line x1="12" y1="9" x2="12" y2="13"></line>
          <line x1="12" y1="17" x2="12.01" y2="17"></line>
        </svg>
        <span>{{ quotaWarning }}</span>
      </div>
      <div class="alert-right-actions">
        <button class="alert-upgrade-btn" @click="isPlanModalOpen = true">
          {{ t('common.upgradePlan') }}
        </button>
        <button class="close-btn" @click="quotaWarning = null">✕</button>
      </div>
    </div>

    <!-- Workspace Section -->
    <section v-if="!currentJob || currentJob.status === 'pending' || currentJob.status === 'processing'" class="upload-section">
      <!-- DESKTOP: Compact Creation & Import Command Bar (Dropzone) -->
      <div 
        v-if="!isMobile"
        class="dropzone command-bar-dropzone"
        :class="{ 'dragging': isDragging, 'disabled': isUploading && !isUploadCardMinimized && !isUploadCardDismissed }"
        @dragover.prevent="isDragging = true"
        @dragleave.prevent="isDragging = false"
        @drop.prevent="handleDrop"
      >
        <div class="command-bar-content">
          <div class="command-bar-lead">
            <div class="upload-icon-wrapper compact-icon">
              <svg class="upload-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="17 8 12 3 7 8"></polyline>
                <line x1="12" y1="3" x2="12" y2="15"></line>
              </svg>
            </div>
            <div class="command-bar-copy">
              <h3>{{ t('dashboard.uploadTitle') }}</h3>
              <div class="command-bar-hints">
                <span class="format-pill">{{ t('dashboard.pdfMultipage') }}</span>
                <span class="format-pill">{{ t('dashboard.pngJpg') }}</span>
                <span class="format-pill paste-pill" :title="t('dashboard.dlpHelpOptionPasteDesc')">
                  <kbd class="kbd-badge">Ctrl+V</kbd> {{ t('dashboard.pasteClipboardHint') }}
                </span>
              </div>
            </div>
          </div>

          <div class="command-bar-actions">
            <label class="browse-btn" :class="{ 'disabled': isUploading && !isUploadCardMinimized && !isUploadCardDismissed }">
              <svg class="action-btn-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="17 8 12 3 7 8"></polyline>
                <line x1="12" y1="3" x2="12" y2="15"></line>
              </svg>
              <span>{{ t('dashboard.browseFiles') }}</span>
              <input 
                type="file" 
                accept=".pdf,.png,.jpg,.jpeg,.tiff,.bmp" 
                :disabled="isUploading && !isUploadCardMinimized && !isUploadCardDismissed"
                @change="handleFileSelect" 
                hidden 
              />
            </label>

            <button
              type="button"
              class="create-scratch-btn"
              :disabled="isUploading && !isUploadCardMinimized && !isUploadCardDismissed"
              @click.stop="isCreationModalOpen = true"
            >
              <svg class="scratch-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 5v14M5 12h14"></path>
              </svg>
              <span>{{ t('dashboard.createBlankScore') }}</span>
            </button>

            <button
              type="button"
              class="import-url-action-btn"
              :disabled="isUploading && !isUploadCardMinimized && !isUploadCardDismissed"
              @click.stop="isUrlImportModalOpen = true"
              :title="t('dashboard.importUrlSubtitle')"
            >
              <svg class="action-btn-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="2" y1="12" x2="22" y2="12"></line>
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
              </svg>
              <span>{{ t('dashboard.importUrlBtn') }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- MOBILE: Dedicated New / Import Score Tab Workspace -->
      <div v-else-if="mobileWorkspaceTab === 'create'" class="mobile-create-workspace">
        <div class="mobile-action-cards-grid">
          <!-- 1. Upload File (PDF / Image) -->
          <label class="mobile-create-card primary-card" :class="{ 'disabled': isUploading && !isUploadCardMinimized && !isUploadCardDismissed }">
            <div class="mobile-card-icon-box primary">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="17 8 12 3 7 8"></polyline>
                <line x1="12" y1="3" x2="12" y2="15"></line>
              </svg>
            </div>
            <div class="mobile-card-body">
              <strong>{{ t('dashboard.browseFiles') }}</strong>
              <span>{{ t('dashboard.pdfMultipage') }} • {{ t('dashboard.pngJpg') }}</span>
            </div>
            <input 
              type="file" 
              accept=".pdf,.png,.jpg,.jpeg,.tiff,.bmp" 
              :disabled="isUploading && !isUploadCardMinimized && !isUploadCardDismissed"
              @change="handleFileSelect" 
              hidden 
            />
          </label>

          <!-- 2. Scan with Camera -->
          <button
            type="button"
            class="mobile-create-card"
            :disabled="isScanning"
            @click="capturePhoto('camera')"
          >
            <div class="mobile-card-icon-box accent">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path>
                <circle cx="12" cy="13" r="4"></circle>
              </svg>
            </div>
            <div class="mobile-card-body">
              <strong>{{ t('landing.step1Title') }}</strong>
              <span>{{ t('dashboard.dlpHelpOptionMobileTitle') }}</span>
            </div>
          </button>

          <!-- 3. Select Photos from Gallery -->
          <button
            type="button"
            class="mobile-create-card"
            :disabled="isScanning"
            @click="capturePhoto('photos')"
          >
            <div class="mobile-card-icon-box emerald">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                <circle cx="8.5" cy="8.5" r="1.5"></circle>
                <polyline points="21 15 16 10 5 21"></polyline>
              </svg>
            </div>
            <div class="mobile-card-body">
              <strong>{{ t('dashboard.pngJpg') }}</strong>
              <span>{{ t('dashboard.stepUpload') }}</span>
            </div>
          </button>

          <!-- 4. Compose Blank Score -->
          <button
            type="button"
            class="mobile-create-card"
            @click="isCreationModalOpen = true"
          >
            <div class="mobile-card-icon-box violet">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 5v14M5 12h14"></path>
              </svg>
            </div>
            <div class="mobile-card-body">
              <strong>{{ t('dashboard.createScore') }}</strong>
              <span>{{ t('dashboard.dlpHelpOptionBlankTitle') }}</span>
            </div>
          </button>

          <!-- 5. Import from Web URL -->
          <button
            type="button"
            class="mobile-create-card"
            @click="isUrlImportModalOpen = true"
          >
            <div class="mobile-card-icon-box subtle">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="2" y1="12" x2="22" y2="12"></line>
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
              </svg>
            </div>
            <div class="mobile-card-body">
              <strong>{{ t('dashboard.dlpHelpOpenUrlBtn') }}</strong>
              <span>{{ t('dashboard.dlpHelpOptionUrlTitle') }}</span>
            </div>
          </button>
        </div>

        <div v-if="scanError" class="alert-box error">
          <span>{{ scanError }}</span>
        </div>

        <!-- Inline Multi-Page Photo Batch Staging Tray -->
        <div v-if="scannedPages.length > 0" class="mobile-scan-staging-tray">
          <div class="staging-tray-header">
            <h4>{{ t('dashboard.stepSegment') }} ({{ scannedPages.length }})</h4>
            <button type="button" class="staging-clear-btn" @click="clearPages">
              {{ t('common.reset') }}
            </button>
          </div>

          <div class="staging-pages-strip">
            <div v-for="(page, idx) in scannedPages" :key="page.id" class="staging-page-thumb">
              <span class="staging-page-num">{{ idx + 1 }}</span>
              <img :src="page.previewUrl" :alt="`Page ${idx + 1}`" />
              <div class="staging-page-controls">
                <button type="button" @click="rotatePage(idx)" :aria-label="t('common.options')">↻</button>
                <button type="button" class="danger" @click="removePage(idx)" :aria-label="t('common.remove')">✕</button>
              </div>
            </div>
          </div>

          <div class="staging-submit-row">
            <input
              v-model="mobileScanTitle"
              type="text"
              class="staging-title-input"
              :placeholder="t('dashboard.importUrlTitlePlaceholder')"
            />
            <button
              type="button"
              class="primary-btn staging-submit-btn"
              :disabled="isSubmittingUpload"
              @click="handleSubmitScannedPages"
            >
              <span>{{ t('dashboard.startRecognition') }} ({{ scannedPages.length }})</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Hidden file input fallback when on mobile library tab so programmatic file tests always work -->
      <input
        v-else
        type="file"
        accept=".pdf,.png,.jpg,.jpeg,.tiff,.bmp"
        @change="handleFileSelect"
        hidden
      />

      <!-- Selected File Card -->
      <div v-if="selectedFile && (!isUploading || isUploadCardMinimized || isUploadCardDismissed)" class="selected-file-card">
        <div class="selected-file-info">
          <svg class="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
          </svg>
          <div class="selected-file-text">
            <span class="selected-filename">{{ selectedFile.name }}</span>
            <span class="selected-filesize">{{ (selectedFile.size / 1024).toFixed(1) }} KB</span>
          </div>
        </div>
        <div class="selected-file-actions">
          <button class="remove-file-btn" @click="clearSelectedFile" :disabled="isSubmittingUpload" :title="t('dashboard.removeFileTitle')">✕</button>
          <button class="primary-btn" @click="startUpload" :disabled="isSubmittingUpload">
            <span v-if="isSubmittingUpload" class="status-spinner-small"></span>
            <span>{{ isSubmittingUpload ? (t('dashboard.uploadingFile') || 'Uploading...') : t('dashboard.startRecognition') }}</span>
          </button>
        </div>
      </div>

      <!-- Demo Scores Quick Picker -->
      <div
        class="demo-scores-bar"
        v-if="(pastJobs.length === 0 || (isMobile && mobileWorkspaceTab === 'create')) && (!currentJob || currentJob.status !== 'completed')"
      >
        <div class="demo-label-group">
          <span class="demo-label">{{ t('dashboard.orTrySampleScores') }}</span>
        </div>
        <div class="demo-buttons">
          <button class="demo-btn" @click="loadDemoScore('beethoven')" :disabled="isUploading && !isUploadCardMinimized && !isUploadCardDismissed" :title="t('dashboard.beethovenOdeDemo')">
            <svg class="demo-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M9 18V5l12-2v13"></path>
              <circle cx="6" cy="18" r="3"></circle>
              <circle cx="18" cy="16" r="3"></circle>
            </svg>
            <span>{{ t('dashboard.beethovenOdeDemo') }}</span>
          </button>
          <button class="demo-btn" @click="loadDemoScore('bach')" :disabled="isUploading && !isUploadCardMinimized && !isUploadCardDismissed" :title="t('dashboard.bachPreludeDemo')">
            <svg class="demo-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="2" y="4" width="20" height="16" rx="2"></rect>
              <line x1="6" y1="4" x2="6" y2="12"></line>
              <line x1="10" y1="4" x2="10" y2="12"></line>
              <line x1="14" y1="4" x2="14" y2="12"></line>
              <line x1="18" y1="4" x2="18" y2="12"></line>
            </svg>
            <span>{{ t('dashboard.bachPreludeDemo') }}</span>
          </button>
        </div>
      </div>

      <!-- Processing Multi-stage Status Progress Card (Ticket P1-1) -->
      <div v-if="isUploading && !isUploadCardMinimized && !isUploadCardDismissed" class="status-card">
        <div class="status-card-header">
          <div class="status-card-title-group">
            <div class="spinner-small"></div>
            <h4>{{ t('dashboard.transcribingSheetMusic') }}</h4>
          </div>
          <div class="status-card-header-actions">
            <button 
              type="button" 
              class="card-minimize-btn" 
              @click="isUploadCardMinimized = true"
              :title="t('dashboard.minimizeHint')"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
              <span>{{ t('dashboard.minimize') }}</span>
            </button>
            <button 
              type="button" 
              class="card-dismiss-btn" 
              @click="isUploadCardDismissed = true"
              :title="t('dashboard.dismiss')"
            >
              ✕
            </button>
          </div>
        </div>

        <p class="status-detail">
          Status: <span class="badge">{{ activeTranscriptionJob?.status || 'uploading' }}</span>
          <span v-if="progressDetail" class="progress-subtext"> — {{ progressDetail }}</span>
        </p>

        <!-- Reassuring Background Processing Notice Box (Ticket P1-1) -->
        <div class="status-reassure-box">
          <div class="reassure-icon-wrapper">
            <svg class="reassure-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="16" x2="12" y2="12"></line>
              <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>
          </div>
          <div class="reassure-text">
            <strong>{{ t('dashboard.processingInBackground') }}</strong>
            <span>{{ t('dashboard.processingInBackgroundHint') }}</span>
          </div>
        </div>

        <!-- Progress Steps -->
        <div class="pipeline-steps">
          <div class="pipeline-step completed">
            <span class="step-check">✓</span>
            <span class="step-label">{{ t('dashboard.stepUpload') }}</span>
          </div>
          <div class="pipeline-step" :class="{ 'active': !progressDetail || progressDetail.includes('Preparing') || progressDetail.includes('page 1 of'), 'completed': progressDetail && !progressDetail.includes('Preparing') && !progressDetail.includes('page 1 of') }">
            <span class="step-check">●</span>
            <span class="step-label">{{ t('dashboard.stepSegment') }}</span>
          </div>
          <div class="pipeline-step" :class="{ 'active': progressDetail && (progressDetail.includes('Recognizing page') || progressDetail.includes('page 2') || progressDetail.includes('page 3')), 'completed': progressDetail.includes('Stitch') }">
            <span class="step-check">●</span>
            <span class="step-label">{{ t('dashboard.stepOmr') }}</span>
          </div>
          <div class="pipeline-step" :class="{ 'active': progressDetail.includes('Stitch') }">
            <span class="step-check">○</span>
            <span class="step-label">{{ t('dashboard.stepStitch') }}</span>
          </div>
        </div>

        <div class="status-card-footer">
          <p class="hint">{{ t('dashboard.extractingHint') }}</p>
          <button 
            type="button" 
            class="continue-bg-btn" 
            @click="isUploadCardMinimized = true"
          >
            {{ t('dashboard.continueInBackground') }}
          </button>
        </div>
      </div>

      <!-- Inline Score Library Workspace Grid -->
      <div v-if="!isMobile || mobileWorkspaceTab === 'library'" class="workspace-library-section">
        <div class="workspace-library-header">
          <div class="workspace-library-title-group">
            <svg class="drawer-header-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
            </svg>
            <h2 class="workspace-library-title">{{ t('dashboard.scoreLibrary') }}</h2>
            <span class="drawer-count-badge">{{ pastJobs.length }}</span>
            <span v-if="processingJobsCount > 0" class="drawer-processing-badge">
              <span class="processing-pulse-dot"></span>
              <span>{{ t('dashboard.processingCount', { count: processingJobsCount }) }}</span>
            </span>
            <button
              v-if="isMobile"
              type="button"
              class="mobile-new-score-pill-btn"
              @click="mobileWorkspaceTab = 'create'"
            >
              + {{ t('dashboard.newScore') }}
            </button>
          </div>

          <div class="workspace-library-controls" v-if="pastJobs.length > 0">
            <div class="library-search-box">
              <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
              </svg>
              <input
                v-model="librarySearchQuery"
                type="search"
                class="library-search-input"
                :placeholder="t('dashboard.searchScores')"
                :aria-label="t('dashboard.searchScores')"
              />
              <button v-if="librarySearchQuery" type="button" class="search-clear-btn" @click="librarySearchQuery = ''">✕</button>
            </div>

            <div class="library-filter-pills" role="group" :aria-label="t('dashboard.filterPlaceholder')">
              <button
                type="button"
                class="filter-pill-btn"
                :class="{ active: libraryStatusFilter === 'all' }"
                @click="libraryStatusFilter = 'all'"
              >
                {{ t('dashboard.filterAll') }}
              </button>
              <button
                type="button"
                class="filter-pill-btn"
                :class="{ active: libraryStatusFilter === 'completed' }"
                @click="libraryStatusFilter = 'completed'"
              >
                {{ t('dashboard.scoreStatusCompleted') }}
              </button>
              <button
                type="button"
                class="filter-pill-btn"
                :class="{ active: libraryStatusFilter === 'processing' }"
                @click="libraryStatusFilter = 'processing'"
              >
                {{ t('dashboard.scoreStatusProcessing') }}
              </button>
            </div>

            <select v-model="librarySortBy" class="library-sort-select" :aria-label="t('common.options')">
              <option value="newest">{{ t('dashboard.sortNewest') }}</option>
              <option value="title">{{ t('dashboard.sortTitle') }}</option>
            </select>
          </div>
        </div>

        <div v-if="isLoadingJobs" class="drawer-loading">
          <div class="spinner-small"></div>
          <span>{{ t('common.loading') }}</span>
        </div>

        <div v-else-if="pastJobs.length === 0" class="workspace-library-empty">
          <svg class="empty-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
          </svg>
          <h4>{{ t('dashboard.noScoresFound') }}</h4>
          <p>{{ t('dashboard.noScoresHint') }}</p>
          <button
            v-if="isMobile"
            type="button"
            class="primary-btn empty-library-cta-btn"
            @click="mobileWorkspaceTab = 'create'"
          >
            + {{ t('dashboard.newScore') }}
          </button>
        </div>

        <div v-else-if="filteredJobs.length === 0" class="workspace-library-empty">
          <h4>{{ t('dashboard.noMatchingScores') }}</h4>
          <p>{{ t('dashboard.noMatchingScoresHint') }}</p>
        </div>

        <div v-else class="workspace-job-grid">
          <div
            v-for="job in filteredJobs"
            :key="`inline-${job.id}`"
            class="job-card workspace-job-card"
            :class="{ 'is-active': currentJob?.id === job.id, 'can-click': job.status === 'completed', 'is-processing': job.status === 'processing' || job.status === 'pending' }"
            @click="job.status === 'completed' && loadJobIntoViewer(job)"
          >
            <div class="job-card-top">
              <div class="job-title-row">
                <svg class="job-file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                  <polyline points="14 2 14 8 20 8"></polyline>
                </svg>
                <strong class="job-filename" :title="job.original_filename">{{ job.original_filename }}</strong>
              </div>
              <span class="status-pill" :class="job.status">
                <span v-if="job.status === 'processing' || job.status === 'pending'" class="status-spinner-small"></span>
                {{ job.status === 'completed' ? t('dashboard.scoreStatusCompleted') : job.status === 'processing' ? t('dashboard.scoreStatusProcessing') : job.status === 'failed' ? t('dashboard.scoreStatusFailed') : t('dashboard.scoreStatusPending') }}
              </span>
            </div>

            <div class="job-card-meta">
              <span class="job-time">{{ formatJobTime(job.created_at) }}</span>
              <span v-if="job.file_size_bytes" class="job-size-badge">
                {{ (job.file_size_bytes / (1024 * 1024)).toFixed(1) }} MB
              </span>
              <span v-if="job.page_count" class="job-pages-badge">
                {{ job.page_count === 1 ? t('dashboard.pageCountSingle', { count: job.page_count }) : t('dashboard.pageCountPlural', { count: job.page_count }) }}
              </span>
              <span v-if="isJobStalled(job)" class="job-stalled-badge" title="Transcription taking longer than 5 minutes">
                {{ t('dashboard.stalled') || 'Stalled' }}
              </span>
              <span v-if="(job.status === 'processing' || job.status === 'pending') && job.id === activeTranscriptionJob?.id && progressDetail" class="job-progress-live">
                {{ progressDetail }}
              </span>
            </div>

            <div v-if="job.status === 'failed' && job.error_message" class="job-error-detail">
              <svg class="job-error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="8" x2="12" y2="12"></line>
                <line x1="12" y1="16" x2="12.01" y2="16"></line>
              </svg>
              <span class="job-error-text">{{ job.error_message }}</span>
            </div>

            <div class="job-card-actions" @click.stop>
              <button v-if="job.status === 'completed'" class="job-chip load-chip" @click="loadJobIntoViewer(job)">
                {{ t('dashboard.openScore') }}
              </button>
              <button
                v-if="job.status === 'completed'"
                type="button"
                class="job-chip rename-chip"
                @click="openRenameModal(job)"
                title="Rename Score"
              >
                <svg class="chip-rename-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"></path>
                </svg>
                <span>{{ t('common.rename') || 'Rename' }}</span>
              </button>
              <button
                v-if="job.status === 'failed' || isJobStalled(job)"
                class="job-chip retry-chip"
                :disabled="retryingJobId === job.id"
                @click="retryJob(job)"
                :title="isJobStalled(job) ? (t('dashboard.retryStalledHint') || 'Transcription may be stalled. Click to retry.') : t('dashboard.retryHint')"
                :aria-label="t('dashboard.retryHint')"
              >
                <svg v-if="retryingJobId !== job.id" class="chip-retry-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="23 4 23 10 17 10"></polyline>
                  <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                </svg>
                <span v-else class="status-spinner-small"></span>
                <span>{{ retryingJobId === job.id ? t('dashboard.retrying') : t('dashboard.retry') }}</span>
              </button>
              <button class="job-chip delete-chip" @click="requestDeleteJob(job)" :title="t('dashboard.deleteScoreTitle')">
                <svg class="chip-trash-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="3 6 5 6 21 6"></polyline>
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                  <line x1="10" y1="11" x2="10" y2="17"></line>
                  <line x1="14" y1="11" x2="14" y2="17"></line>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Completed View -->
    <section v-if="currentJob && currentJob.status === 'completed'" class="result-section" :class="{ 'in-studio': isStudioModeActive }">
      <div v-if="!isStudioModeActive && !musicXmlContent && !isLoadingScoreNotation" class="result-header">
        <div class="result-title-group">
          <h2>{{ currentJob.original_filename }}</h2>
          <p class="success-text">
            <svg class="check-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <path d="M20 6L9 17l-5-5"></path>
            </svg>
            MusicXML and MIDI transcription ready
          </p>
        </div>
        <div class="header-actions">
          <button @click="handlePdfDownload" class="action-btn pdf-btn" title="Download Printable PDF">
            <svg class="action-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
            <span>PDF</span>
          </button>
          <button @click="handleMidiDownload" class="action-btn midi-btn" title="Download Standard MIDI file">
            <svg class="action-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M9 18V5l12-2v13"></path>
              <circle cx="6" cy="18" r="3"></circle>
              <circle cx="18" cy="16" r="3"></circle>
            </svg>
            <span>MIDI</span>
          </button>
          <button @click="handleMusicXmlDownload" class="action-btn xml-btn" title="Download MusicXML">
            <svg class="action-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            <span>MusicXML</span>
          </button>
          <button class="action-btn danger-btn" @click="requestCleanEditorScore" title="Clean up and delete score">
            <svg class="action-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              <line x1="10" y1="11" x2="10" y2="17"></line>
              <line x1="14" y1="11" x2="14" y2="17"></line>
            </svg>
            <span>Clean Up</span>
          </button>
          <button class="action-btn secondary-btn" @click="resetApp">
            {{ t('dashboard.newScore') }}
          </button>
        </div>
      </div>

      <!-- Interactive Score Render & Performance Suite -->
      <ScoreViewer
        v-if="musicXmlContent"
        v-model:is-studio-mode="isStudioModeActive"
        :music-xml="musicXmlContent"
        :job-id="currentJob?.id"
        :score-title="currentJob?.original_filename ? currentJob.original_filename.replace(/\.[^/.]+$/, '') : undefined"
        :page-count="currentJob?.page_count"
        :show-back-button="true"
        :has-original-source="!!currentJob?.file_path || (!!currentJob?.id && !currentJob.id.startsWith('custom-'))"
        @back="resetApp"
        @export-pdf="handlePdfDownload"
        @export-midi="handleMidiDownload"
        @export-xml="handleMusicXmlDownload"
        @cleanup="requestCleanEditorScore"
        @update:music-xml="musicXmlContent = $event"
        @update:score-title="handleScoreTitleUpdated"
      />
      <!-- Loading State: Shown while notation is fetching -->
      <div v-else-if="isLoadingScoreNotation" class="studio-loading-state" role="status" aria-live="polite">
        <div class="studio-loader-card">
          <div class="score-loader-pulse">
            <div class="loader-spinner"></div>
            <svg class="loader-note-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M9 18V5l12-2v13"></path>
              <circle cx="6" cy="18" r="3"></circle>
              <circle cx="18" cy="16" r="3"></circle>
            </svg>
          </div>
          <h3>{{ t('dashboard.loadingScoreNotation') }}</h3>
          <p v-if="currentJob?.original_filename" class="score-filename-highlight">
            {{ currentJob.original_filename.replace(/\.[^/.]+$/, '') }}
          </p>
          <p class="loader-subtext">
            {{ t('dashboard.loadingScoreNotationSubtitle') }}
          </p>
          <div class="loader-shimmer-bar">
            <div class="shimmer-indicator"></div>
          </div>
        </div>
      </div>
      <!-- Error / Empty State: ONLY shown when loading has finished and notation could not be loaded -->
      <div v-else class="studio-empty-state">
        <div class="empty-state-card">
          <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M9 18V5l12-2v13"></path>
            <circle cx="6" cy="18" r="3"></circle>
            <circle cx="18" cy="16" r="3"></circle>
          </svg>
          <h3>{{ t('dashboard.scoreNotationNotLoaded') }}</h3>
          <p>{{ t('dashboard.scoreNotationNotLoadedDesc') }}</p>
          <div class="empty-state-actions">
            <button class="primary-btn" @click="currentJob?.id && fetchMusicXml(currentJob.id)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="btn-icon">
                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"></path>
              </svg>
              <span>{{ t('dashboard.reloadNotation') }}</span>
            </button>
            <button class="secondary-btn" @click="resetApp">
              {{ t('dashboard.newScore') }}
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- Score Library Slide-out Drawer & Confirmation Dialog -->
    <teleport to="body">
      <div v-if="isLibraryOpen" class="drawer-backdrop" @click="isLibraryOpen = false"></div>
      <aside class="library-drawer" :class="{ 'is-open': isLibraryOpen }">
        <div class="drawer-header">
          <div class="drawer-title-group">
            <svg class="drawer-header-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 6.5 2z"></path>
            </svg>
            <h3>{{ t('dashboard.scoreLibrary') }}</h3>
            <span class="drawer-count-badge">{{ pastJobs.length }}</span>
            <span v-if="processingJobsCount > 0" class="drawer-processing-badge">
              <span class="processing-pulse-dot"></span>
              <span>{{ t('dashboard.processingCount', { count: processingJobsCount }) }}</span>
            </span>
          </div>
          <button class="drawer-close-btn" @click="isLibraryOpen = false" aria-label="Close library">✕</button>
        </div>

        <div class="drawer-filter-bar" v-if="pastJobs.length > 0">
          <div class="library-search-box">
            <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <input
              v-model="librarySearchQuery"
              type="search"
              class="library-search-input"
              :placeholder="t('dashboard.searchScores')"
              :aria-label="t('dashboard.searchScores')"
            />
            <button v-if="librarySearchQuery" type="button" class="search-clear-btn" @click="librarySearchQuery = ''">✕</button>
          </div>
          <div class="library-filter-pills">
            <button
              type="button"
              class="filter-pill-btn"
              :class="{ active: libraryStatusFilter === 'all' }"
              @click="libraryStatusFilter = 'all'"
            >
              {{ t('dashboard.filterAll') }}
            </button>
            <button
              type="button"
              class="filter-pill-btn"
              :class="{ active: libraryStatusFilter === 'completed' }"
              @click="libraryStatusFilter = 'completed'"
            >
              {{ t('dashboard.scoreStatusCompleted') }}
            </button>
            <button
              type="button"
              class="filter-pill-btn"
              :class="{ active: libraryStatusFilter === 'processing' }"
              @click="libraryStatusFilter = 'processing'"
            >
              {{ t('dashboard.scoreStatusProcessing') }}
            </button>
          </div>
        </div>

        <div class="drawer-body">
          <div v-if="isLoadingJobs" class="drawer-loading">
            <div class="spinner-small"></div>
            <span>{{ t('common.loading') }}</span>
          </div>

          <div v-else-if="pastJobs.length === 0" class="drawer-empty">
            <svg class="empty-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
            </svg>
            <h4>{{ t('dashboard.noScoresFound') }}</h4>
            <p>{{ t('dashboard.noScoresHint') }}</p>
          </div>

          <div v-else-if="filteredJobs.length === 0" class="drawer-empty">
            <h4>{{ t('dashboard.noMatchingScores') }}</h4>
            <p>{{ t('dashboard.noMatchingScoresHint') }}</p>
          </div>

          <div v-else class="job-list">
            <div 
              v-for="job in filteredJobs" 
              :key="job.id" 
              class="job-card"
              :class="{ 'is-active': currentJob?.id === job.id, 'can-click': job.status === 'completed', 'is-processing': job.status === 'processing' || job.status === 'pending' }"
              @click="job.status === 'completed' && loadJobIntoViewer(job)"
            >
              <div class="job-card-top">
                <div class="job-title-row">
                  <svg class="job-file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                  </svg>
                  <strong class="job-filename" :title="job.original_filename">{{ job.original_filename }}</strong>
                </div>
                <span class="status-pill" :class="job.status">
                  <span v-if="job.status === 'processing' || job.status === 'pending'" class="status-spinner-small"></span>
                  {{ job.status === 'completed' ? t('dashboard.scoreStatusCompleted') : job.status === 'processing' ? t('dashboard.scoreStatusProcessing') : job.status === 'failed' ? t('dashboard.scoreStatusFailed') : t('dashboard.scoreStatusPending') }}
                </span>
              </div>

              <div class="job-card-meta">
                <span class="job-time">{{ formatJobTime(job.created_at) }}</span>
                <span v-if="job.file_size_bytes" class="job-size-badge">
                  {{ (job.file_size_bytes / (1024 * 1024)).toFixed(1) }} MB
                </span>
                <span v-if="job.page_count" class="job-pages-badge">
                  {{ job.page_count === 1 ? t('dashboard.pageCountSingle', { count: job.page_count }) : t('dashboard.pageCountPlural', { count: job.page_count }) }}
                </span>
                <span v-if="isJobStalled(job)" class="job-stalled-badge" title="Transcription taking longer than 5 minutes">
                  {{ t('dashboard.stalled') || 'Stalled' }}
                </span>
                <span v-if="(job.status === 'processing' || job.status === 'pending') && job.id === activeTranscriptionJob?.id && progressDetail" class="job-progress-live">
                  {{ progressDetail }}
                </span>
              </div>

              <div v-if="job.status === 'failed' && job.error_message" class="job-error-detail">
                <svg class="job-error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="10"></circle>
                  <line x1="12" y1="8" x2="12" y2="12"></line>
                  <line x1="12" y1="16" x2="12.01" y2="16"></line>
                </svg>
                <span class="job-error-text">{{ job.error_message }}</span>
              </div>

              <div class="job-card-actions" @click.stop>
                <button v-if="job.status === 'completed'" class="job-chip load-chip" @click="loadJobIntoViewer(job)">
                  {{ t('dashboard.openScore') }}
                </button>
                <button
                  v-if="job.status === 'completed'"
                  type="button"
                  class="job-chip rename-chip"
                  @click="openRenameModal(job)"
                  title="Rename Score"
                >
                  <svg class="chip-rename-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"></path>
                  </svg>
                  <span>{{ t('common.rename') || 'Rename' }}</span>
                </button>
                <button
                  v-if="job.status === 'failed' || isJobStalled(job)"
                  class="job-chip retry-chip"
                  :disabled="retryingJobId === job.id"
                  @click="retryJob(job)"
                  :title="isJobStalled(job) ? (t('dashboard.retryStalledHint') || 'Transcription may be stalled. Click to retry.') : t('dashboard.retryHint')"
                  :aria-label="t('dashboard.retryHint')"
                >
                  <svg v-if="retryingJobId !== job.id" class="chip-retry-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="23 4 23 10 17 10"></polyline>
                    <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                  </svg>
                  <span v-else class="status-spinner-small"></span>
                  <span>{{ retryingJobId === job.id ? t('dashboard.retrying') : t('dashboard.retry') }}</span>
                </button>
                <button class="job-chip delete-chip" @click="requestDeleteJob(job)" :title="t('dashboard.deleteScoreTitle')">
                  <svg class="chip-trash-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="3 6 5 6 21 6"></polyline>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    <line x1="10" y1="11" x2="10" y2="17"></line>
                    <line x1="14" y1="11" x2="14" y2="17"></line>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Drawer Footer with Storage Usage Meter -->
        <div v-if="userQuota" class="drawer-footer">
          <div class="drawer-quota-row">
            <span class="drawer-quota-title">{{ t('dashboard.storageQuota') }}</span>
            <span class="drawer-quota-val">
              <strong>{{ userQuota.storage.used_mb }}</strong> / {{ userQuota.storage.limit_mb }} MB ({{ userQuota.storage.percent_used }}%)
            </span>
          </div>
          <div class="drawer-quota-bar">
            <div 
              class="drawer-quota-fill" 
              :style="{ width: `${userQuota.storage.percent_used}%` }"
              :class="{ 
                'warn': userQuota.storage.percent_used > 80, 
                'danger': userQuota.storage.percent_used > 95 
              }"
            ></div>
          </div>
          <button class="drawer-upgrade-link" @click="isPlanModalOpen = true; isLibraryOpen = false">
            {{ t('dashboard.upgradeCapacity', { tier: userQuota.tier_name }) }}
          </button>
        </div>
      </aside>

      <!-- Confirmation Modal Dialog -->
      <div v-if="showConfirmModal" class="confirm-modal-backdrop" @click="cancelDelete">
        <div class="confirm-modal-card" @click.stop role="dialog" aria-modal="true">
          <div class="confirm-modal-header">
            <div class="confirm-warning-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                <line x1="10" y1="11" x2="10" y2="17"></line>
                <line x1="14" y1="11" x2="14" y2="17"></line>
              </svg>
            </div>
            <div>
              <h4 class="confirm-title">{{ t('dashboard.deleteScoreTitle') }}</h4>
              <p class="confirm-subtitle">{{ t('common.warning') }}</p>
            </div>
          </div>

          <div class="confirm-modal-body">
            <p>
              {{ t('dashboard.deleteScorePrompt', { filename: jobPendingDelete?.original_filename || '' }) }}
            </p>
          </div>

          <div class="confirm-modal-footer">
            <button class="confirm-btn cancel-btn" @click="cancelDelete" :disabled="isDeleting">
              {{ t('common.cancel') }}
            </button>
            <button class="confirm-btn delete-btn" @click="confirmDelete" :disabled="isDeleting">
              <span v-if="isDeleting">{{ t('common.deleting') }}</span>
              <span v-else>{{ t('common.delete') }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Rename Score Modal Dialog -->
      <div v-if="isRenameModalOpen" class="confirm-modal-backdrop" @click="isRenameModalOpen = false">
        <div class="confirm-modal-card rename-modal-card" @click.stop role="dialog" aria-modal="true">
          <div class="confirm-modal-header">
            <div class="confirm-warning-icon rename-icon-bg">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"></path>
              </svg>
            </div>
            <div>
              <h4 class="confirm-title">{{ t('common.renameScore') || 'Rename Score' }}</h4>
              <p class="confirm-subtitle">{{ t('common.renameScoreSubtitle') || 'Enter a new title for this score.' }}</p>
            </div>
          </div>

          <div class="confirm-modal-body">
            <label class="rename-input-label">Score Title</label>
            <input
              v-model="renameTitleInput"
              class="rename-modal-input"
              placeholder="e.g. Moonlight Sonata"
              @keydown.enter="handleConfirmRename"
              @keydown.esc="isRenameModalOpen = false"
              autoFocus
            />
          </div>

          <div class="confirm-modal-footer">
            <button class="confirm-btn cancel-btn" @click="isRenameModalOpen = false" :disabled="isRenamingJob">
              {{ t('common.cancel') || 'Cancel' }}
            </button>
            <button
              class="confirm-btn confirm-save-btn"
              @click="handleConfirmRename"
              :disabled="!renameTitleInput.trim() || isRenamingJob"
            >
              <span v-if="isRenamingJob">{{ t('common.saving') || 'Saving...' }}</span>
              <span v-else>{{ t('common.save') || 'Save' }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Floating Docked Background Processing Pill (Track P1) -->
      <div 
        v-if="isUploading && (isUploadCardMinimized || isUploadCardDismissed || !!currentJob)" 
        class="docked-processing-pill"
        role="region"
        :aria-label="t('dashboard.processingInBackground')"
      >
        <div class="docked-pill-inner" @click="isUploadCardMinimized = false; isUploadCardDismissed = false">
          <span class="docked-spinner"></span>
          <div class="docked-pill-info">
            <div class="docked-pill-title-row">
              <span class="docked-pill-title">
                {{ t('dashboard.dockedTranscribing') }} <strong>{{ activeTranscriptionJob?.original_filename || 'Score' }}</strong>
              </span>
              <span class="docked-live-tag">{{ t('dashboard.dockedBackground') }}</span>
            </div>
            <span class="docked-pill-sub">{{ progressDetail || t('dashboard.transcribingProgress') }}</span>
          </div>
          <button 
            type="button" 
            class="docked-expand-btn" 
            :title="t('dashboard.dockedViewHint')"
            @click.stop="isUploadCardMinimized = false; isUploadCardDismissed = false"
          >
            {{ t('dashboard.dockedView') }}
          </button>
          <button
            type="button"
            class="docked-dismiss-btn"
            :title="t('dashboard.dockedDismissHint')"
            @click.stop="isUploadCardDismissed = true"
          >
            ✕
          </button>
        </div>
      </div>
    </teleport>

    <!-- Score Creation Wizard Modal -->
    <ScoreCreationModal
      :is-open="isCreationModalOpen"
      @close="isCreationModalOpen = false"
      @create="handleScoreCreated"
    />

    <!-- URL Import Modal -->
    <teleport to="body">
      <div v-if="isUrlImportModalOpen" class="confirm-modal-backdrop" @click="isUrlImportModalOpen = false">
        <div class="url-import-modal-card" @click.stop role="dialog" aria-modal="true">
          <div class="modal-header-row">
            <div class="modal-title-group">
              <div class="url-icon-bubble">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="10"></circle>
                  <line x1="2" y1="12" x2="22" y2="12"></line>
                  <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
                </svg>
              </div>
              <div>
                <h3 class="modal-headline">{{ t('dashboard.importUrlModalTitle') }}</h3>
                <p class="modal-subtitle-text">{{ t('dashboard.importUrlSubtitle') }}</p>
              </div>
            </div>
            <button class="modal-close-btn" @click="isUrlImportModalOpen = false" aria-label="Close">✕</button>
          </div>

          <div v-if="urlImportError" class="modal-error-banner">
            {{ urlImportError }}
          </div>

          <form @submit.prevent="handleUrlImport" class="url-import-form">
            <div class="form-group">
              <label class="form-label">URL *</label>
              <input
                type="url"
                v-model="urlInput"
                :placeholder="t('dashboard.importUrlPlaceholder')"
                class="form-input"
                required
                autofocus
              />
            </div>

            <div class="form-group">
              <label class="form-label">{{ t('dashboard.importUrlTitlePlaceholder') }}</label>
              <input
                type="text"
                v-model="urlTitleInput"
                :placeholder="t('dashboard.importUrlTitlePlaceholder')"
                class="form-input"
              />
            </div>

            <div class="modal-actions-row">
              <button
                type="button"
                class="secondary-btn"
                @click="isUrlImportModalOpen = false"
                :disabled="isImportingUrl"
              >
                {{ t('common.cancel') }}
              </button>
              <button
                type="submit"
                class="primary-btn url-submit-btn"
                :disabled="isImportingUrl || !urlInput.trim()"
              >
                <span v-if="isImportingUrl" class="btn-spinner"></span>
                <span>{{ isImportingUrl ? t('dashboard.importingUrl') : t('dashboard.importUrlSubmit') }}</span>
              </button>
            </div>
          </form>
        </div>
      </div>

      <!-- Restricted Environment / DLP Help Modal -->
      <div v-if="isDlpHelpModalOpen" class="confirm-modal-backdrop" @click="isDlpHelpModalOpen = false">
        <div class="dlp-modal-card" @click.stop role="dialog" aria-modal="true">
          <div class="modal-header-row">
            <div class="modal-title-group">
              <div class="dlp-icon-bubble">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                </svg>
              </div>
              <div>
                <h3 class="modal-headline">{{ t('dashboard.dlpHelpTitle') }}</h3>
                <p class="modal-subtitle-text">{{ t('dashboard.topbarSubtitle') }}</p>
              </div>
            </div>
            <button class="modal-close-btn" @click="isDlpHelpModalOpen = false" aria-label="Close">✕</button>
          </div>

          <p class="dlp-body-desc">{{ t('dashboard.dlpHelpBody') }}</p>

          <div class="dlp-options-grid">
            <div class="dlp-option-card">
              <div class="dlp-card-header">
                <span class="dlp-badge">Ctrl + V</span>
                <h4>{{ t('dashboard.dlpHelpOptionPasteTitle') }}</h4>
              </div>
              <p>{{ t('dashboard.dlpHelpOptionPasteDesc') }}</p>
            </div>

            <div class="dlp-option-card clickable-card" @click="isDlpHelpModalOpen = false; isUrlImportModalOpen = true">
              <div class="dlp-card-header">
                <span class="dlp-badge url-badge">URL</span>
                <h4>{{ t('dashboard.dlpHelpOptionUrlTitle') }}</h4>
              </div>
              <p>{{ t('dashboard.dlpHelpOptionUrlDesc') }}</p>
              <button type="button" class="option-action-link">{{ t('dashboard.dlpHelpOpenUrlBtn') }} →</button>
            </div>

            <div class="dlp-option-card">
              <div class="dlp-card-header">
                <span class="dlp-badge mobile-badge">Mobile</span>
                <h4>{{ t('dashboard.dlpHelpOptionMobileTitle') }}</h4>
              </div>
              <p>{{ t('dashboard.dlpHelpOptionMobileDesc') }}</p>
            </div>

            <div class="dlp-option-card clickable-card" @click="isDlpHelpModalOpen = false; isCreationModalOpen = true">
              <div class="dlp-card-header">
                <span class="dlp-badge blank-badge">Blank</span>
                <h4>{{ t('dashboard.dlpHelpOptionBlankTitle') }}</h4>
              </div>
              <p>{{ t('dashboard.dlpHelpOptionBlankDesc') }}</p>
              <button type="button" class="option-action-link">{{ t('dashboard.createBlankScore') }} →</button>
            </div>
          </div>

          <div class="modal-footer-row">
            <button type="button" class="primary-btn modal-done-btn" @click="isDlpHelpModalOpen = false">
              {{ t('dashboard.dlpHelpClose') }}
            </button>
          </div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<style scoped>
.dashboard-view {
  width: 100%;
}

.dashboard-topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 24px;
  transition: all 0.2s ease;
}

.dashboard-topbar.compact-mode {
  margin-bottom: 12px;
}

.dashboard-topbar.compact-mode .page-title {
  font-size: 1.3rem;
  margin-bottom: 0;
}

.dashboard-topbar.compact-mode .page-subtitle {
  display: none;
}

.page-title {
  font-size: 1.75rem;
  font-weight: 700;
  letter-spacing: -0.5px;
  margin: 0 0 4px 0;
  color: var(--text-primary, #f8fafc);
}

.page-subtitle {
  margin: 0;
  color: var(--text-secondary, #94a3b8);
  font-size: 0.95rem;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.create-score-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--color-primary-light, rgba(99, 102, 241, 0.15));
  border: 1px solid var(--color-primary, #6366f1);
  color: var(--color-primary, #6366f1);
  padding: 8px 16px;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 2px 10px rgba(99, 102, 241, 0.15);
}

.create-score-btn:hover {
  background: var(--color-primary, #4f46e5);
  color: #ffffff;
  border-color: var(--color-primary-hover, #4338ca);
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.3);
}

.scratch-create-row {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
}

.scratch-divider {
  font-size: 0.75rem;
  color: var(--text-muted, #64748b);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.create-scratch-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  background: var(--color-primary-light, rgba(99, 102, 241, 0.12));
  border: 1px dashed var(--color-primary, #6366f1);
  border-radius: 20px;
  color: var(--color-primary, #6366f1);
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.create-scratch-btn:hover:not(:disabled) {
  background: var(--color-primary, #4f46e5);
  border-style: solid;
  color: #ffffff;
  border-color: var(--color-primary-hover, #4338ca);
  transform: translateY(-1px);
}

.scratch-btn-icon {
  width: 14px;
  height: 14px;
}

.library-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  color: var(--text-primary, #f8fafc);
  padding: 8px 16px;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: var(--shadow-sm, 0 1px 3px rgba(0, 0, 0, 0.2));
}

.library-toggle-btn:hover {
  border-color: var(--color-primary, #6366f1);
  color: var(--color-primary, #6366f1);
  transform: translateY(-1px);
}

.btn-icon {
  width: 16px;
  height: 16px;
}

.library-count-badge {
  background: var(--color-primary-light, rgba(99, 102, 241, 0.15));
  color: var(--color-primary, #6366f1);
  font-size: 0.75rem;
  padding: 2px 7px;
  border-radius: 12px;
  font-weight: 700;
}

.topbar-quota-pills {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* Dropzone & Desktop Compact Command Bar */
.dropzone {
  border: 2px dashed var(--border, #28334a);
  background: var(--bg-card, #151b28);
  border-radius: 16px;
  padding: 20px 24px;
  transition: all 0.2s ease;
  box-shadow: var(--shadow-sm);
}

.dropzone.command-bar-dropzone {
  padding: 18px 22px;
  text-align: left;
}

.command-bar-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}

.command-bar-lead {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 260px;
  flex: 1;
}

.upload-icon-wrapper.compact-icon {
  width: 46px;
  height: 46px;
  margin: 0;
  border-radius: 12px;
  flex-shrink: 0;
}

.upload-icon-wrapper.compact-icon .upload-icon-svg {
  width: 22px;
  height: 22px;
}

.command-bar-copy {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.command-bar-copy h3 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text-primary, #f8fafc);
}

.command-bar-hints {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.command-bar-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.dropzone:hover {
  border-color: var(--color-primary, #6366f1);
  box-shadow: var(--shadow-md);
}

.dropzone.dragging {
  border-color: var(--color-accent, #22d3ee);
  background: var(--color-primary-light, rgba(99, 102, 241, 0.1));
}

.dropzone.disabled {
  opacity: 0.6;
  pointer-events: none;
}

.upload-icon-wrapper {
  width: 56px;
  height: 56px;
  margin: 0 auto 16px auto;
  border-radius: 14px;
  background: var(--color-primary-light, rgba(99, 102, 241, 0.12));
  color: var(--color-primary, #6366f1);
  display: flex;
  align-items: center;
  justify-content: center;
}

.upload-icon-svg {
  width: 28px;
  height: 28px;
}

/* Mobile Creation & Import Workspace */
.mobile-create-workspace {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.mobile-action-cards-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.mobile-create-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px;
  border-radius: 16px;
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  color: var(--text-primary, #f8fafc);
  text-align: left;
  cursor: pointer;
  transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
  box-shadow: var(--shadow-sm);
  -webkit-tap-highlight-color: transparent;
}

.mobile-create-card:active {
  transform: scale(0.98);
}

.mobile-create-card.primary-card {
  grid-column: span 2;
  flex-direction: row;
  align-items: center;
  justify-content: flex-start;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.16) 0%, rgba(34, 211, 238, 0.08) 100%);
  border-color: rgba(99, 102, 241, 0.45);
}

.mobile-create-card.full-span-card {
  grid-column: span 2;
  flex-direction: row;
  align-items: center;
  justify-content: flex-start;
}

.mobile-card-icon-box {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.mobile-card-icon-box svg {
  width: 22px;
  height: 22px;
}

.mobile-card-icon-box.primary {
  background: var(--color-primary, #6366f1);
  color: #ffffff;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.35);
}

.mobile-card-icon-box.accent {
  background: rgba(34, 211, 238, 0.15);
  color: var(--color-accent, #22d3ee);
}

.mobile-card-icon-box.emerald {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.mobile-card-icon-box.violet {
  background: rgba(139, 92, 246, 0.15);
  color: #a78bfa;
}

.mobile-card-icon-box.subtle {
  background: var(--bg-subtle, rgba(255, 255, 255, 0.06));
  color: var(--text-secondary, #94a3b8);
}

.mobile-card-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.mobile-card-body strong {
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--text-primary, #f8fafc);
}

.mobile-card-body span {
  font-size: 0.78rem;
  color: var(--text-secondary, #94a3b8);
  line-height: 1.3;
}

/* Inline Multi-Page Photo Batch Staging Tray */
.mobile-scan-staging-tray {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--color-primary, #6366f1);
  border-radius: 16px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: var(--shadow-md);
}

.staging-tray-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.staging-tray-header h4 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--text-primary, #f8fafc);
}

.staging-clear-btn {
  background: none;
  border: none;
  color: var(--color-danger, #ef4444);
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}

.staging-pages-strip {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 6px;
}

.staging-page-thumb {
  position: relative;
  width: 110px;
  height: 146px;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--border, #28334a);
  background: #0b0f17;
  flex-shrink: 0;
}

.staging-page-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.staging-page-num {
  position: absolute;
  top: 6px;
  left: 6px;
  background: rgba(15, 23, 42, 0.85);
  color: #ffffff;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 999px;
}

.staging-page-controls {
  position: absolute;
  bottom: 6px;
  right: 6px;
  display: flex;
  gap: 4px;
}

.staging-page-controls button {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: none;
  background: rgba(15, 23, 42, 0.85);
  color: #ffffff;
  font-size: 0.78rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.staging-page-controls button.danger {
  color: #f87171;
}

.staging-submit-row {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.staging-title-input {
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #28334a);
  border-radius: 10px;
  padding: 10px 12px;
  color: var(--text-primary, #f8fafc);
  font-size: 0.9rem;
  outline: none;
}

.staging-submit-btn {
  width: 100%;
  min-height: 44px;
  justify-content: center;
}

.mobile-new-score-pill-btn {
  margin-left: auto;
  background: var(--color-primary, #6366f1);
  color: #ffffff;
  border: none;
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 0.8rem;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.empty-library-cta-btn {
  margin-top: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.format-badges {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 24px;
}

.format-pill {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 20px;
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #28334a);
  color: var(--text-muted, #64748b);
}

.paste-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: var(--bg-card, #151b28);
  border-color: var(--color-primary-light, rgba(99, 102, 241, 0.3));
  color: var(--text-normal, #e2e8f0);
}

.kbd-badge {
  font-family: inherit;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 1px 5px;
  background: var(--bg-subtle, #1e293b);
  border: 1px solid var(--border, #334155);
  border-radius: 4px;
  color: var(--color-primary, #818cf8);
}

.upload-action-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 4px;
}

.action-btn-svg {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.browse-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--color-primary, #6366f1);
  color: #ffffff;
  padding: 10px 22px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.95rem;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.25);
}

.browse-btn:hover {
  background: var(--color-primary-hover, #818cf8);
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35);
}

.import-url-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-subtle, #1c2336);
  color: var(--text-normal, #e2e8f0);
  border: 1px solid var(--border, #334155);
  padding: 10px 20px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.95rem;
  cursor: pointer;
  transition: all 0.2s;
}

.import-url-action-btn:hover {
  background: var(--bg-hover, #28334a);
  border-color: var(--color-primary, #6366f1);
  color: #ffffff;
  transform: translateY(-1px);
}

.dlp-help-wrapper {
  margin-top: 18px;
  display: flex;
  justify-content: center;
}

.dlp-help-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: none;
  border: none;
  color: var(--text-muted, #94a3b8);
  font-size: 0.82rem;
  cursor: pointer;
  padding: 4px 10px;
  border-radius: 6px;
  transition: color 0.15s, background 0.15s;
}

.dlp-help-trigger:hover {
  color: var(--color-primary, #818cf8);
  background: var(--bg-subtle, rgba(99, 102, 241, 0.08));
  text-decoration: underline;
}

.dlp-help-icon {
  width: 14px;
  height: 14px;
}

/* Selected File Card */
.selected-file-card {
  margin-top: 20px;
  padding: 14px 20px;
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  border-radius: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: var(--shadow-sm);
}

.selected-file-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.file-icon {
  width: 24px;
  height: 24px;
  color: var(--color-primary, #6366f1);
}

.selected-file-text {
  display: flex;
  flex-direction: column;
}

.selected-filename {
  font-weight: 600;
  color: var(--text-primary, #f8fafc);
  font-size: 0.95rem;
}

.selected-filesize {
  font-size: 0.8rem;
  color: var(--text-secondary, #94a3b8);
}

.selected-file-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.remove-file-btn {
  background: none;
  border: none;
  color: var(--text-muted, #64748b);
  font-size: 1.1rem;
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  transition: color 0.2s;
}

.remove-file-btn:hover {
  color: var(--color-danger, #ef4444);
}

.primary-btn {
  background: linear-gradient(135deg, var(--color-primary, #6366f1) 0%, var(--color-accent, #22d3ee) 100%);
  color: #ffffff;
  border: none;
  padding: 10px 24px;
  border-radius: 8px;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.3);
}

.primary-btn:hover {
  opacity: 0.92;
  transform: translateY(-1px);
}

/* Demo Scores Bar */
.demo-scores-bar {
  margin-top: 20px;
  padding: 12px 18px;
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  border-radius: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.demo-label-group {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.demo-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-primary, #f8fafc);
}

.demo-hint {
  font-size: 0.8rem;
  color: var(--text-muted, #64748b);
}

.demo-buttons {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.demo-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #28334a);
  color: var(--text-primary, #f8fafc);
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.demo-btn:hover:not(:disabled) {
  border-color: var(--color-primary, #6366f1);
  color: var(--color-primary, #6366f1);
  transform: translateY(-1px);
}

.demo-icon {
  width: 14px;
  height: 14px;
}

/* Processing Status Card */
.status-card {
  margin-top: 32px;
  background: var(--bg-card, #151b28);
  padding: 32px 24px;
  border-radius: 14px;
  border: 1px solid var(--border, #28334a);
  box-shadow: var(--shadow-md);
  text-align: center;
}

.spinner-large {
  width: 48px;
  height: 48px;
  border: 4px solid var(--border, #28334a);
  border-top-color: var(--color-primary, #6366f1);
  border-right-color: var(--color-accent, #22d3ee);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 16px auto;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.badge {
  background: var(--color-primary-light, rgba(99, 102, 241, 0.15));
  color: var(--color-primary, #6366f1);
  padding: 4px 10px;
  border-radius: 6px;
  text-transform: uppercase;
  font-size: 0.8rem;
  font-weight: 600;
}

.pipeline-steps {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  max-width: 640px;
  margin: 20px auto 14px auto;
}

.pipeline-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px 8px;
  border-radius: 8px;
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #28334a);
  font-size: 0.78rem;
  color: var(--text-muted, #64748b);
}

.pipeline-step.completed {
  border-color: rgba(16, 185, 129, 0.3);
  color: var(--color-success, #10b981);
}

.pipeline-step.active {
  border-color: var(--color-primary, #6366f1);
  color: var(--color-primary, #6366f1);
  font-weight: 600;
  box-shadow: 0 0 10px rgba(99, 102, 241, 0.2);
}

.step-check {
  font-size: 0.9rem;
}

.hint {
  font-size: 0.85rem;
  color: var(--text-secondary, #94a3b8);
  margin-top: 12px;
}

/* Result Section */
.result-section.in-studio {
  margin: 0;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 10px;
}

.result-title-group h2 {
  font-size: 1.2rem;
  font-weight: 700;
  margin: 0 0 2px 0;
  color: var(--text-primary, #f8fafc);
}

.success-text {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--color-success, #10b981);
  font-weight: 500;
  font-size: 0.82rem;
  margin: 0;
}

.check-icon {
  width: 15px;
  height: 15px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: all 0.2s ease;
}

.action-btn-icon {
  width: 14px;
  height: 14px;
}

.pdf-btn {
  background: #dc2626;
  color: #ffffff;
}
.pdf-btn:hover { background: #b91c1c; }

.midi-btn {
  background: var(--color-primary, #6366f1);
  color: #ffffff;
}
.midi-btn:hover { background: var(--color-primary-hover, #818cf8); }

.xml-btn {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  color: var(--text-primary, #f8fafc);
}
.xml-btn:hover {
  border-color: var(--color-primary, #6366f1);
  color: var(--color-primary, #6366f1);
}

.secondary-btn {
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #28334a);
  color: var(--text-primary, #f8fafc);
}
.secondary-btn:hover {
  background: var(--border, #28334a);
}

/* Alert Box */
.alert-box.error {
  background: var(--color-danger-light, rgba(239, 68, 68, 0.1));
  border: 1px solid var(--color-danger, #ef4444);
  color: var(--color-danger-text, #ef4444);
  padding: 12px 18px;
  border-radius: 10px;
  margin-bottom: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.alert-box.warning {
  background: var(--color-warning-light, rgba(245, 158, 11, 0.12));
  border: 1px solid var(--color-warning, #f59e0b);
  color: var(--color-warning-text, #f59e0b);
  padding: 12px 18px;
  border-radius: 10px;
  margin-bottom: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.alert-right-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.alert-upgrade-btn {
  background: var(--color-primary, #6366f1);
  color: #ffffff;
  border: none;
  border-radius: 6px;
  padding: 5px 12px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
  white-space: nowrap;
}

.alert-upgrade-btn:hover {
  background: var(--color-primary-hover, #818cf8);
}

.alert-msg {
  display: flex;
  align-items: center;
  gap: 10px;
}

.alert-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.close-btn {
  background: none;
  border: none;
  color: inherit;
  font-size: 1.1rem;
  cursor: pointer;
  padding: 4px;
}

/* Score Library Slide-out Drawer */
.drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(2px);
  z-index: 998;
}

.library-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 420px;
  max-width: 90vw;
  background: var(--bg-card, #151b28);
  border-left: 1px solid var(--border, #28334a);
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.35);
  z-index: 999;
  display: flex;
  flex-direction: column;
  transform: translateX(100%);
  transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1);
}

.library-drawer.is-open {
  transform: translateX(0);
}

.drawer-header {
  padding: 20px 24px;
  border-bottom: 1px solid var(--border, #28334a);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.drawer-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.drawer-header-icon {
  width: 20px;
  height: 20px;
  color: var(--color-primary, #6366f1);
}

.drawer-header h3 {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--text-primary, #f8fafc);
}

.drawer-count-badge {
  background: var(--color-primary-light, rgba(99, 102, 241, 0.15));
  color: var(--color-primary, #6366f1);
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 700;
}

.drawer-close-btn {
  background: none;
  border: none;
  color: var(--text-muted, #64748b);
  font-size: 1.25rem;
  cursor: pointer;
  padding: 4px;
  transition: color 0.2s;
}

.drawer-close-btn:hover {
  color: var(--text-primary, #f8fafc);
}

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
}

.drawer-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: var(--text-secondary, #94a3b8);
  gap: 12px;
}

.spinner-small {
  width: 24px;
  height: 24px;
  border: 3px solid var(--border, #28334a);
  border-top-color: var(--color-primary, #6366f1);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.drawer-empty {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-secondary, #94a3b8);
}

.empty-icon-svg {
  width: 44px;
  height: 44px;
  color: var(--text-muted, #64748b);
  margin-bottom: 12px;
}

.drawer-empty h4 {
  margin: 0 0 6px 0;
  color: var(--text-primary, #f8fafc);
}

.drawer-empty p {
  margin: 0;
  font-size: 0.85rem;
  color: var(--text-secondary, #94a3b8);
}

.studio-loading-state {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 420px;
  padding: 64px 20px;
  background: var(--bg-card, #131929);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  border-radius: 12px;
  margin-top: 20px;
}

.studio-loader-card {
  text-align: center;
  max-width: 440px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.score-loader-pulse {
  position: relative;
  width: 68px;
  height: 68px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20px;
}

.score-loader-pulse .loader-spinner {
  position: absolute;
  inset: 0;
  border: 3px solid rgba(99, 102, 241, 0.15);
  border-top-color: var(--color-primary, #6366f1);
  border-right-color: var(--color-accent, #06b6d4);
  border-radius: 50%;
  animation: spin 0.9s cubic-bezier(0.5, 0.1, 0.5, 0.9) infinite;
}

.loader-note-icon {
  width: 28px;
  height: 28px;
  color: var(--color-accent, #06b6d4);
  animation: pulse-glow 2s ease-in-out infinite;
}

@keyframes pulse-glow {
  0%, 100% {
    opacity: 0.6;
    transform: scale(0.95);
  }
  50% {
    opacity: 1;
    transform: scale(1.05);
  }
}

.studio-loader-card h3 {
  margin: 0 0 8px 0;
  font-size: 1.2rem;
  font-weight: 600;
  color: var(--text-primary, #f8fafc);
  letter-spacing: -0.01em;
}

.score-filename-highlight {
  margin: 0 0 6px 0;
  font-size: 0.92rem;
  font-weight: 500;
  color: var(--color-accent, #06b6d4);
  max-width: 380px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.loader-subtext {
  margin: 0 0 22px 0;
  font-size: 0.88rem;
  color: var(--text-secondary, #94a3b8);
  line-height: 1.5;
}

.loader-shimmer-bar {
  width: 220px;
  height: 4px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 9999px;
  overflow: hidden;
  position: relative;
}

.shimmer-indicator {
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  width: 45%;
  background: linear-gradient(90deg, transparent, var(--color-primary, #6366f1), var(--color-accent, #06b6d4), transparent);
  border-radius: 9999px;
  animation: shimmer-slide 1.5s ease-in-out infinite;
}

@keyframes shimmer-slide {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(250%);
  }
}

.studio-empty-state {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 64px 20px;
  background: var(--bg-card, #131929);
  border: 1px dashed var(--border, rgba(255, 255, 255, 0.1));
  border-radius: 12px;
  margin-top: 20px;
}

.empty-state-card {
  text-align: center;
  max-width: 440px;
}

.empty-state-icon {
  width: 48px;
  height: 48px;
  color: var(--text-muted, #64748b);
  margin-bottom: 16px;
}

.empty-state-card h3 {
  margin: 0 0 8px 0;
  font-size: 1.15rem;
  color: var(--text-primary, #f8fafc);
}

.empty-state-card p {
  margin: 0 0 20px 0;
  font-size: 0.9rem;
  color: var(--text-secondary, #94a3b8);
  line-height: 1.5;
}

.empty-state-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
}

.job-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.job-card {
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #28334a);
  border-radius: 12px;
  padding: 14px;
  transition: all 0.2s ease;
}

.job-card.can-click {
  cursor: pointer;
}

.job-card.can-click:hover {
  border-color: var(--color-primary, #6366f1);
  transform: translateY(-1px);
}

.job-card.is-active {
  border-color: var(--color-primary, #6366f1);
  box-shadow: 0 0 0 1px var(--color-primary, #6366f1);
}

.job-card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}

.job-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
}

.job-file-icon {
  width: 16px;
  height: 16px;
  color: var(--color-primary, #6366f1);
  flex-shrink: 0;
}

.job-filename {
  font-size: 0.9rem;
  color: var(--text-primary, #f8fafc);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.status-pill {
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 2px 7px;
  border-radius: 6px;
  flex-shrink: 0;
}

.status-pill.completed {
  background: var(--color-success-light, rgba(16, 185, 129, 0.15));
  color: var(--color-success, #10b981);
}

.status-pill.pending,
.status-pill.processing {
  background: var(--color-warning-light, rgba(245, 158, 11, 0.15));
  color: var(--color-warning, #f59e0b);
}

.status-pill.failed {
  background: var(--color-danger-light, rgba(239, 68, 68, 0.15));
  color: var(--color-danger, #ef4444);
}

.job-card-meta {
  margin-top: 6px;
  font-size: 0.75rem;
  color: var(--text-muted, #64748b);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.job-size-badge,
.job-pages-badge {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.7rem;
  color: var(--text-secondary, #94a3b8);
}

.job-stalled-badge {
  background: var(--color-danger-light, rgba(239, 68, 68, 0.15));
  border: 1px solid rgba(239, 68, 68, 0.3);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--color-danger, #ef4444);
}

.job-error-detail {
  margin-top: 8px;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 0.72rem;
  color: var(--color-danger, #ef4444);
  line-height: 1.35;
}

.job-error-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  margin-top: 1px;
}

.job-error-text {
  word-break: break-word;
}

.job-card-actions {
  display: flex;
  gap: 6px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border, #28334a);
}

.job-chip {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  color: var(--text-primary, #f8fafc);
  font-size: 0.75rem;
  padding: 4px 8px;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.job-chip:hover {
  border-color: var(--color-primary, #6366f1);
  color: var(--color-primary, #6366f1);
}

.job-chip.load-chip {
  background: var(--color-primary, #6366f1);
  border-color: var(--color-primary, #6366f1);
  color: var(--color-primary-contrast, #ffffff);
  flex: 1;
  text-align: center;
}

.job-chip.load-chip:hover {
  background: var(--color-primary-hover, #818cf8);
  border-color: var(--color-primary-hover, #818cf8);
}

.job-chip.retry-chip {
  background: var(--color-primary, #6366f1);
  border-color: var(--color-primary, #6366f1);
  color: var(--color-primary-contrast, #ffffff);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex: 1;
  text-align: center;
}

.job-chip.retry-chip:hover:not(:disabled) {
  background: var(--color-primary-hover, #818cf8);
  border-color: var(--color-primary-hover, #818cf8);
  color: var(--color-primary-contrast, #ffffff);
}

.job-chip.retry-chip:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.chip-retry-icon {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
}

.job-chip.delete-chip {
  padding: 4px 6px;
  color: var(--text-muted, #64748b);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.job-chip.delete-chip:hover {
  border-color: var(--color-danger, #ef4444);
  color: var(--color-danger, #ef4444);
  background: var(--color-danger-light, rgba(239, 68, 68, 0.12));
}

.chip-trash-icon {
  width: 14px;
  height: 14px;
}

.job-chip.rename-chip {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  color: var(--text-secondary, #94a3b8);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 5px 9px;
  font-size: 0.78rem;
  font-weight: 600;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.job-chip.rename-chip:hover {
  border-color: var(--color-primary, #6366f1);
  color: var(--text-primary, #ffffff);
  background: rgba(99, 102, 241, 0.12);
}

.chip-rename-icon {
  width: 12px;
  height: 12px;
}

.rename-icon-bg {
  background: rgba(99, 102, 241, 0.15) !important;
  color: var(--color-primary, #6366f1) !important;
}

.rename-input-label {
  display: block;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-secondary, #94a3b8);
  margin-bottom: 6px;
}

.rename-modal-input {
  width: 100%;
  padding: 10px 14px;
  background: var(--input-bg, #0b0f19);
  border: 1px solid var(--border, #28334a);
  border-radius: 8px;
  color: var(--text-primary, #ffffff);
  font-size: 0.95rem;
  font-weight: 600;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
  box-sizing: border-box;
}

.rename-modal-input:focus {
  border-color: var(--color-primary, #6366f1);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
}

.confirm-btn.confirm-save-btn {
  background: var(--color-primary, #6366f1);
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.confirm-btn.confirm-save-btn:hover:not(:disabled) {
  background: var(--color-primary-hover, #4f46e5);
}

.confirm-btn.confirm-save-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-btn.danger-btn {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  color: var(--text-secondary, #94a3b8);
}

.action-btn.danger-btn:hover {
  border-color: var(--color-danger, #ef4444);
  color: var(--color-danger, #ef4444);
  background: var(--color-danger-light, rgba(239, 68, 68, 0.12));
  transform: translateY(-1px);
}

/* Confirmation Modal */
.confirm-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(4px);
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.confirm-modal-card {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  border-radius: 16px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.45);
  width: 100%;
  max-width: 440px;
  overflow: hidden;
  animation: scaleUp 0.2s ease;
}

@keyframes scaleUp {
  from { transform: scale(0.95); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}

.confirm-modal-header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 20px 24px;
  border-bottom: 1px solid var(--border, #28334a);
}

.confirm-warning-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: var(--color-danger-light, rgba(239, 68, 68, 0.12));
  color: var(--color-danger, #ef4444);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.confirm-warning-icon svg {
  width: 22px;
  height: 22px;
}

.confirm-title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--text-primary, #f8fafc);
}

.confirm-subtitle {
  margin: 2px 0 0 0;
  font-size: 0.8rem;
  color: var(--text-secondary, #94a3b8);
}

.confirm-modal-body {
  padding: 20px 24px;
  font-size: 0.92rem;
  line-height: 1.5;
  color: var(--text-secondary, #94a3b8);
}

.confirm-modal-body strong {
  color: var(--text-primary, #f8fafc);
  word-break: break-all;
}

.confirm-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 24px;
  background: var(--bg-subtle, #1c2336);
  border-top: 1px solid var(--border, #28334a);
}

.confirm-btn {
  padding: 9px 18px;
  border-radius: 8px;
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: all 0.2s ease;
}

.confirm-btn.cancel-btn {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  color: var(--text-primary, #f8fafc);
}

.confirm-btn.cancel-btn:hover:not(:disabled) {
  background: var(--border, #28334a);
}

.confirm-btn.delete-btn {
  background: var(--color-danger, #ef4444);
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(239, 68, 68, 0.3);
}

.confirm-btn.delete-btn:hover:not(:disabled) {
  background: #dc2626;
  box-shadow: 0 4px 14px rgba(239, 68, 68, 0.4);
}

.confirm-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* URL Import & DLP Modal Cards */
.url-import-modal-card,
.dlp-modal-card {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  border-radius: 16px;
  width: 100%;
  max-width: 540px;
  padding: 24px 28px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
  color: var(--text-normal, #e2e8f0);
  animation: modalScaleIn 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.dlp-modal-card {
  max-width: 620px;
}

@keyframes modalScaleIn {
  from {
    opacity: 0;
    transform: scale(0.96) translateY(8px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

.modal-header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.modal-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.url-icon-bubble,
.dlp-icon-bubble {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: rgba(99, 102, 241, 0.15);
  color: var(--color-primary, #818cf8);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.url-icon-bubble svg,
.dlp-icon-bubble svg {
  width: 22px;
  height: 22px;
}

.modal-headline {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--text-strong, #ffffff);
}

.modal-subtitle-text {
  margin: 4px 0 0 0;
  font-size: 0.85rem;
  color: var(--text-muted, #94a3b8);
}

.modal-close-btn {
  background: none;
  border: none;
  color: var(--text-muted, #94a3b8);
  font-size: 1.1rem;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  transition: color 0.15s, background 0.15s;
}

.modal-close-btn:hover {
  color: #ffffff;
  background: var(--bg-hover, #28334a);
}

.modal-error-banner {
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #f87171;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 0.85rem;
  margin-bottom: 16px;
}

.url-import-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 14px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-muted, #94a3b8);
}

.form-input {
  width: 100%;
  padding: 10px 14px;
  background: var(--bg-canvas, #0c0f17);
  border: 1px solid var(--border, #28334a);
  border-radius: 8px;
  color: #ffffff;
  font-size: 0.92rem;
  outline: none;
  transition: border-color 0.2s;
}

.form-input:focus {
  border-color: var(--color-primary, #6366f1);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
}

.modal-actions-row,
.modal-footer-row {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 8px;
}

.url-submit-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.btn-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #ffffff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.dlp-body-desc {
  font-size: 0.9rem;
  color: var(--text-normal, #cbd5e1);
  line-height: 1.5;
  margin: 12px 0 16px 0;
}

.dlp-options-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}

@media (max-width: 600px) {
  .dlp-options-grid {
    grid-template-columns: 1fr;
  }
}

.dlp-option-card {
  background: var(--bg-subtle, #192030);
  border: 1px solid var(--border, #28334a);
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dlp-option-card p {
  margin: 0;
  font-size: 0.82rem;
  color: var(--text-muted, #94a3b8);
  line-height: 1.4;
}

.dlp-option-card.clickable-card {
  cursor: pointer;
  transition: border-color 0.15s, transform 0.15s, background 0.15s;
}

.dlp-option-card.clickable-card:hover {
  border-color: var(--color-primary, #6366f1);
  background: var(--bg-hover, #212a3f);
  transform: translateY(-1px);
}

.dlp-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dlp-card-header h4 {
  margin: 0;
  font-size: 0.88rem;
  font-weight: 600;
  color: #ffffff;
}

.dlp-badge {
  font-size: 0.68rem;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(99, 102, 241, 0.2);
  color: var(--color-primary, #818cf8);
}

.dlp-badge.url-badge {
  background: rgba(14, 165, 233, 0.2);
  color: #38bdf8;
}

.dlp-badge.mobile-badge {
  background: rgba(168, 85, 247, 0.2);
  color: #c084fc;
}

.dlp-badge.blank-badge {
  background: rgba(34, 197, 94, 0.2);
  color: #4ade80;
}

.option-action-link {
  background: none;
  border: none;
  color: var(--color-primary, #818cf8);
  font-size: 0.8rem;
  font-weight: 600;
  padding: 0;
  margin-top: 4px;
  cursor: pointer;
  text-align: left;
}

.option-action-link:hover {
  text-decoration: underline;
}

.modal-done-btn {
  padding: 8px 24px;
}

/* Drawer Storage Footer */
.drawer-footer {
  padding: 16px 20px;
  background: var(--bg-subtle, #1c2336);
  border-top: 1px solid var(--border, #28334a);
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}

.drawer-quota-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.78rem;
}

.drawer-quota-title {
  color: var(--text-secondary, #94a3b8);
  font-weight: 500;
}

.drawer-quota-val {
  color: var(--text-primary, #f8fafc);
}

.drawer-quota-bar {
  width: 100%;
  height: 6px;
  background: var(--bg-card, #151b28);
  border-radius: 3px;
  overflow: hidden;
}

.drawer-quota-fill {
  height: 100%;
  background: var(--color-primary, #6366f1);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.drawer-quota-fill.warn {
  background: var(--color-warning, #f59e0b);
}

.drawer-quota-fill.danger {
  background: var(--color-danger, #ef4444);
}

.drawer-upgrade-link {
  background: none;
  border: none;
  color: var(--color-accent, #22d3ee);
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
  text-align: left;
  transition: color 0.15s ease;
}

.drawer-upgrade-link:hover {
  color: var(--color-accent-hover, #38bdf8);
  text-decoration: underline;
}

/* ========================================================
   Track P1: Async Processing, Badges & Floating Status Pill
   ======================================================== */

/* Topbar & Drawer Pulsing Badges */
.library-processing-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.35);
  color: #34d399;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 12px;
}

.processing-pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-color: #10b981;
  box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
  animation: pulse-beacon 1.8s infinite cubic-bezier(0.66, 0, 0, 1);
}

@keyframes pulse-beacon {
  0% {
    transform: scale(0.95);
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
  }
  70% {
    transform: scale(1.1);
    box-shadow: 0 0 0 8px rgba(16, 185, 129, 0);
  }
  100% {
    transform: scale(0.95);
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
  }
}

.drawer-processing-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.35);
  color: #34d399;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 12px;
}

.status-spinner-small {
  display: inline-block;
  width: 9px;
  height: 9px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  margin-right: 4px;
  vertical-align: middle;
}

.job-progress-live {
  color: #38bdf8;
  font-size: 0.72rem;
  font-weight: 500;
}

/* Status Card Header & Controls */
.status-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 8px;
}

.status-card-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
  text-align: left;
}

.status-card-title-group h4 {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--text-primary, #f8fafc);
}

.status-card-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-minimize-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #28334a);
  border-radius: 8px;
  color: var(--text-secondary, #94a3b8);
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.card-minimize-btn svg {
  width: 14px;
  height: 14px;
}

.card-minimize-btn:hover {
  color: var(--text-primary, #f8fafc);
  border-color: var(--color-primary, #6366f1);
  background: var(--bg-card, #151b28);
}

.card-dismiss-btn {
  background: transparent;
  border: none;
  color: var(--text-muted, #64748b);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 0.9rem;
  transition: color 0.15s ease;
}

.card-dismiss-btn:hover {
  color: var(--text-primary, #f8fafc);
}

/* Reassuring Notice Box (Ticket P1-1) */
.status-reassure-box {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(34, 211, 238, 0.06) 100%);
  border: 1px solid rgba(99, 102, 241, 0.25);
  border-radius: 12px;
  padding: 14px 18px;
  margin: 18px auto;
  max-width: 640px;
  display: flex;
  align-items: flex-start;
  gap: 14px;
  text-align: left;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.reassure-icon-wrapper {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: rgba(99, 102, 241, 0.18);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 1px;
}

.reassure-icon {
  width: 17px;
  height: 17px;
  color: #818cf8;
}

.reassure-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 0.86rem;
  line-height: 1.45;
}

.reassure-text strong {
  color: var(--text-primary, #f8fafc);
  font-weight: 600;
  font-size: 0.9rem;
}

.reassure-text span {
  color: var(--text-secondary, #94a3b8);
}

.status-card-footer {
  margin-top: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.continue-bg-btn {
  background: rgba(99, 102, 241, 0.1);
  border: 1px solid rgba(139, 92, 246, 0.3);
  color: #c4b5fd;
  padding: 6px 16px;
  border-radius: 20px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.continue-bg-btn:hover {
  background: rgba(99, 102, 241, 0.2);
  color: #ffffff;
  border-color: #a78bfa;
  transform: translateY(-1px);
}

/* Docked Floating Background Processing Pill */
.docked-processing-pill {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 9995;
  max-width: 420px;
  width: calc(100vw - 36px);
  animation: slide-up-pill 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slide-up-pill {
  from {
    transform: translateY(20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

.docked-pill-inner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--bg-card, #151b28);
  border: 1px solid rgba(99, 102, 241, 0.35);
  border-radius: 14px;
  box-shadow: 0 12px 30px -4px rgba(0, 0, 0, 0.5), 0 4px 12px rgba(99, 102, 241, 0.15);
  backdrop-filter: blur(12px);
  cursor: pointer;
  transition: all 0.2s ease;
}

.docked-pill-inner:hover {
  border-color: var(--color-primary, #6366f1);
  transform: translateY(-2px);
}

.docked-spinner {
  width: 22px;
  height: 22px;
  border: 3px solid rgba(99, 102, 241, 0.25);
  border-top-color: #818cf8;
  border-right-color: #22d3ee;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}

.docked-pill-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.docked-pill-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.docked-pill-title {
  font-size: 0.86rem;
  color: var(--text-primary, #f8fafc);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.docked-pill-title strong {
  color: #fff;
}

.docked-live-tag {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  color: #38bdf8;
  background: rgba(56, 189, 248, 0.15);
  padding: 1px 6px;
  border-radius: 10px;
}

.docked-pill-sub {
  font-size: 0.76rem;
  color: var(--text-secondary, #94a3b8);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.docked-expand-btn {
  padding: 4px 10px;
  font-size: 0.78rem;
  font-weight: 600;
  border-radius: 6px;
  background: var(--color-primary, #6366f1);
  color: #ffffff;
  border: none;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.15s ease;
}

.docked-expand-btn:hover {
  background: #4f46e5;
}

.docked-dismiss-btn {
  background: transparent;
  border: none;
  color: var(--text-muted, #64748b);
  cursor: pointer;
  padding: 4px;
  font-size: 0.85rem;
  flex-shrink: 0;
  transition: color 0.15s ease;
}

.docked-dismiss-btn:hover {
  color: var(--text-primary, #f8fafc);
}

/* ========================================================
   Inline Score Library Workspace Grid & Search/Filter Bar
   ======================================================== */
.workspace-library-section {
  margin-top: 28px;
  padding-top: 24px;
  border-top: 1px solid var(--border, #28334a);
}

.workspace-library-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 18px;
}

.workspace-library-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.workspace-library-title {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--text-primary, #f8fafc);
  letter-spacing: -0.01em;
}

.workspace-library-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.drawer-filter-bar {
  padding: 12px 24px;
  border-bottom: 1px solid var(--border, #28334a);
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--bg-surface, var(--bg-secondary));
}

.library-search-box {
  position: relative;
  display: flex;
  align-items: center;
  min-width: 220px;
  flex: 1;
}

.search-icon {
  position: absolute;
  left: 11px;
  width: 15px;
  height: 15px;
  color: var(--text-muted, #64748b);
  pointer-events: none;
}

.library-search-input {
  width: 100%;
  min-height: 38px;
  padding: 6px 30px 6px 34px;
  border-radius: 8px;
  border: 1px solid var(--border, #28334a);
  background: var(--bg-card, #151b28);
  color: var(--text-primary, #f8fafc);
  font-size: 0.85rem;
  outline: none;
  transition: border-color 0.15s ease;
}

.library-search-input:focus {
  border-color: var(--color-primary, #6366f1);
}

.search-clear-btn {
  position: absolute;
  right: 8px;
  background: transparent;
  border: none;
  color: var(--text-muted, #64748b);
  cursor: pointer;
  padding: 4px;
  font-size: 0.78rem;
}

.library-filter-pills {
  display: inline-flex;
  align-items: center;
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  border-radius: 8px;
  padding: 3px;
  gap: 2px;
}

.filter-pill-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary, #94a3b8);
  font-size: 0.78rem;
  font-weight: 600;
  padding: 5px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  min-height: 32px;
}

.filter-pill-btn.active {
  background: var(--color-primary, #6366f1);
  color: #ffffff;
}

.library-sort-select {
  min-height: 38px;
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid var(--border, #28334a);
  background: var(--bg-card, #151b28);
  color: var(--text-primary, #f8fafc);
  font-size: 0.82rem;
  font-weight: 600;
  outline: none;
  cursor: pointer;
}

.workspace-job-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}

.workspace-job-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  background: var(--bg-card, #151b28);
}

.workspace-library-empty {
  text-align: center;
  padding: 40px 20px;
  background: var(--bg-card, #151b28);
  border: 1px dashed var(--border, #28334a);
  border-radius: 12px;
  color: var(--text-secondary, #94a3b8);
}

.workspace-library-empty h4 {
  margin: 0 0 6px 0;
  color: var(--text-primary, #f8fafc);
}

.workspace-library-empty p {
  margin: 0;
  font-size: 0.85rem;
}

/* Responsive Styles for Dashboard (Mobile & Tablet) */
@media (max-width: 768px) {
  .dashboard-topbar {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
    margin-bottom: 14px;
  }

  .topbar-actions {
    width: 100%;
    display: flex;
    gap: 8px;
  }

  .create-score-btn,
  .library-toggle-btn {
    flex: 1;
    justify-content: center;
    min-height: 44px;
    padding: 10px 14px;
  }

  .dropzone {
    padding: 20px 14px;
    min-height: auto;
  }

  .browse-btn {
    min-height: 44px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    max-width: 280px;
  }

  .create-scratch-btn {
    min-height: 42px;
  }

  .demo-scores-bar {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }

  .demo-buttons {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .demo-btn {
    min-height: 44px;
    width: 100%;
    justify-content: center;
  }

  .selected-file-card {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }

  .selected-file-actions {
    width: 100%;
    justify-content: flex-end;
  }

  .selected-file-actions .primary-btn {
    flex: 1;
    min-height: 44px;
  }

  .workspace-library-section {
    margin-top: 4px;
    padding-top: 0;
    border-top: none;
  }

  .workspace-library-header {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }

  .workspace-library-controls {
    width: 100%;
    flex-direction: column;
    align-items: stretch;
  }

  .library-search-box {
    width: 100%;
  }

  .library-search-input {
    min-height: 42px;
    font-size: 16px;
  }

  .library-filter-pills {
    width: 100%;
    display: flex;
  }

  .filter-pill-btn {
    flex: 1;
    min-height: 38px;
  }

  .library-sort-select {
    width: 100%;
    min-height: 42px;
    font-size: 16px;
  }

  .workspace-job-grid {
    grid-template-columns: 1fr;
  }

  .job-chip {
    min-height: 38px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 6px 10px;
  }

  .library-drawer {
    width: 100%;
    max-width: 100%;
    padding-top: var(--sat);
    padding-bottom: calc(var(--sab) + 4.5rem);
  }

  .drawer-filter-bar {
    padding: 10px 16px;
  }

  .job-chip.offline-toggle-chip {
    color: #38bdf8;
    border-color: rgba(56, 189, 248, 0.3);
  }

  .job-chip.offline-toggle-chip.is-saved-offline {
    background: rgba(16, 185, 129, 0.15);
    border-color: #10b981;
    color: #6ee7b7;
  }

  .pipeline-steps {
    flex-direction: column;
    gap: 10px;
    align-items: stretch;
  }

  .result-header {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }

  .result-header .header-actions {
    flex-wrap: wrap;
    gap: 8px;
  }

  .action-btn {
    min-height: 42px;
  }

  .docked-processing-pill {
    left: 12px;
    right: 12px;
    bottom: calc(var(--mobile-bottom-offset, 68px) + 12px);
    width: auto;
    max-width: none;
  }
}

@media (max-width: 480px) {
  .page-title {
    font-size: 1.35rem;
  }

  .format-badges {
    flex-direction: column;
    align-items: stretch;
    width: 100%;
  }

  .format-pill {
    text-align: center;
  }

  .docked-pill-inner {
    padding: 8px 12px;
  }
}
</style>

