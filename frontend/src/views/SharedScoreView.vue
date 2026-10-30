<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { OpenSheetMusicDisplay } from 'opensheetmusicdisplay'
import { ScorePlaybackController } from '../audio/scorePlayer'
import AudioPlayerControls from '../components/AudioPlayerControls.vue'
import { sanitizeMusicXmlLyrics } from '../utils/musicxmlLyricsSanitizer'
import {
  Music2,
  GitFork,
  Code,
  Eye,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Minimize2,
  BookOpen,
  Columns,
  Check,
  Copy,
  X
} from 'lucide-vue-next'
import { showToast } from '../composables/useToast'

const route = useRoute()
const router = useRouter()
const token = route.params.token as string

const isLoading = ref(true)
const errorMessage = ref<string | null>(null)
const scoreData = ref<{
  share_token: string
  title: string
  author_name: string
  musicxml: string
  allow_playback: boolean
  allow_fork: boolean
  view_count: number
  created_at: string
} | null>(null)

const containerRef = ref<HTMLDivElement | null>(null)
const zoomLevel = ref(1.0)
const viewMode = ref<'continuous' | 'paginated'>('continuous')
const isFullscreen = ref(false)
const isEmbedModalOpen = ref(false)
const hasCopiedEmbed = ref(false)
const isForking = ref(false)

let osmd: OpenSheetMusicDisplay | null = null
const player = new ScorePlaybackController()

const fetchSharedScore = async () => {
  isLoading.value = true
  errorMessage.value = null
  try {
    const res = await fetch(`/api/scores/share/${token}`)
    if (!res.ok) {
      if (res.status === 410) {
        throw new Error('This shared score link has expired.')
      }
      throw new Error('Shared score not found or link has been revoked.')
    }
    scoreData.value = await res.json()
    if (scoreData.value) {
      const pageTitle = `${scoreData.value.title} | NoteSight Sheet Music`
      const pageDesc = `View and play ${scoreData.value.title}${scoreData.value.author_name ? ` by ${scoreData.value.author_name}` : ''} interactively in NoteSight.`
      document.title = pageTitle
      const metaDesc = document.querySelector('meta[name="description"]')
      if (metaDesc) metaDesc.setAttribute('content', pageDesc)
      const ogTitle = document.querySelector('meta[property="og:title"]')
      if (ogTitle) ogTitle.setAttribute('content', pageTitle)
      const ogDesc = document.querySelector('meta[property="og:description"]')
      if (ogDesc) ogDesc.setAttribute('content', pageDesc)
      const twTitle = document.querySelector('meta[name="twitter:title"]')
      if (twTitle) twTitle.setAttribute('content', pageTitle)
      const twDesc = document.querySelector('meta[name="twitter:description"]')
      if (twDesc) twDesc.setAttribute('content', pageDesc)
    }
    isLoading.value = false
    await nextTick()
    await renderScore()
  } catch (err: any) {
    errorMessage.value = err.message || 'Failed to load shared score.'
  } finally {
    if (isLoading.value) {
      isLoading.value = false
    }
  }
}

