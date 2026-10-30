<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch, nextTick } from 'vue'
import type { OpenSheetMusicDisplay } from 'opensheetmusicdisplay'
import {
  ChevronLeft,
  ChevronRight,
  BookOpen,
  Columns,
  Copy,
  Printer,
  Maximize2,
  Minimize2,
  Trash2,
  Sparkles,
  Share2,
  ArrowDown,
  MoreHorizontal,
  ArrowLeft,
  Download,
  FileText,
  Music,
  Eye,
  EyeOff,
  Pencil,
  Check,
  X
} from 'lucide-vue-next'
import { ScorePlaybackController } from '../audio/scorePlayer'
import { preferences } from '../composables/useSettings'
import { useWakeLock } from '../composables/useWakeLock'
import { usePedalNavigation } from '../composables/usePedalNavigation'
import { isMobileImmersiveMode } from '../composables/useNativePlatform'
import AudioPlayerControls from './AudioPlayerControls.vue'
import NotationStudio from './studio/NotationStudio.vue'
import ScoreShareModal from './studio/ScoreShareModal.vue'
import { sanitizeMusicXmlLyrics } from '../utils/musicxmlLyricsSanitizer'
import { updateMusicXmlTitle } from '../utils/musicxmlTitleUpdater'
import { apiFetch } from '../services/apiClient'

const props = defineProps<{
  musicXml: string
  jobId?: string
  hasOriginalSource?: boolean
  scoreTitle?: string
  scoreComposer?: string
  pageCount?: number
  partCount?: number
  showBackButton?: boolean
}>()

const emit = defineEmits<{
  (e: 'cleanup'): void
  (e: 'back'): void
  (e: 'exportPdf'): void
  (e: 'exportMidi'): void
  (e: 'exportXml'): void
  (e: 'update:musicXml', xml: string): void
  (e: 'update:scoreTitle', title: string): void
}>()

const wrapperRef = ref<HTMLDivElement | null>(null)
const containerRef = ref<HTMLDivElement | null>(null)
const isLoading = ref(true)
const errorMessage = ref<string | null>(null)

// Responsive initial zoom & viewMode
const isMobileViewport = ref(typeof window !== 'undefined' && window.innerWidth <= 768)
const computeInitialZoom = () => {
  if (isMobileViewport.value) {
    if (preferences.value.defaultZoom && preferences.value.defaultZoom !== 100) {
      return (preferences.value.defaultZoom / 100) * 0.78
    }
    return 0.78
  }
  return (preferences.value.defaultZoom || 100) / 100
}
const zoomLevel = ref<number>(computeInitialZoom())
const isFullscreen = ref<boolean>(false)
const isStageHudHidden = ref<boolean>(false)
const copySuccess = ref(false)
const isExportMenuOpen = ref(false)

// Pagination & View Mode
const viewMode = ref<'paginated' | 'continuous'>(isMobileViewport.value ? 'continuous' : 'paginated')
const currentPage = ref<number>(1)
const totalPages = ref<number>(1)

// Score Editor & Studio State
const isStudioMode = defineModel<boolean>('isStudioMode', { default: false })
const isShareModalOpen = ref<boolean>(false)
const isMobileActionsOpen = ref<boolean>(false)


let osmd: OpenSheetMusicDisplay | null = null
const player = new ScorePlaybackController()
const playbackSnapshot = ref(player.getSnapshot())
let unsubscribeMeasure: (() => void) | null = null
let unsubscribeState: (() => void) | null = null

if (preferences.value.defaultInstrument && preferences.value.defaultInstrument !== 'piano') {
  player.setInstrument(preferences.value.defaultInstrument)
}
if (preferences.value.defaultBpm) {
  player.setBpm(preferences.value.defaultBpm)
}

const { requestWakeLock } = useWakeLock()

const isDualPageSpread = ref(false)

const toggleDualPageSpread = () => {
  isDualPageSpread.value = !isDualPageSpread.value
  applyPageVisibility()
}

const applyPageVisibility = () => {
  if (!containerRef.value) return

  const pageDivs = containerRef.value.querySelectorAll('[id^="osmdCanvasPage"]')
  if (pageDivs.length === 0) return

  if (viewMode.value === 'continuous') {
    containerRef.value.classList.remove('dual-page-layout')
    pageDivs.forEach((p) => {
      (p as HTMLElement).style.display = 'block'
      ;(p as HTMLElement).style.marginBottom = '24px'
      ;(p as HTMLElement).style.maxWidth = '100%'
    })
    setupTitleCanvasInteraction()
    return
  }

  // Paginated Mode: Single Page vs Dual-Page Spread
  if (isDualPageSpread.value && totalPages.value > 1) {
    containerRef.value.classList.add('dual-page-layout')
    pageDivs.forEach((p, idx) => {
      const pageNum = idx + 1
      if (pageNum === currentPage.value || pageNum === currentPage.value + 1) {
        ;(p as HTMLElement).style.display = 'inline-block'
        ;(p as HTMLElement).style.margin = '0 8px'
        ;(p as HTMLElement).style.verticalAlign = 'top'
        ;(p as HTMLElement).style.maxWidth = 'calc(50% - 20px)'
      } else {
        ;(p as HTMLElement).style.display = 'none'
      }
    })
  } else {
    containerRef.value.classList.remove('dual-page-layout')
    pageDivs.forEach((p, idx) => {
      const pageNum = idx + 1
      if (pageNum === currentPage.value) {
        ;(p as HTMLElement).style.display = 'block'
        ;(p as HTMLElement).style.margin = '0 auto'
        ;(p as HTMLElement).style.marginBottom = '0'
        ;(p as HTMLElement).style.maxWidth = '100%'
      } else {
        ;(p as HTMLElement).style.display = 'none'
      }
    })
  }
  setupTitleCanvasInteraction()
}
// Score Title Renaming & Syncing State
const localScoreTitle = ref(props.scoreTitle || '')
watch(() => props.scoreTitle, (newVal) => {
  if (newVal) {
    localScoreTitle.value = newVal
  }
})

const isEditingTitle = ref(false)
const titleInput = ref('')
const titleInputRef = ref<HTMLInputElement | null>(null)

const startEditTitle = () => {
  titleInput.value = localScoreTitle.value || props.scoreTitle || 'Score'
  isEditingTitle.value = true
  nextTick(() => {
    titleInputRef.value?.focus()
    titleInputRef.value?.select()
  })
}

const cancelEditTitle = () => {
  isEditingTitle.value = false
}

