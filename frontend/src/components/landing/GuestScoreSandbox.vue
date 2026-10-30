<script setup lang="ts">
import { ref, shallowRef, defineAsyncComponent, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import type { OpenSheetMusicDisplay } from 'opensheetmusicdisplay'
import type { ScorePlaybackController as ScorePlaybackControllerType } from '../../audio/scorePlayer'
import { showToast } from '../../composables/useToast'
import { t } from '../../i18n'

const AudioPlayerControls = defineAsyncComponent(() => import('../AudioPlayerControls.vue'))

import {
  Music,
  CheckCircle2,
  AlertCircle,
  Sparkles,
  RefreshCw,
  ArrowRight,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Minimize2,
  Columns,
  BookOpen
} from 'lucide-vue-next'

const router = useRouter()

const isProcessing = ref(false)
const uploadProgressText = ref('')
const errorMessage = ref<string | null>(null)
const multiPageWarning = ref<string | null>(null)

// Current loaded score
const activeScore = ref<{
  id: string
  title: string
  isSample: boolean
  guestToken?: string
  pageCount?: number
} | null>(null)

const currentXmlContent = ref<string>('')
const containerRef = ref<HTMLDivElement | null>(null)
const zoomLevel = ref(1.0)
const viewMode = ref<'continuous' | 'paginated'>('continuous')
const isFullscreen = ref(false)

let osmd: OpenSheetMusicDisplay | null = null
const player = shallowRef<ScorePlaybackControllerType | null>(null)
let pollTimer: number | null = null

const ensurePlayer = async (): Promise<ScorePlaybackControllerType> => {
  if (!player.value) {
    const { ScorePlaybackController } = await import('../../audio/scorePlayer')
    player.value = new ScorePlaybackController()
  }
  return player.value
}


const SAMPLES = [
  {
    id: 'bach',
    title: 'J. S. Bach: Prelude in C Major',
    path: '/samples/bach_prelude.musicxml',
    badge: 'Polyphonic Keyboard'
  },
  {
    id: 'beethoven',
    title: 'L. v. Beethoven: Ode to Joy',
    path: '/samples/beethoven_ode_to_joy.musicxml',
    badge: 'Melody & Harmony'
  },
  {
    id: 'staff',
    title: 'Simple Staff Exercise',
    path: '/samples/simple_staff.musicxml',
    badge: 'Single Voice'
  }
]

const loadSampleScore = async (sample: typeof SAMPLES[0]) => {
  errorMessage.value = null
  multiPageWarning.value = null
  isProcessing.value = true
  uploadProgressText.value = `Loading ${sample.title}...`

  try {
    const res = await fetch(sample.path)
    if (!res.ok) throw new Error('Could not load sample file.')
    const xml = await res.text()

    activeScore.value = {
      id: `sample-${sample.id}`,
      title: sample.title,
      isSample: true,
      pageCount: 1
    }

    isProcessing.value = false
    await nextTick()
    await renderMusicXml(xml, sample.title)
  } catch (err: any) {
    isProcessing.value = false
    errorMessage.value = err.message || 'Failed to load sample score.'
  }
}

const renderMusicXml = async (rawXml: string, scoreTitle: string) => {
  currentXmlContent.value = rawXml
  if (!containerRef.value) {
    await nextTick()
  }
  if (!containerRef.value) return

  try {
    const { sanitizeMusicXmlLyrics } = await import('../../utils/musicxmlLyricsSanitizer')
    let cleanXml = sanitizeMusicXmlLyrics(rawXml.trim())
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
      autoBeam: true
    })

    // Anti-collision engraving rules
    osmd.EngravingRules.MaximumLyricsElongationFactor = 4.0
    osmd.EngravingRules.HorizontalBetweenLyricsDistance = 0.5
    osmd.EngravingRules.BetweenSyllableMinimumDistance = 0.8
    osmd.EngravingRules.LyricsHeight = 1.6

    osmd.zoom = zoomLevel.value
    await osmd.load(cleanXml)
    osmd.render()

    const activePlayer = await ensurePlayer()
    activePlayer.loadScore(osmd)
    activePlayer.setScoreMetadata(scoreTitle, 'NoteSight Demo')
  } catch (err: any) {
    console.error('OSMD rendering error:', err)
    errorMessage.value = `Failed to render notation: ${err?.message || 'Invalid MusicXML'}`
  }
}

const resetSandbox = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  if (player.value) {
    player.value.stop()
  }
  if (osmd) {
    osmd.clear()
    osmd = null
  }
  activeScore.value = null
  errorMessage.value = null
  multiPageWarning.value = null
  isProcessing.value = false
}