const renderScore = async () => {
  if (!containerRef.value) {
    await nextTick()
  }
  if (!containerRef.value || !scoreData.value?.musicxml) return
  try {
    let cleanXml = sanitizeMusicXmlLyrics(scoreData.value.musicxml.trim())
    if (!cleanXml.startsWith('<?xml')) {
      cleanXml = '<?xml version="1.0" encoding="utf-8"?>\n' + cleanXml
    }

    containerRef.value.innerHTML = ''
    const { OpenSheetMusicDisplay: OSMDClass } = await import('opensheetmusicdisplay')
    osmd = new OSMDClass(containerRef.value, {
      autoResize: true,
      backend: 'svg',
      drawTitle: true,
      drawSubtitle: true,
      drawComposer: true,
      drawLyricist: false,
      drawPartNames: true,
      drawingParameters: viewMode.value === 'paginated' ? 'compact' : 'default',
      pageFormat: viewMode.value === 'paginated' ? 'A4_P' : 'Endless',
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
    osmd.EngravingRules.LyricsHeight = 1.6

    osmd.zoom = zoomLevel.value
    await osmd.load(cleanXml)
    osmd.render()

    if (scoreData.value.allow_playback) {
      player.loadScore(osmd)
      if (scoreData.value.title) {
        player.setScoreMetadata(scoreData.value.title, scoreData.value.author_name)
      }
    }
  } catch (err: any) {
    console.error('Failed to render OSMD sheet:', err)
    errorMessage.value = err?.message ? `Failed to render sheet music: ${err.message}` : 'Failed to render sheet music notation.'
  }
}

const toggleViewMode = () => {
  viewMode.value = viewMode.value === 'continuous' ? 'paginated' : 'continuous'
  renderScore()
}

const zoomIn = () => {
  zoomLevel.value = Math.min(2.0, zoomLevel.value + 0.1)
  if (osmd) {
    osmd.zoom = zoomLevel.value
    osmd.render()
  }
}

const zoomOut = () => {
  zoomLevel.value = Math.max(0.5, zoomLevel.value - 0.1)
  if (osmd) {
    osmd.zoom = zoomLevel.value
    osmd.render()
  }
}

const toggleFullscreen = () => {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen().then(() => {
      isFullscreen.value = true
    })
  } else {
    document.exitFullscreen().then(() => {
      isFullscreen.value = false
    })
  }
}

const handleFork = async () => {
  const authToken = localStorage.getItem('token')
  if (!authToken) {
    showToast({
      title: 'Sign In Required',
      message: 'Please sign in or create an account to clone this score to your library.',
      type: 'info',
    })
    router.push({ name: 'Login', query: { redirect: route.fullPath } })
    return
  }

  isForking.value = true
  try {
    const res = await fetch(`/api/scores/share/${token}/fork`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${authToken}`,
      },
    })

    if (res.ok) {
      await res.json()
      showToast({
        title: 'Score Forked!',
        message: 'Successfully cloned into your Score Library.',
        type: 'success',
      })
      router.push({ name: 'Dashboard' })
    } else {
      const errData = await res.json().catch(() => ({}))
      showToast({
        title: 'Fork Failed',
        message: errData.detail || 'Could not fork score.',
        type: 'error',
      })
    }
  } catch (err) {
    console.error('Fork request error:', err)
  } finally {
    isForking.value = false
  }
}

const embedCode = computed(() => {
  const embedUrl = `${window.location.origin}/score/embed/${token}`
  return `<iframe src="${embedUrl}" width="100%" height="600" frameborder="0" allow="autoplay; fullscreen" loading="lazy"></iframe>`
})

const copyEmbed = async () => {
  await navigator.clipboard.writeText(embedCode.value)
  hasCopiedEmbed.value = true
  showToast({
    title: 'Copied',
    message: 'Embed snippet copied to clipboard.',
    type: 'success',
  })
  setTimeout(() => {
    hasCopiedEmbed.value = false
  }, 2500)
}

onMounted(() => {
  fetchSharedScore()
})

onUnmounted(() => {
  player.stop()
  if (osmd) {
    osmd.clear()
    osmd = null
  }
})
</script>

<template>
  <div class="shared-score-layout">
    <!-- Top Bar -->
    <header class="shared-header">
      <div class="header-left">
        <router-link to="/" class="brand-link">
          <div class="brand-icon">
            <Music2 :size="18" class="text-indigo-400" />
          </div>
          <span class="brand-title">NoteSight</span>
        </router-link>

        <div class="divider"></div>

        <div class="score-meta-block">
          <h1 class="score-title">{{ scoreData?.title || 'Shared Score' }}</h1>
          <div class="score-byline">
            <span class="author-tag">{{ $t('share.byAuthor', { author: scoreData?.author_name || 'Musician' }) }}</span>
            <span class="dot-separator">•</span>
            <span class="views-tag">
              <Eye :size="12" />
              <span>{{ $t('share.viewsCount', { count: scoreData?.view_count || 1 }) }}</span>
            </span>
          </div>
        </div>
      </div>

      <div class="header-right">
        <!-- Zoom Controls -->
        <div class="btn-group">
          <button class="tool-btn" @click="zoomOut" title="Zoom Out">
            <ZoomOut :size="15" />
          </button>
          <span class="zoom-display">{{ Math.round(zoomLevel * 100) }}%</span>
          <button class="tool-btn" @click="zoomIn" title="Zoom In">
            <ZoomIn :size="15" />
          </button>
        </div>

        <!-- View Mode Toggle -->
        <button class="tool-btn with-text" @click="toggleViewMode" title="Toggle pagination mode">
          <Columns v-if="viewMode === 'paginated'" :size="15" />
          <BookOpen v-else :size="15" />
          <span>{{ viewMode === 'paginated' ? $t('scoreViewer.continuous') : $t('scoreViewer.pageView') }}</span>
        </button>

        <!-- Embed Button -->
        <button class="tool-btn with-text" @click="isEmbedModalOpen = true" title="Get embed snippet">
          <Code :size="15" />
          <span>{{ $t('share.embedScore') }}</span>
        </button>

        <!-- Fullscreen -->
        <button class="tool-btn" @click="toggleFullscreen" title="Fullscreen">
          <Minimize2 v-if="isFullscreen" :size="15" />
          <Maximize2 v-else :size="15" />
        </button>

        <!-- Fork Button -->
        <button
          v-if="scoreData?.allow_fork"
          class="primary-btn fork-btn"
          :disabled="isForking"
          @click="handleFork"
          title="Clone this score into your library"
        >
          <GitFork :size="15" />
          <span>{{ isForking ? $t('share.cloning') : $t('share.forkScore') }}</span>
        </button>
      </div>
    </header>

    <!-- Main Canvas Area -->
    <main class="score-stage">
      <div v-if="isLoading" class="loading-state">
        <div class="spinner"></div>
        <p>{{ $t('share.loadingSharedScore') }}</p>
      </div>

      <div v-else-if="errorMessage" class="error-state">
        <h3>{{ $t('share.unableToLoadScore') }}</h3>
        <p>{{ errorMessage }}</p>
        <router-link to="/" class="primary-btn back-btn">{{ $t('share.returnToNoteSight') }}</router-link>
      </div>

      <div v-else class="stage-content">
        <!-- Interactive Transport (Sticky when playback permitted) -->
        <div v-if="scoreData?.allow_playback" class="playback-toolbar-container">
          <AudioPlayerControls :player="player" />
        </div>

        <div class="canvas-viewport">
          <div ref="containerRef" class="osmd-sheet-container"></div>
        </div>
      </div>
    </main>

    <!-- Embed Modal -->
    <div v-if="isEmbedModalOpen" class="modal-backdrop" @click.self="isEmbedModalOpen = false">
      <div class="modal-dialog">
        <div class="modal-dialog-header">
          <h3>{{ $t('share.embedScore') }}</h3>
          <button class="close-btn" @click="isEmbedModalOpen = false"><X :size="16" /></button>
        </div>
        <div class="modal-dialog-body">
          <p class="dialog-desc">{{ $t('share.embedDesc') }}</p>
          <textarea readonly :value="embedCode" rows="3" class="embed-code-box"></textarea>
          <button class="copy-dialog-btn" @click="copyEmbed">
            <Check v-if="hasCopiedEmbed" :size="14" class="text-emerald-400" />
            <Copy v-else :size="14" />
            <span>{{ hasCopiedEmbed ? $t('share.copied') : $t('share.copyEmbed') }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.shared-score-layout {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--bg-canvas);
  color: var(--text-primary);
}

.shared-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1.5rem;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 40;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.brand-link {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  text-decoration: none;
  color: var(--text-primary);
}

.brand-icon {
  width: 2rem;
  height: 2rem;
  border-radius: 0.375rem;
  background: var(--color-primary-light);
  display: flex;
  align-items: center;
  justify-content: center;
}

.brand-title {
  font-weight: 700;
  font-size: 1rem;
}

.divider {
  width: 1px;
  height: 1.5rem;
  background: var(--border);
}

.score-title {
  font-size: 1.05rem;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary);
}

.score-byline {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
  margin-top: 0.1rem;
}

.views-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.btn-group {
  display: flex;
  align-items: center;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: 0.375rem;
  overflow: hidden;
}

.tool-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  padding: 0.45rem 0.65rem;
  min-height: 40px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.8rem;
  transition: all 0.15s;
}

.tool-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.tool-btn.with-text {
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: 0.375rem;
}

.zoom-display {
  font-size: 0.75rem;
  color: var(--text-secondary);
  padding: 0 0.4rem;
  font-family: monospace;
}

.primary-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  background: var(--color-primary);
  color: white;
  border: none;
  border-radius: 0.375rem;
  padding: 0.45rem 0.85rem;
  min-height: 40px;
  font-size: 0.825rem;
  font-weight: 500;
  cursor: pointer;
  text-decoration: none;
}

.fork-btn {
  background: var(--color-success);
}

.fork-btn:hover:not(:disabled) {
  opacity: 0.9;
}

.score-stage {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.loading-state, .error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 6rem 2rem;
  text-align: center;
}

.spinner {
  width: 2.5rem;
  height: 2.5rem;
  border: 3px solid var(--color-primary-light);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 1rem;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.stage-content {
  display: flex;
  flex-direction: column;
  flex: 1;
}

.playback-toolbar-container {
  padding: 0.75rem 1.5rem;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
}

.canvas-viewport {
  flex: 1;
  display: flex;
  justify-content: center;
  padding: 2rem;
  overflow-y: auto;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.osmd-sheet-container {
  background: var(--score-paper-bg, #ffffff);
  border-radius: 0.5rem;
  padding: 2rem;
  box-shadow: var(--shadow-lg);
  width: 100%;
  max-width: 960px;
  min-height: 600px;
}

@media (max-width: 768px) {
  .canvas-viewport {
    padding: 0.5rem 0.25rem 5rem;
  }

  .osmd-sheet-container {
    padding: 0.75rem 0.35rem;
    min-width: 0;
  }
}

.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal-dialog {
  background: #1e293b;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 0.75rem;
  width: 100%;
  max-width: 480px;
  overflow: hidden;
}

.modal-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.modal-dialog-header h3 {
  margin: 0;
  font-size: 1rem;
  color: #f8fafc;
}

.modal-dialog-body {
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.dialog-desc {
  font-size: 0.85rem;
  color: #94a3b8;
  margin: 0;
}

.embed-code-box {
  background: #0f172a;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #e2e8f0;
  border-radius: 0.375rem;
  font-family: monospace;
  font-size: 0.75rem;
  padding: 0.5rem;
  outline: none;
  resize: none;
}

.copy-dialog-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  background: #6366f1;
  color: white;
  border: none;
  border-radius: 0.375rem;
  padding: 0.5rem;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
}
</style>