const commitEditTitle = async () => {
  const newTitle = titleInput.value.trim()
  if (!newTitle || newTitle === localScoreTitle.value) {
    isEditingTitle.value = false
    return
  }
  isEditingTitle.value = false
  localScoreTitle.value = newTitle

  // 1. Update MusicXML with the new title
  const updatedXml = updateMusicXmlTitle(props.musicXml, newTitle)
  emit('update:musicXml', updatedXml)
  emit('update:scoreTitle', newTitle)

  // 2. Re-render OSMD with updated XML so the big letters update immediately
  if (osmd) {
    try {
      await osmd.load(updatedXml)
      osmd.render()
      applyPageVisibility()
    } catch (e) {
      console.warn('Failed to re-render OSMD after title update:', e)
    }
  }

  // 3. Persist to backend if jobId is present
  if (props.jobId && !props.jobId.startsWith('sample-') && !props.jobId.startsWith('custom-')) {
    try {
      await apiFetch(`/api/jobs/${props.jobId}/rename`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle }),
      })
    } catch (err) {
      console.error('Failed to persist renamed title to backend:', err)
    }
  }
}

const setupTitleCanvasInteraction = () => {
  if (!containerRef.value) return
  const textNodes = Array.from(containerRef.value.querySelectorAll('svg text'))
  for (const node of textNodes) {
    const text = node.textContent?.trim()
    if (!text) continue
    const fontSize = parseFloat(window.getComputedStyle(node).fontSize || '0')
    const matchesTitle = text === localScoreTitle.value || text === props.scoreTitle
    const isLargeHeader = fontSize >= 16

    if (matchesTitle || isLargeHeader) {
      node.classList.add('osmd-clickable-title')
      node.setAttribute('title', 'Click to rename score')
      ;(node as HTMLElement).style.cursor = 'pointer'
      ;(node as HTMLElement).onclick = (e) => {
        e.stopPropagation()
        startEditTitle()
      }
      break
    }
  }
}

const setPage = (pageNum: number) => {
  const clamped = Math.max(1, Math.min(totalPages.value, pageNum))
  if (currentPage.value === clamped) return
  currentPage.value = clamped
  applyPageVisibility()
}

const nextPage = () => {
  const step = isDualPageSpread.value && totalPages.value > 1 ? 2 : 1
  setPage(currentPage.value + step)
}

const prevPage = () => {
  const step = isDualPageSpread.value && totalPages.value > 1 ? 2 : 1
  setPage(currentPage.value - step)
}

usePedalNavigation(nextPage, prevPage)

const toggleViewMode = () => {
  viewMode.value = viewMode.value === 'paginated' ? 'continuous' : 'paginated'
  if (osmd) {
    osmd.setOptions({
      pageFormat: viewMode.value === 'paginated' ? 'A4_P' : 'Endless',
      followCursor: false
    })
    osmd.render()
    const detectedPages = (osmd as any).GraphicSheet?.MusicPages?.length || 1
    totalPages.value = Math.max(1, detectedPages)
    applyPageVisibility()
  }
}

const renderScore = async () => {
  if (!containerRef.value || !props.musicXml) return
  isLoading.value = true
  errorMessage.value = null

  try {
    let cleanXml = sanitizeMusicXmlLyrics(props.musicXml.trim())
    if (!cleanXml.startsWith('<?xml')) {
      cleanXml = '<?xml version="1.0" encoding="utf-8"?>\n' + cleanXml
    }

    if (osmd) {
      osmd.clear()
    } else {
      const { OpenSheetMusicDisplay: OSMDClass } = await import('opensheetmusicdisplay')
      osmd = new OSMDClass(containerRef.value, {
        autoResize: true,
        backend: 'svg',
        drawTitle: true,
        drawSubtitle: true,
        drawComposer: true,
        drawingParameters: isMobileViewport.value ? 'compact' : 'default',
        pageFormat: viewMode.value === 'paginated' ? 'A4_P' : 'Endless',
        followCursor: false, // Avoid competing unthrottled window scrolling
        autoBeam: true,
        autoBeamOptions: {
          beam_rests: false,
          beam_middle_rests_only: false,
          maintain_stem_directions: false
        }
      })

      // Anti-collision engraving rules for lyrics & measure spacing
      osmd.EngravingRules.MaximumLyricsElongationFactor = 4.5
      osmd.EngravingRules.HorizontalBetweenLyricsDistance = 0.5
      osmd.EngravingRules.BetweenSyllableMinimumDistance = 0.8
      osmd.EngravingRules.LyricsXPaddingFactorForLongLyrics = 1.3
      osmd.EngravingRules.LyricsUseXPaddingForLongLyrics = true
      osmd.EngravingRules.LyricsXPaddingForLastNoteInMeasure = true
      osmd.EngravingRules.LyricOverlapAllowedIntoNextMeasure = 1.0
      osmd.EngravingRules.VoiceSpacingMultiplierVexflow = 0.95

      if (isMobileViewport.value) {
        osmd.EngravingRules.SheetTitleHeight = 2.2
        osmd.EngravingRules.SheetSubtitleHeight = 1.3
        osmd.EngravingRules.CompactMode = true
        osmd.EngravingRules.LyricsHeight = 1.6
      }
    }

    await osmd.load(cleanXml)
    osmd.zoom = zoomLevel.value
    osmd.render()

    const detectedPages = (osmd as any).GraphicSheet?.MusicPages?.length || 1
    totalPages.value = Math.max(1, detectedPages)
    if (currentPage.value > totalPages.value) {
      currentPage.value = 1
    }
    applyPageVisibility()

    // Initialize playback timeline
    try {
      player.loadScore(osmd)
      let effectiveTitle = props.scoreTitle
      if (!effectiveTitle || effectiveTitle === 'NoteSight Score') {
        const match = cleanXml.match(/<(work-title|movement-title)[^>]*>([^<]+)<\/(work-title|movement-title)>/i)
        if (match && match[2].trim()) {
          effectiveTitle = match[2].trim()
        }
      }
      const finalTitle = effectiveTitle || player.getScoreTitle()
      if (finalTitle && finalTitle !== 'score') {
        player.setScoreMetadata(finalTitle, props.scoreComposer)
      }
      requestWakeLock()
    } catch (audioErr) {
      console.warn('Audio timeline playback initialization warning:', audioErr)
    }
  } catch (err: any) {
    console.error('Failed to render MusicXML:', err)
    const detail = err?.message ? ` (${err.message})` : ''
    errorMessage.value = `Failed to render sheet music notation${detail}.`
  } finally {
    isLoading.value = false
  }
}