const handleSaveScoreToAccount = () => {
  if (activeScore.value && !activeScore.value.isSample && activeScore.value.guestToken) {
    sessionStorage.setItem(
      'pendingGuestScore',
      JSON.stringify({
        jobId: activeScore.value.id,
        guestToken: activeScore.value.guestToken,
        title: activeScore.value.title
      })
    )
  }
  showToast({
    title: t('landing.readyToSaveTitle'),
    message: t('landing.readyToSaveMsg'),
    type: 'info'
  })
  router.push({ name: 'Register' })
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

const toggleViewMode = () => {
  viewMode.value = viewMode.value === 'continuous' ? 'paginated' : 'continuous'
  if (currentXmlContent.value && activeScore.value) {
    renderMusicXml(currentXmlContent.value, activeScore.value.title)
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

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  if (player.value) {
    player.value.stop()
  }
  if (osmd) {
    osmd.clear()
    osmd = null
  }
})
</script>

<template>
  <div class="sandbox-container" id="sandbox">
    <!-- Header / Banner -->
    <div class="sandbox-header">
      <div class="sandbox-badge">
        <Sparkles :size="15" class="text-indigo-400" />
        <span>{{ t('landing.sandboxBadge') }}</span>
      </div>
      <h2 class="sandbox-title">{{ t('landing.sandboxTitle') }}</h2>
      <p class="sandbox-subtitle">
        {{ t('landing.sandboxSubtitle') }}
      </p>
    </div>

    <!-- Error Alert -->
    <div v-if="errorMessage" class="sandbox-alert error">
      <AlertCircle :size="18" />
      <span>{{ errorMessage }}</span>
      <button class="alert-close-btn" @click="errorMessage = null">✕</button>
    </div>

    <!-- Multi-page Warning Modal / Alert -->
    <div v-if="multiPageWarning" class="sandbox-alert warning">
      <AlertCircle :size="18" />
      <div class="warning-content">
        <strong>{{ t('landing.ceilingTitle') }}</strong>
        <p>{{ multiPageWarning }}</p>
      </div>
      <router-link to="/register" class="signup-pill-btn">
        <span>{{ t('landing.createFreeAccount') }}</span>
        <ArrowRight :size="14" />
      </router-link>
      <button class="alert-close-btn" @click="multiPageWarning = null">✕</button>
    </div>

    <!-- State 1: Interactive Samples & Registration Callout -->
    <div v-if="!activeScore && !isProcessing" class="demo-showcase-wrapper">
      <!-- Quick 1-Click Samples -->
      <div class="sample-scores-section">
        <span class="sample-intro">{{ t('landing.samplePrompt') }}</span>
        <div class="sample-pills-row">
          <button
            v-for="sample in SAMPLES"
            :key="sample.id"
            class="sample-pill-btn"
            @click="loadSampleScore(sample)"
          >
            <Music :size="15" class="text-indigo-400" />
            <span class="sample-name">{{ sample.title }}</span>
            <span class="sample-badge">{{ sample.badge }}</span>
          </button>
        </div>
      </div>

      <!-- Registration CTA Card -->
      <div class="register-prompt-card">
        <div class="prompt-icon-circle">
          <Sparkles :size="24" class="text-indigo-400" />
        </div>
        <div class="prompt-content">
          <h3 class="prompt-main-text">{{ t('landing.ctaTitle') }}</h3>
          <p class="prompt-sub-text">{{ t('landing.ctaSubtitle') }}</p>
        </div>
        <router-link to="/register" class="prompt-register-btn">
          <span>{{ t('landing.createFreeAccount') }}</span>
          <ArrowRight :size="16" />
        </router-link>
      </div>
    </div>

    <!-- State 2: Processing Progress -->
    <div v-else-if="isProcessing" class="processing-state-card">
      <div class="spinner-large"></div>
      <h3>{{ uploadProgressText || t('landing.transcribingText') }}</h3>
      <p class="processing-hint">
        {{ t('landing.processingDesc') }}
      </p>
      <div class="progress-bar-track">
        <div class="progress-bar-indeterminate"></div>
      </div>
    </div>

    <!-- State 3: Interactive Score Viewer & Audio Player -->
    <div v-else class="score-display-card">
      <!-- Toolbar Header -->
      <div class="viewer-top-toolbar">
        <div class="score-meta">
          <span class="score-name">{{ activeScore?.title }}</span>
          <span class="sandbox-tag">{{ t('landing.guestTag') }}</span>
        </div>

        <div class="viewer-actions">
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

          <!-- View Mode -->
          <button class="tool-btn with-text" @click="toggleViewMode" title="Toggle pagination">
            <Columns v-if="viewMode === 'paginated'" :size="15" />
            <BookOpen v-else :size="15" />
            <span>{{ viewMode === 'paginated' ? 'Continuous' : 'Page View' }}</span>
          </button>

          <!-- Fullscreen -->
          <button class="tool-btn" @click="toggleFullscreen" title="Fullscreen">
            <Minimize2 v-if="isFullscreen" :size="15" />
            <Maximize2 v-else :size="15" />
          </button>

          <!-- Reset / Try Another -->
          <button class="tool-btn reset-btn" @click="resetSandbox" title="Try another score">
            <RefreshCw :size="14" />
            <span>{{ t('landing.tryAnother') }}</span>
          </button>
        </div>
      </div>

      <!-- Playback Transport Controls -->
      <div v-if="player" class="playback-controls-container">
        <AudioPlayerControls :player="player" />
      </div>

      <!-- Notation Viewport -->
      <div class="notation-viewport">
        <div ref="containerRef" class="osmd-sheet-surface"></div>
      </div>

      <!-- Sandbox Limitations & Conversion Callout Banner -->
      <div class="conversion-banner">
        <div class="banner-text-group">
          <div class="banner-title-row">
            <CheckCircle2 :size="18" class="text-emerald-400" />
            <strong>{{ t('landing.bannerTitle') }}</strong>
          </div>
          <p class="banner-desc">
            {{ t('landing.bannerDesc') }}
          </p>
        </div>

        <button class="primary-claim-btn" @click="handleSaveScoreToAccount">
          <span>{{ t('landing.claimBtn') }}</span>
          <ArrowRight :size="16" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sandbox-container {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 1040px;
  margin: 0 auto;
  padding: 1.5rem 1rem 3rem;
}

.sandbox-header {
  text-align: center;
  margin-bottom: 2rem;
}

.sandbox-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: rgba(99, 102, 241, 0.12);
  color: #818cf8;
  padding: 0.35rem 0.85rem;
  border-radius: 9999px;
  font-size: 0.8rem;
  font-weight: 600;
  margin-bottom: 0.85rem;
  border: 1px solid rgba(99, 102, 241, 0.25);
}