const setZoom = (factor: number) => {
  zoomLevel.value = Math.max(0.4, Math.min(2.0, Math.round(factor * 10) / 10))
  if (osmd) {
    osmd.zoom = zoomLevel.value
    osmd.render()
    applyPageVisibility()
  }
}

const zoomIn = () => setZoom(zoomLevel.value + 0.1)
const zoomOut = () => setZoom(zoomLevel.value - 0.1)
const resetZoom = () => setZoom(computeInitialZoom())

const toggleFullscreen = async () => {
  if (!wrapperRef.value) return
  try {
    if (!document.fullscreenElement) {
      await wrapperRef.value.requestFullscreen()
      isFullscreen.value = true
    } else {
      await document.exitFullscreen()
      isFullscreen.value = false
    }
  } catch (err) {
    console.warn('Fullscreen request failed:', err)
  }
}

const onFullscreenChange = () => {
  isFullscreen.value = !!document.fullscreenElement
  if (!isFullscreen.value) {
    isStageHudHidden.value = false
  }
}

const printScore = () => {
  window.print()
}

const copyMusicXml = async () => {
  if (!props.musicXml) return
  try {
    await navigator.clipboard.writeText(props.musicXml)
    copySuccess.value = true
    setTimeout(() => { copySuccess.value = false }, 2500)
  } catch (err) {
    console.error('Clipboard copy failed:', err)
  }
}

// Click on measure to activate Notation Studio, or tap left/right edges / center HUD in Stage Mode
const handleContainerClick = (event: MouseEvent) => {
  if (containerRef.value && (isFullscreen.value || viewMode.value === 'paginated')) {
    const rect = containerRef.value.getBoundingClientRect()
    const clickX = event.clientX - rect.left
    if (viewMode.value === 'paginated' && totalPages.value > 1) {
      if (clickX < rect.width * 0.18) {
        prevPage()
        return
      } else if (clickX > rect.width * 0.82) {
        nextPage()
        return
      }
    }
    if (isFullscreen.value) {
      isStageHudHidden.value = !isStageHudHidden.value
      return
    }
  }

  const target = event.target as Element | null
  if (!target) return
  const measureEl = target.closest('.vf-measure')
  if (measureEl && !isMobileViewport.value) {
    isStudioMode.value = true
  }
}

// Touch Gestures: Pinch-to-Zoom and Paginated Swipe Page Turning
let initialPinchDistance = 0
let initialZoom = 1.0
let pendingZoom = 1.0
let isPinching = false
let touchStartX = 0
let touchStartY = 0
let touchStartTime = 0

const handleTouchStart = (e: TouchEvent) => {
  if (e.touches.length === 2) {
    const t1 = e.touches[0]
    const t2 = e.touches[1]
    initialPinchDistance = Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY)
    initialZoom = zoomLevel.value
    pendingZoom = zoomLevel.value
    isPinching = true
  } else if (e.touches.length === 1) {
    touchStartX = e.touches[0].clientX
    touchStartY = e.touches[0].clientY
    touchStartTime = Date.now()
  }
}

const handleTouchMove = (e: TouchEvent) => {
  if (e.touches.length === 2 && initialPinchDistance > 0 && containerRef.value) {
    e.preventDefault()
    const t1 = e.touches[0]
    const t2 = e.touches[1]
    const currentDist = Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY)
    const factor = currentDist / initialPinchDistance
    pendingZoom = Math.max(0.5, Math.min(2.0, Math.round(initialZoom * factor * 20) / 20))
    const visualScale = pendingZoom / initialZoom
    containerRef.value.style.transformOrigin = 'center top'
    containerRef.value.style.transform = `scale(${visualScale})`
  }
}

const handleTouchEnd = (e: TouchEvent) => {
  if (isPinching && e.touches.length < 2) {
    isPinching = false
    initialPinchDistance = 0
    if (containerRef.value) {
      containerRef.value.style.transform = ''
      containerRef.value.style.transformOrigin = ''
    }
    if (osmd && pendingZoom !== zoomLevel.value) {
      zoomLevel.value = pendingZoom
      osmd.zoom = pendingZoom
      osmd.render()
      applyPageVisibility()
    }
    return
  }

  if (e.changedTouches.length === 1 && !isPinching && initialPinchDistance === 0) {
    const touch = e.changedTouches[0]
    const deltaX = touch.clientX - touchStartX
    const deltaY = touch.clientY - touchStartY
    const deltaTime = Date.now() - touchStartTime

    // Horizontal swipe gesture for page turning ONLY in paginated mode when not zoomed-in
    if (
      viewMode.value === 'paginated' &&
      zoomLevel.value <= 1.05 &&
      deltaTime < 350 &&
      Math.abs(deltaX) > 65 &&
      Math.abs(deltaY) < 40
    ) {
      if (deltaX < 0) {
        nextPage()
      } else {
        prevPage()
      }
      return
    }
  }
  if (e.touches.length < 2) {
    initialPinchDistance = 0
    isPinching = false
  }
}

// User scroll detection: pauses auto-scroll when user manually navigates away
const checkCursorVisibilityAndSuspend = () => {
  try {
    const cursorEl = (osmd as any)?.cursor?.cursorElement
    if (!cursorEl) return
    const rect = cursorEl.getBoundingClientRect()
    // Ignore invalid/collapsed cursor during layout transitions or when on hidden page
    if (rect.width === 0 || rect.height === 0) return

    const vh = window.innerHeight || document.documentElement.clientHeight
    const stickyOffset = isMobileViewport.value ? 60 : 160

    // If cursor is within comfortable reading viewport
    if (rect.top >= stickyOffset && rect.bottom <= vh * 0.82) {
      if (player.isAutoScrollSuspended()) {
        player.resumeAutoScroll()
      }
    } else {
      // User scrolled away so cursor is out of view
      player.suspendAutoScrollByUser()
    }
  } catch {}
}

const handleUserScroll = () => {
  if (player.isCurrentlyProgrammaticScrolling()) return
  if (player.getSnapshot().status !== 'playing' || !player.getSnapshot().autoScrollEnabled) return

  checkCursorVisibilityAndSuspend()
}

const handleWindowScroll = () => {
  if (player.isCurrentlyProgrammaticScrolling()) return
  if (player.getSnapshot().status !== 'playing' || !player.getSnapshot().autoScrollEnabled) return

  checkCursorVisibilityAndSuspend()
}

const handleKeyNavigation = (e: KeyboardEvent) => {
  if (player.getSnapshot().status !== 'playing' || !player.getSnapshot().autoScrollEnabled) return
  const scrollKeys = ['PageUp', 'PageDown', 'Home', 'End', 'ArrowUp', 'ArrowDown']
  if (scrollKeys.includes(e.code) && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) {
    player.suspendAutoScrollByUser()
  }
}

const handleXmlUpdated = (newXml: string) => {
  emit('update:musicXml', newXml)
  renderScore()
}

watch(isStudioMode, (newVal) => {
  if (!newVal) {
    nextTick(() => {
      osmd = null
      renderScore()
    })
  }
})

onMounted(() => {
  isMobileImmersiveMode.value = true
  window.dispatchEvent(new CustomEvent('notesight:score-state', { detail: { hasScore: true } }))

  unsubscribeState = player.onStateChange((snapshot) => {
    playbackSnapshot.value = snapshot
  })

  document.addEventListener('fullscreenchange', onFullscreenChange)
  window.addEventListener('wheel', handleUserScroll, { passive: true })
  window.addEventListener('touchmove', handleUserScroll, { passive: true })
  window.addEventListener('scroll', handleWindowScroll, { passive: true })
  window.addEventListener('keydown', handleKeyNavigation)

  // Listen to playback measure transitions to auto-flip pages in paginated mode
  unsubscribeMeasure = player.onMeasureChange((measureNumber) => {
    if (viewMode.value !== 'paginated' || !osmd) return
    try {
      const gMeasure = (osmd as any).GraphicSheet?.MeasureList?.[measureNumber - 1]?.[0]
      const targetPage = gMeasure?.ParentMusicSystem?.Parent?.PageNumber
      if (typeof targetPage === 'number' && targetPage > 0) {
        const isVisible = isDualPageSpread.value && totalPages.value > 1
          ? (targetPage === currentPage.value || targetPage === currentPage.value + 1)
          : targetPage === currentPage.value

        if (!isVisible) {
          setPage(targetPage)
          if (containerRef.value) {
            player.setProgrammaticScrolling(900)
            const stickyHeaderOffset = isMobileViewport.value ? 60 : 160
            const containerTop = containerRef.value.getBoundingClientRect().top + (window.scrollY || window.pageYOffset || 0)
            window.scrollTo({ top: Math.max(0, containerTop - stickyHeaderOffset), behavior: 'smooth' })
          }
        }
      }
    } catch {}
  })

  renderScore()
})

watch(() => props.musicXml, () => {
  renderScore()
})

watch(() => preferences.value.defaultZoom, (newZoom) => {
  if (isMobileViewport.value) {
    setZoom((newZoom / 100) * 0.78)
  } else {
    setZoom(newZoom / 100)
  }
})

watch(() => preferences.value.defaultInstrument, (newInst) => {
  player.setInstrument(newInst)
})

watch(() => preferences.value.defaultBpm, (newBpm) => {
  player.setBpm(newBpm)
})

onUnmounted(() => {
  isMobileImmersiveMode.value = false
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  window.removeEventListener('wheel', handleUserScroll)
  window.removeEventListener('touchmove', handleUserScroll)
  window.removeEventListener('scroll', handleWindowScroll)
  window.removeEventListener('keydown', handleKeyNavigation)
  if (unsubscribeState) {
    unsubscribeState()
    unsubscribeState = null
  }
  if (unsubscribeMeasure) {
    unsubscribeMeasure()
    unsubscribeMeasure = null
  }
  player.destroy()
  if (containerRef.value) {
    containerRef.value.innerHTML = ''
  }
  osmd = null
})
</script>