.sandbox-title {
  font-size: 1.85rem;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 0.5rem;
  letter-spacing: -0.02em;
}

.sandbox-subtitle {
  font-size: 1rem;
  color: var(--text-secondary);
  max-width: 650px;
  margin: 0 auto;
  line-height: 1.5;
}

.sandbox-alert {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.85rem 1.25rem;
  border-radius: 0.5rem;
  margin-bottom: 1.5rem;
  font-size: 0.9rem;
}

.sandbox-alert.error {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #f87171;
}

.sandbox-alert.warning {
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.35);
  color: #fbbf24;
  justify-content: space-between;
}

.warning-content {
  flex: 1;
}

.warning-content strong {
  display: block;
  font-size: 0.95rem;
  margin-bottom: 0.2rem;
}

.warning-content p {
  margin: 0;
  font-size: 0.85rem;
  color: #fde68a;
}

.signup-pill-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  background: #f59e0b;
  color: #1e1e1e;
  padding: 0.45rem 0.85rem;
  border-radius: 0.375rem;
  font-weight: 600;
  font-size: 0.825rem;
  text-decoration: none;
  white-space: nowrap;
}

.alert-close-btn {
  background: transparent;
  border: none;
  color: inherit;
  font-size: 1.1rem;
  cursor: pointer;
  padding: 0.25rem;
}

/* Demo Showcase & Registration Prompt */
.demo-showcase-wrapper {
  display: flex;
  flex-direction: column;
  gap: 2rem;
}

.register-prompt-card {
  background: var(--bg-card);
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 1rem;
  padding: 2rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, var(--bg-card) 60%);
}

.prompt-icon-circle {
  width: 3.5rem;
  height: 3.5rem;
  border-radius: 50%;
  background: rgba(99, 102, 241, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.prompt-content {
  flex: 1;
}

.prompt-main-text {
  font-size: 1.15rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 0.35rem;
}

.prompt-sub-text {
  font-size: 0.875rem;
  color: var(--text-secondary);
  margin: 0;
  line-height: 1.45;
}

.prompt-register-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: #4f46e5;
  color: #ffffff;
  padding: 0.75rem 1.4rem;
  border-radius: 0.5rem;
  font-weight: 600;
  font-size: 0.9rem;
  text-decoration: none;
  white-space: nowrap;
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.4);
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.prompt-register-btn:hover {
  background: #4338ca;
  transform: translateY(-1px);
}

@media (max-width: 768px) {
  .register-prompt-card {
    flex-direction: column;
    text-align: center;
  }
}

/* Sample Pills */
.sample-scores-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.85rem;
  text-align: center;
}

.sample-intro {
  font-size: 0.875rem;
  color: var(--text-secondary);
  font-weight: 500;
}

.sample-pills-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.75rem;
}

.sample-pill-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: var(--bg-card);
  border: 1px solid var(--border);
  padding: 0.55rem 1rem;
  border-radius: 9999px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.sample-pill-btn:hover {
  border-color: #6366f1;
  background: var(--bg-hover);
  transform: translateY(-1px);
}

.sample-name {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text-primary);
}

.sample-badge {
  font-size: 0.7rem;
  background: var(--bg-subtle);
  color: var(--text-secondary);
  padding: 0.15rem 0.45rem;
  border-radius: 0.25rem;
}

/* Processing State */
.processing-state-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 1rem;
  padding: 4rem 2rem;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
}

.spinner-large {
  width: 3.5rem;
  height: 3.5rem;
  border: 4px solid rgba(99, 102, 241, 0.2);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.processing-state-card h3 {
  font-size: 1.3rem;
  margin: 0;
  color: var(--text-primary);
}

.processing-hint {
  font-size: 0.9rem;
  color: var(--text-secondary);
  max-width: 500px;
  line-height: 1.5;
  margin: 0;
}

.progress-bar-track {
  width: 100%;
  max-width: 400px;
  height: 6px;
  background: var(--bg-subtle);
  border-radius: 3px;
  overflow: hidden;
  position: relative;
  margin-top: 0.5rem;
}

.progress-bar-indeterminate {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  width: 35%;
  background: linear-gradient(90deg, #6366f1, #818cf8);
  border-radius: 3px;
  animation: indeterminate 1.5s infinite ease-in-out;
}

@keyframes indeterminate {
  0% { left: -35%; }
  100% { left: 100%; }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Score Display Card */
.score-display-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 1rem;
  overflow: hidden;
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
}

.viewer-top-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1.25rem;
  border-bottom: 1px solid var(--border);
  background: var(--bg-card);
  flex-wrap: wrap;
  gap: 0.75rem;
}

.score-meta {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.score-name {
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text-primary);
}

.sandbox-tag {
  font-size: 0.75rem;
  font-weight: 600;
  background: rgba(99, 102, 241, 0.15);
  color: #818cf8;
  padding: 0.2rem 0.5rem;
  border-radius: 0.25rem;
}

.viewer-actions {
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
  padding: 0.4rem 0.65rem;
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

.tool-btn.reset-btn {
  color: #f87171;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 0.375rem;
}

.tool-btn.reset-btn:hover {
  background: rgba(239, 68, 68, 0.18);
}

.zoom-display {
  font-size: 0.75rem;
  color: var(--text-secondary);
  padding: 0 0.4rem;
  font-family: monospace;
}

.playback-controls-container {
  padding: 0.75rem 1.25rem;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
}

.notation-viewport {
  display: flex;
  justify-content: center;
  padding: 2rem 1.5rem;
  background: var(--bg-canvas);
  overflow-x: auto;
  min-height: 480px;
}

.osmd-sheet-surface {
  background: #ffffff;
  border-radius: 0.5rem;
  padding: 1.5rem;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.25);
  width: 100%;
  max-width: 900px;
  min-height: 500px;
}

/* Conversion Callout Banner */
.conversion-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem 1.75rem;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.15), rgba(79, 70, 229, 0.08));
  border-top: 1px solid rgba(99, 102, 241, 0.25);
  gap: 1.5rem;
  flex-wrap: wrap;
}

.banner-text-group {
  flex: 1;
}

.banner-title-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1rem;
  color: var(--text-primary);
  margin-bottom: 0.25rem;
}

.banner-desc {
  font-size: 0.85rem;
  color: var(--text-secondary);
  margin: 0;
  line-height: 1.4;
}

.primary-claim-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: #047857;
  color: #ffffff;
  border: none;
  padding: 0.65rem 1.25rem;
  border-radius: 0.5rem;
  font-weight: 600;
  font-size: 0.9rem;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(4, 120, 87, 0.4);
  transition: all 0.15s ease;
  white-space: nowrap;
}

.primary-claim-btn:hover {
  background: #065f46;
  transform: translateY(-1px);
}

@media (max-width: 768px) {
  .sandbox-title {
    font-size: 1.45rem;
  }
  .sandbox-dropzone {
    padding: 2.5rem 1rem;
  }
  .conversion-banner {
    flex-direction: column;
    align-items: stretch;
  }
  .primary-claim-btn {
    justify-content: center;
  }
}
</style>