<template>
  <div
    ref="wrapperRef"
    class="score-viewer-wrapper"
    :class="{
      'is-fullscreen': isFullscreen,
      'is-hud-hidden': isStageHudHidden,
      'in-studio-mode': isStudioMode
    }"
  >
    <div v-if="isLoading" class="score-loading">
      <div class="spinner"></div>
      <p>{{ $t('scoreViewer.loading') }}</p>
    </div>

    <div v-if="errorMessage" class="score-error">
      <p>{{ errorMessage }}</p>
      <button class="retry-render-btn" @click="renderScore">
        {{ $t('scoreViewer.retryRender') }}
      </button>
    </div>

    <!-- Floating HUD Restore Pill (Visible when Stage HUD is auto-hidden) -->
    <Transition name="fade-pill">
      <button
        v-if="isStageHudHidden && !isStudioMode"
        type="button"
        class="restore-hud-pill"
        @click="isStageHudHidden = false"
        :title="$t('scoreViewer.showControls')"
      >
        <Eye :size="15" />
        <span>{{ $t('scoreViewer.showControls') }}</span>
      </button>
    </Transition>

    <!-- Unified Reader & Performance Toolbar -->
    <div
      v-if="!isLoading && !errorMessage && !isStudioMode && !isStageHudHidden"
      class="score-toolbar"
    >
      <!-- Left: Back Navigation, Score Title & View Controls -->
      <div class="toolbar-left-group">
        <!-- Back to Library Button -->
        <button
          v-if="showBackButton"
          type="button"
          class="tool-btn back-library-btn"
          @click="emit('back')"
          :title="$t('dashboard.backToDashboard')"
        >
          <ArrowLeft :size="16" />
          <span class="back-btn-label">{{ $t('dashboard.scoreLibrary') }}</span>
        </button>

        <!-- Contextual Score Title & Metadata -->
        <div v-if="localScoreTitle || scoreTitle" class="toolbar-score-identity">
          <div v-if="!isEditingTitle" class="title-display-wrap">
            <span
              class="toolbar-score-title clickable"
              :title="`Click to rename (${localScoreTitle || scoreTitle})`"
              @click="startEditTitle"
            >
              {{ localScoreTitle || scoreTitle }}
            </span>
            <button
              class="rename-pencil-btn"
              type="button"
              @click="startEditTitle"
              title="Rename score"
            >
              <Pencil :size="12" />
            </button>
          </div>
          <div v-else class="title-edit-wrap">
            <input
              ref="titleInputRef"
              v-model="titleInput"
              class="toolbar-title-input"
              @keydown.enter="commitEditTitle"
              @keydown.esc="cancelEditTitle"
              placeholder="Score title"
            />
            <button class="rename-save-btn" type="button" @click="commitEditTitle" title="Save title">
              <Check :size="13" />
            </button>
            <button class="rename-cancel-btn" type="button" @click="cancelEditTitle" title="Cancel">
              <X :size="13" />
            </button>
          </div>
          <div v-if="(pageCount && pageCount > 1) || (partCount && partCount > 1)" class="toolbar-score-badges">
            <span v-if="pageCount && pageCount > 1" class="meta-mini-badge">{{ pageCount }}p</span>
            <span v-if="partCount && partCount > 1" class="meta-mini-badge accent">{{ $t('scoreViewer.partsCount', { count: partCount }) }}</span>
          </div>
        </div>

        <!-- Zoom Controls (Desktop & Tablet inline, Mobile inside More sheet) -->
        <div class="toolbar-group zoom-group desktop-zoom-group">
          <button class="tool-btn icon-only-btn" @click="zoomOut" :disabled="zoomLevel <= 0.4" title="Zoom Out (-10%)">
            <svg class="tool-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
          </button>
          <button class="zoom-display-btn" @click="resetZoom" title="Reset Zoom">
            {{ Math.round(zoomLevel * 100) }}%
          </button>
          <button class="tool-btn icon-only-btn" @click="zoomIn" :disabled="zoomLevel >= 2.0" title="Zoom In (+10%)">
            <svg class="tool-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
          </button>
        </div>

        <!-- View Mode (Paginated vs Continuous) -->
        <div class="toolbar-group view-mode-group">
          <button
            class="tool-btn with-text view-mode-btn"
            :class="{ active: viewMode === 'paginated' }"
            @click="toggleViewMode"
            :title="viewMode === 'paginated' ? 'Switch to Continuous Vertical Scroll' : 'Switch to Clean Page-by-Page View'"
          >
            <BookOpen v-if="viewMode === 'paginated'" :size="15" />
            <Columns v-else :size="15" />
            <span class="view-mode-label">{{ viewMode === 'paginated' ? $t('scoreViewer.pageView') : $t('scoreViewer.continuous') }}</span>
          </button>

          <!-- Pagination Turn Controls (Active in Paginated Mode) -->
          <div v-if="viewMode === 'paginated'" class="page-nav-group">
            <button
              class="tool-btn page-arrow-btn"
              @click="prevPage"
              :disabled="currentPage <= 1"
              title="Previous Page"
            >
              <ChevronLeft :size="15" />
            </button>
            <span class="page-indicator">
              <template v-if="isDualPageSpread && totalPages > 1">
                {{ currentPage }}–{{ Math.min(totalPages, currentPage + 1) }}/{{ totalPages }}
              </template>
              <template v-else>
                {{ currentPage }}/{{ totalPages }}
              </template>
            </span>
            <button
              class="tool-btn page-arrow-btn"
              @click="nextPage"
              :disabled="currentPage >= totalPages"
              title="Next Page"
            >
              <ChevronRight :size="15" />
            </button>
            <button
              v-if="totalPages > 1"
              class="tool-btn page-arrow-btn spread-toggle-btn desktop-only-btn"
              :class="{ active: isDualPageSpread }"
              @click="toggleDualPageSpread"
              :title="isDualPageSpread ? 'Switch to Single Page' : 'Switch to 2-Page Book Spread'"
            >
              <Columns :size="14" />
            </button>
          </div>
        </div>
      </div>

      <!-- Right: Edit Score, Export, Stage Mode, Cleanup -->
      <div class="toolbar-group action-group">
        <!-- Notation Studio Button -->
        <button
          class="tool-btn with-text studio-mode-btn"
          @click="isStudioMode = !isStudioMode"
          :class="{ active: isStudioMode }"
          :title="isStudioMode ? 'Switch to reading view' : 'Open Notation Studio'"
        >
          <Sparkles :size="15" />
          <span class="studio-btn-label">{{ isStudioMode ? $t('scoreViewer.readingView') : $t('scoreViewer.notationStudio') }}</span>
        </button>

        <!-- Desktop Action Buttons (Visible > 768px) -->
        <div class="desktop-action-buttons">
          <!-- Unified Export Dropdown -->
          <div class="export-dropdown-wrapper">
            <button
              type="button"
              class="tool-btn with-text"
              :class="{ active: isExportMenuOpen }"
              @click="isExportMenuOpen = !isExportMenuOpen"
              :title="$t('studio.header.export')"
            >
              <Download :size="14" />
              <span>{{ $t('studio.header.export') }}</span>
            </button>
            <div v-if="isExportMenuOpen" class="desktop-export-menu">
              <button v-if="jobId" class="mobile-dropdown-item" @click="emit('exportPdf'); isExportMenuOpen = false">
                <FileText :size="14" />
                <span>{{ $t('dashboard.exportPdf') }}</span>
              </button>
              <button v-if="jobId" class="mobile-dropdown-item" @click="emit('exportMidi'); isExportMenuOpen = false">
                <Music :size="14" />
                <span>{{ $t('dashboard.exportMidi') }}</span>
              </button>
              <button class="mobile-dropdown-item" @click="emit('exportXml'); isExportMenuOpen = false">
                <Download :size="14" />
                <span>{{ $t('dashboard.exportMusicXml') }}</span>
              </button>
              <button class="mobile-dropdown-item" @click="copyMusicXml(); isExportMenuOpen = false">
                <Copy :size="14" />
                <span>{{ copySuccess ? $t('scoreViewer.copied') : $t('scoreViewer.copyXml') }}</span>
              </button>
              <button class="mobile-dropdown-item" @click="printScore(); isExportMenuOpen = false">
                <Printer :size="14" />
                <span>{{ $t('scoreViewer.print') }}</span>
              </button>
            </div>
          </div>

          <!-- Public Share & Community Hub Modal -->
          <button
            v-if="jobId && !jobId.startsWith('sample-')"
            class="tool-btn with-text share-score-btn"
            @click="isShareModalOpen = true"
            :title="$t('scoreViewer.share')"
          >
            <Share2 :size="14" />
            <span>{{ $t('scoreViewer.share') }}</span>
          </button>

          <button
            v-if="isFullscreen"
            class="tool-btn with-text"
            @click="isStageHudHidden = true"
            :title="$t('scoreViewer.hideHud')"
          >
            <EyeOff :size="14" />
            <span>{{ $t('scoreViewer.hideHud') }}</span>
          </button>

          <button class="tool-btn with-text stage-mode-btn" @click="toggleFullscreen" :title="isFullscreen ? $t('scoreViewer.exitStage') : $t('scoreViewer.stageMode')">
            <Minimize2 v-if="isFullscreen" :size="14" />
            <Maximize2 v-else :size="14" />
            <span>{{ isFullscreen ? $t('scoreViewer.exitStage') : $t('scoreViewer.stageMode') }}</span>
          </button>

          <button class="tool-btn icon-only-btn danger-tool-btn" @click="emit('cleanup')" :title="$t('scoreViewer.cleanUp')">
            <Trash2 :size="14" />
          </button>
        </div>

        <!-- Mobile More Actions Sheet Trigger (Visible <= 768px) -->
        <div class="mobile-overflow-wrapper">
          <button
            class="tool-btn mobile-more-btn"
            :class="{ active: isMobileActionsOpen }"
            @click="isMobileActionsOpen = !isMobileActionsOpen"
            title="Score options & exports"
            aria-label="More score actions"
          >
            <MoreHorizontal :size="18" />
          </button>

          <div v-if="isMobileActionsOpen" class="mobile-actions-backdrop" @click="isMobileActionsOpen = false"></div>
          <div v-if="isMobileActionsOpen" class="mobile-actions-dropdown">
            <div class="mobile-sheet-header">
              <span class="mobile-sheet-title">{{ scoreTitle || 'Score Options' }}</span>
              <span class="mobile-sheet-zoom">Zoom: {{ Math.round(zoomLevel * 100) }}%</span>
            </div>

            <!-- Mobile Zoom Stepper Row -->
            <div class="mobile-zoom-row">
              <button class="mobile-zoom-btn" @click="zoomOut" :disabled="zoomLevel <= 0.4">− Zoom Out</button>
              <button class="mobile-zoom-btn" @click="resetZoom">{{ $t('common.reset') }}</button>
              <button class="mobile-zoom-btn" @click="zoomIn" :disabled="zoomLevel >= 2.0">+ Zoom In</button>
            </div>

            <button v-if="jobId" class="mobile-dropdown-item" @click="emit('exportPdf'); isMobileActionsOpen = false">
              <FileText :size="16" />
              <span>{{ $t('dashboard.exportPdf') }}</span>
            </button>
            <button v-if="jobId" class="mobile-dropdown-item" @click="emit('exportMidi'); isMobileActionsOpen = false">
              <Music :size="16" />
              <span>{{ $t('dashboard.exportMidi') }}</span>
            </button>
            <button class="mobile-dropdown-item" @click="emit('exportXml'); isMobileActionsOpen = false">
              <Download :size="16" />
              <span>{{ $t('dashboard.exportMusicXml') }}</span>
            </button>
            <button class="mobile-dropdown-item" @click="copyMusicXml(); isMobileActionsOpen = false">
              <Copy :size="16" />
              <span>{{ copySuccess ? $t('scoreViewer.copied') : $t('scoreViewer.copyXml') }}</span>
            </button>
            <button class="mobile-dropdown-item" @click="printScore(); isMobileActionsOpen = false">
              <Printer :size="16" />
              <span>{{ $t('scoreViewer.print') }}</span>
            </button>
            <button
              v-if="jobId && !jobId.startsWith('sample-')"
              class="mobile-dropdown-item"
              @click="isShareModalOpen = true; isMobileActionsOpen = false"
            >
              <Share2 :size="16" />
              <span>{{ $t('scoreViewer.share') }}</span>
            </button>
            <button class="mobile-dropdown-item" @click="isStageHudHidden = true; isMobileActionsOpen = false">
              <EyeOff :size="16" />
              <span>{{ $t('scoreViewer.hideHud') }}</span>
            </button>
            <button class="mobile-dropdown-item" @click="toggleFullscreen(); isMobileActionsOpen = false">
              <Maximize2 :size="16" />
              <span>{{ isFullscreen ? $t('scoreViewer.exitStage') : $t('scoreViewer.stageMode') }}</span>
            </button>
            <button class="mobile-dropdown-item danger-item" @click="emit('cleanup'); isMobileActionsOpen = false">
              <Trash2 :size="16" />
              <span>{{ $t('scoreViewer.cleanUp') }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Notation Studio Workbench (When Active) -->
    <div v-if="isStudioMode" class="studio-embedded-container">
      <NotationStudio
        :music-xml="musicXml"
        :job-id="jobId"
        :score-title="localScoreTitle || scoreTitle"
        :has-original-source="hasOriginalSource"
        @update:music-xml="handleXmlUpdated"
        @exit-studio="isStudioMode = false"
      />
    </div>

    <template v-else>
      <!-- Unified Interactive Audio Playback Transport (Sticky Top on Desktop, Floating Bottom Dock on Mobile) -->
      <AudioPlayerControls
        v-if="!isLoading && !errorMessage && !isStageHudHidden"
        :player="player"
      />

      <!-- Floating Resume Auto-Scroll Pill -->
      <Transition name="fade-pill">
        <button
          v-if="!isLoading && !errorMessage && playbackSnapshot.status === 'playing' && playbackSnapshot.autoScrollEnabled && playbackSnapshot.autoScrollSuspended"
          type="button"
          class="autoscroll-resume-pill"
          @click="player.resumeAutoScroll()"
          :title="$t('player.resumeAutoScroll')"
        >
          <ArrowDown :size="15" class="resume-icon" />
          <span>{{ $t('player.resumeAutoScroll') }}</span>
        </button>
      </Transition>

      <!-- Score Notation Canvas -->
      <div
        class="score-container"
        :class="{ 'is-paginated': viewMode === 'paginated' }"
        @click="handleContainerClick"
        @touchstart="handleTouchStart"
        @touchmove="handleTouchMove"
        @touchend="handleTouchEnd"
        title="Click on any measure to open Notation Studio"
      >
        <div ref="containerRef" class="score-sheet-inner"></div>
      </div>
    </template>

    <!-- Score Share Modal -->
    <ScoreShareModal
      v-if="jobId && !jobId.startsWith('sample-')"
      :is-open="isShareModalOpen"
      :job-id="jobId"
      @close="isShareModalOpen = false"
    />
  </div>
</template>

<style scoped>
.score-viewer-wrapper {
  background: var(--bg-card, #ffffff);
  border: 1px solid var(--border, #e6e2d8);
  border-radius: 12px;
  box-shadow: var(--shadow-md, 0 4px 20px rgba(0, 0, 0, 0.08));
  padding: 14px 16px;
  margin-top: 8px;
  min-height: 400px;
  position: relative;
  transition: all 0.25s ease;
}

.score-viewer-wrapper.in-studio-mode {
  padding: 0;
  margin-top: 0;
  border: none;
  background: transparent;
  box-shadow: none;
  border-radius: 0;
}

.score-viewer-wrapper.is-fullscreen {
  border-radius: 0;
  padding: 16px;
  min-height: 100vh;
  border: none;
  background: var(--bg-canvas);
}

.restore-hud-pill {
  position: fixed;
  top: calc(12px + var(--sat, 0px));
  right: 16px;
  z-index: 9500;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--bg-glass-heavy);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 9999px;
  padding: 8px 14px;
  min-height: 40px;
  font-size: 0.8rem;
  font-weight: 600;
  box-shadow: var(--shadow-md);
  backdrop-filter: blur(12px);
  cursor: pointer;
}

.score-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #28334a);
  border-radius: 10px;
  margin-bottom: 10px;
}

.toolbar-left-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  min-width: 0;
}

.back-library-btn {
  font-weight: 600;
  color: var(--text-primary);
}

.toolbar-score-identity {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding-right: 6px;
  border-right: 1px solid var(--border);
}

.toolbar-score-title {
  font-size: 0.92rem;
  font-weight: 700;
  color: var(--text-primary);
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.title-display-wrap {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.toolbar-score-title.clickable {
  cursor: pointer;
  transition: color 0.15s ease;
}

.toolbar-score-title.clickable:hover {
  color: var(--color-primary, #6366f1);
}

.rename-pencil-btn {
  background: transparent;
  border: none;
  color: var(--text-muted, #94a3b8);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 4px;
  border-radius: 4px;
  transition: all 0.15s ease;
  opacity: 0.7;
}

.rename-pencil-btn:hover {
  color: var(--color-primary, #818cf8);
  background: rgba(255, 255, 255, 0.08);
  opacity: 1;
}

.title-edit-wrap {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.toolbar-title-input {
  background: var(--input-bg, #0b0f19);
  border: 1px solid var(--color-primary, #6366f1);
  color: #ffffff;
  border-radius: 4px;
  font-size: 0.88rem;
  font-weight: 600;
  padding: 2px 8px;
  height: 28px;
  width: 170px;
  outline: none;
}

.rename-save-btn,
.rename-cancel-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  padding: 0;
  transition: all 0.15s ease;
}

.rename-save-btn {
  color: var(--color-success, #10b981);
}

.rename-save-btn:hover {
  background: rgba(16, 185, 129, 0.15);
}

.rename-cancel-btn {
  color: var(--text-muted, #94a3b8);
}

.rename-cancel-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #ffffff;
}

:deep(.osmd-clickable-title) {
  cursor: pointer !important;
  transition: opacity 0.15s ease, filter 0.15s ease;
}

:deep(.osmd-clickable-title:hover) {
  opacity: 0.75 !important;
  filter: drop-shadow(0 2px 4px rgba(99, 102, 241, 0.4));
}

.toolbar-score-badges {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.meta-mini-badge {
  font-size: 0.7rem;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 9999px;
  background: var(--bg-card);
  color: var(--text-secondary);
  border: 1px solid var(--border);
}

.meta-mini-badge.accent {
  background: var(--color-primary-light);
  color: var(--color-primary);
  border-color: transparent;
}

.toolbar-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  color: var(--text-primary, #f8fafc);
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.18s ease;
  min-height: 40px;
}

.tool-btn.icon-only-btn {
  padding: 6px 10px;
  min-width: 40px;
}

.tool-btn:hover:not(:disabled) {
  background: var(--color-primary-light, rgba(99, 102, 241, 0.15));
  border-color: var(--color-primary, #6366f1);
  color: var(--color-primary, #6366f1);
}

.tool-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.tool-icon {
  width: 14px;
  height: 14px;
}

.zoom-display-btn {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  color: var(--text-primary, #f8fafc);
  padding: 6px 10px;
  border-radius: 8px;
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
  min-width: 54px;
  min-height: 40px;
  text-align: center;
}

.zoom-display-btn:hover {
  border-color: var(--color-primary, #6366f1);
}

.page-nav-group {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  border-radius: 8px;
  padding: 0 2px;
}

.page-arrow-btn {
  border: none;
  background: none;
  padding: 6px 8px;
  min-width: 38px;
  min-height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.page-indicator {
  font-size: 0.76rem;
  font-weight: 600;
  color: var(--text-primary, #f8fafc);
  padding: 0 4px;
  font-family: var(--font-mono, monospace);
}

.studio-mode-btn {
  background: var(--color-primary-light);
  border-color: var(--color-primary);
  color: var(--color-primary);
  font-weight: 600;
}

.studio-mode-btn:hover,
.studio-mode-btn.active {
  background: var(--color-primary);
  color: #ffffff;
}

.studio-embedded-container {
  margin-top: 0;
  width: 100%;
}

.stage-mode-btn {
  background: linear-gradient(135deg, var(--color-primary, #6366f1) 0%, var(--color-accent, #22d3ee) 100%);
  color: #ffffff;
  border: none;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.25);
}

.stage-mode-btn:hover:not(:disabled) {
  opacity: 0.92;
  color: #ffffff;
}

.danger-tool-btn:hover:not(:disabled) {
  border-color: var(--color-danger, #ef4444) !important;
  color: var(--color-danger, #ef4444) !important;
  background: var(--color-danger-light, rgba(239, 68, 68, 0.12)) !important;
}

.export-dropdown-wrapper {
  position: relative;
}

.desktop-export-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 150;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 6px;
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 210px;
}

.score-container {
  width: 100%;
  max-width: 100%;
  overflow-x: hidden;
  -webkit-overflow-scrolling: touch;
  min-height: 380px;
  margin-top: 10px;
  cursor: pointer;
  background: var(--score-paper-bg, #ffffff);
  border: 1px solid var(--score-paper-border, #e2e8f0);
  border-radius: 8px;
  padding: 16px 20px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.12);
  box-sizing: border-box;
}

.score-sheet-inner {
  width: 100%;
  min-width: 0;
  display: block;
}

.autoscroll-resume-pill {
  position: fixed;
  bottom: 24px;
  right: 28px;
  z-index: 8900;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--color-primary, #6366f1);
  color: #ffffff;
  border: 1px solid rgba(255, 255, 255, 0.25);
  border-radius: 9999px;
  padding: 10px 18px;
  min-height: 44px;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4), 0 2px 8px rgba(0, 0, 0, 0.15);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  user-select: none;
}

.autoscroll-resume-pill:hover {
  transform: translateY(-2px);
  background: var(--color-primary-hover, #4f46e5);
}

.resume-icon {
  animation: bounce-subtle 1.8s infinite ease-in-out;
}

@keyframes bounce-subtle {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(3px);
  }
}

.fade-pill-enter-active,
.fade-pill-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}

.fade-pill-enter-from,
.fade-pill-leave-to {
  opacity: 0;
  transform: translateY(12px) scale(0.95);
}

.score-container :deep(div[id^="osmdCanvasPage"]) {
  background: var(--score-paper-bg, #ffffff);
  border-radius: 4px;
  max-width: 100%;
  overflow-x: visible;
  margin: 0 auto;
}

.score-container :deep(svg) {
  background: var(--score-paper-bg, #ffffff);
  display: block;
  max-width: 100% !important;
  height: auto !important;
  margin: 0 auto;
}

.desktop-action-buttons {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.mobile-overflow-wrapper {
  display: none;
  position: relative;
}

.mobile-more-btn {
  width: 44px;
  height: 44px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.mobile-actions-backdrop {
  position: fixed;
  inset: 0;
  z-index: 9400;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(2px);
}

.mobile-actions-dropdown {
  position: fixed;
  left: 12px;
  right: 12px;
  bottom: calc(max(var(--sab, 0px), 12px) + 74px);
  z-index: 9500;
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  border-radius: 16px;
  padding: 12px;
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: calc(100dvh - 110px);
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

.mobile-sheet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px 10px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 4px;
}

.mobile-sheet-title {
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-sheet-zoom {
  font-size: 0.78rem;
  font-family: var(--font-mono);
  color: var(--color-primary);
  font-weight: 600;
}

.mobile-zoom-row {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 6px;
  margin-bottom: 6px;
}

.mobile-zoom-btn {
  min-height: 44px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--bg-subtle);
  color: var(--text-primary);
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
}

.mobile-dropdown-item {
  display: flex;
  align-items: center;
  gap: 10px;
  background: transparent;
  border: none;
  color: var(--text-primary, #f8fafc);
  font-size: 0.88rem;
  font-weight: 500;
  padding: 10px 12px;
  min-height: 44px;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}

.mobile-dropdown-item:hover {
  background: var(--bg-subtle, #1c2336);
  color: var(--color-primary, #818cf8);
}

.mobile-dropdown-item.danger-item {
  color: var(--color-danger, #ef4444);
}

.mobile-dropdown-item.danger-item:hover {
  background: var(--color-danger-light, rgba(239, 68, 68, 0.15));
}

.score-container.is-paginated {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.score-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px;
  color: var(--text-secondary, #585d6e);
}

.spinner {
  width: 36px;
  height: 36px;
  border: 4px solid var(--border, #e6e2d8);
  border-top-color: var(--color-primary, #4f46e5);
  border-right-color: var(--color-accent, #06b6d4);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: 12px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.score-error {
  color: var(--color-danger, #ef4444);
  text-align: center;
  padding: 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.retry-render-btn {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--color-primary, #6366f1);
  color: var(--color-primary, #6366f1);
  padding: 8px 16px;
  min-height: 44px;
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.retry-render-btn:hover {
  background: var(--color-primary, #6366f1);
  color: #ffffff;
}

.spread-toggle-btn.active {
  background: var(--color-primary-light) !important;
  color: var(--color-primary) !important;
  border-color: var(--color-primary) !important;
}

:deep(.dual-page-layout) {
  display: flex !important;
  flex-direction: row !important;
  justify-content: center !important;
  align-items: flex-start !important;
  gap: 16px !important;
  width: 100% !important;
  overflow-x: auto !important;
}

:deep(.dual-page-layout svg) {
  max-width: 100% !important;
  height: auto !important;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
  border-radius: 4px;
}

/* Responsive Score Reader (Mobile & Tablet <= 768px) */
@media (max-width: 768px) {
  .score-viewer-wrapper {
    padding: 0 0 calc(78px + var(--sab, 0px)) 0;
    border-radius: 0;
    border: none;
    box-shadow: none;
    margin-top: 0;
    min-height: 100vh;
    background: var(--bg-canvas);
  }

  .score-toolbar {
    position: sticky;
    top: 0;
    z-index: 120;
    flex-direction: row;
    flex-wrap: nowrap;
    justify-content: space-between;
    align-items: center;
    gap: 6px;
    padding: calc(6px + var(--sat, 0px)) 10px 6px;
    margin-bottom: 0;
    border-radius: 0;
    border-top: none;
    border-left: none;
    border-right: none;
    background: var(--bg-glass-heavy);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
  }

  .toolbar-left-group {
    flex: 1;
    flex-wrap: nowrap;
    justify-content: flex-start;
    gap: 6px;
    min-width: 0;
  }

  .back-btn-label,
  .toolbar-score-badges,
  .desktop-zoom-group,
  .desktop-only-btn,
  .view-mode-label {
    display: none !important;
  }

  .toolbar-score-identity {
    border-right: none;
    padding-right: 2px;
    flex: 1;
    min-width: 0;
  }

  .toolbar-score-title {
    font-size: 0.88rem;
    max-width: 100%;
  }

  .action-group {
    justify-content: flex-end;
    width: auto;
    gap: 6px;
    flex-shrink: 0;
  }

  .desktop-action-buttons {
    display: none !important;
  }

  .mobile-overflow-wrapper {
    display: block;
  }

  .tool-btn {
    padding: 0 10px;
    min-height: 42px;
    min-width: 42px;
    font-size: 0.78rem;
  }

  .studio-btn-label {
    font-size: 0.76rem;
  }

  .score-container {
    padding: 8px 4px 24px;
    margin-top: 0;
    border-radius: 0;
    border-left: none;
    border-right: none;
    overflow-x: auto;
  }

  .score-sheet-inner {
    min-width: 0;
    width: 100%;
  }

  .autoscroll-resume-pill {
    bottom: calc(76px + max(var(--sab, 0px), 8px));
    right: 14px;
    padding: 8px 14px;
    font-size: 0.8rem;
  }
}

@media (max-width: 420px) {
  .studio-btn-label {
    display: none;
  }
}

/* Direct Print Format Stylesheet */
@media print {
  .score-viewer-wrapper {
    box-shadow: none !important;
    border: none !important;
    padding: 0 !important;
    margin: 0 !important;
    width: 100% !important;
    background: white !important;
  }
  .score-toolbar,
  :deep(.audio-player-controls) {
    display: none !important;
  }
}
</style>
