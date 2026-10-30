<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import {
  Play,
  Pause,
  Square,
  SkipBack,
  SkipForward,
  RotateCcw,
  Volume2,
  VolumeX,
  Repeat,
  Eye,
  EyeOff,
  MoveVertical,
  SlidersHorizontal,
  Download,
  Loader2,
  Check,
  ChevronDown,
  ChevronUp,
  Music,
  Headphones,
  Settings2,
  Minus,
  Plus
} from 'lucide-vue-next'
import { ScorePlaybackController, type PlaybackStateSnapshot } from '../audio/scorePlayer'
import { INSTRUMENT_OPTIONS, type InstrumentType } from '../audio/synth'
import { REVERB_PRESETS, type ReverbPreset } from '../audio/effectsBus'
import { preferences, savePreferences } from '../composables/useSettings'
import { t } from '../i18n'
import RehearsalExportModal from './RehearsalExportModal.vue'

const props = defineProps<{
  player: ScorePlaybackController
}>()

function handleMasterInstrumentChange(inst: InstrumentType) {
  props.player.setInstrument(inst)
  preferences.value.defaultInstrument = inst
  savePreferences()
}

const playbackState = ref<PlaybackStateSnapshot>(props.player.getSnapshot())
const isScrubbing = ref(false)
const scrubProgress = ref(0)
const isTracksOpen = ref(false)
const isMobileDrawerOpen = ref(false)
const isExportingAudio = ref(false)
const isRehearsalModalOpen = ref(false)
const exportSuccessMessage = ref<string | null>(null)
const exportErrorMessage = ref<string | null>(null)

// Inline editable BPM state
const isEditingBpm = ref(false)
const bpmInputValue = ref<number>(120)
const bpmInputRef = ref<HTMLInputElement | null>(null)

// Wired A-B Measure Practice Loop State
const loopStartMeasure = ref<number | null>(null)
const loopEndMeasure = ref<number | null>(null)

const handleToggleAbLoop = () => {
  const cur = playbackState.value.currentMeasure || 1
  if (loopStartMeasure.value === null) {
    loopStartMeasure.value = cur
  } else if (loopEndMeasure.value === null) {
    if (cur >= loopStartMeasure.value) {
      loopEndMeasure.value = cur
    } else {
      loopEndMeasure.value = loopStartMeasure.value
      loopStartMeasure.value = cur
    }
  } else {
    loopStartMeasure.value = null
    loopEndMeasure.value = null
  }
}

const abLoopLabel = computed(() => {
  if (loopStartMeasure.value !== null && loopEndMeasure.value !== null) {
    return `A–B (${loopStartMeasure.value}–${loopEndMeasure.value})`
  }
  if (loopStartMeasure.value !== null) {
    return `Set B (${loopStartMeasure.value}→)`
  }
  return 'A–B Loop'
})

// Viewport & sticky scroll compact state
const isMobile = ref(typeof window !== 'undefined' && window.innerWidth <= 768)
const isScrolledPast = ref(false)

const closeMobileSheet = () => {
  isMobileDrawerOpen.value = false
  isTracksOpen.value = false
}

const toggleVoicesDrawer = () => {
  if (isTracksOpen.value) {
    isTracksOpen.value = false
  } else {
    isTracksOpen.value = true
    isMobileDrawerOpen.value = false
  }
}

const togglePracticeDrawer = () => {
  if (isMobileDrawerOpen.value && !isTracksOpen.value) {
    isMobileDrawerOpen.value = false
  } else {
    isMobileDrawerOpen.value = true
    isTracksOpen.value = false
  }
}

const switchToVoicesTab = () => {
  isTracksOpen.value = true
  isMobileDrawerOpen.value = false
}

const updateViewportState = () => {
  if (typeof window !== 'undefined') {
    isMobile.value = window.innerWidth <= 768
    isScrolledPast.value = window.scrollY > 100
  }
}

const startEditBpm = () => {
  bpmInputValue.value = playbackState.value.bpm
  isEditingBpm.value = true
  setTimeout(() => {
    bpmInputRef.value?.focus()
    bpmInputRef.value?.select()
  }, 20)
}

const commitBpm = () => {
  isEditingBpm.value = false
  const val = Math.max(30, Math.min(280, Math.round(bpmInputValue.value || 120)))
  props.player.setBpm(val)
}

const handleScrollToggle = () => {
  if (playbackState.value.autoScrollEnabled && playbackState.value.autoScrollSuspended) {
    props.player.resumeAutoScroll()
  } else {
    props.player.toggleAutoScroll()
  }
}

const autoscrollButtonLabel = computed(() => {
  if (!playbackState.value.autoScrollEnabled) {
    return `${t('player.scroll')}: OFF`
  }
  if (playbackState.value.autoScrollSuspended) {
    return `${t('player.scroll')}: ${t('player.scrollPausedShort')}`
  }
  return `${t('player.scroll')}: ON`
})

const autoscrollTooltip = computed(() => {
  if (!playbackState.value.autoScrollEnabled) {
    return t('player.enableAutoScroll')
  }
  if (playbackState.value.autoScrollSuspended) {
    return t('player.scrollSuspendedHint')
  }
  return t('player.disableAutoScroll')
})

let unsubscribe: (() => void) | null = null

const formatTime = (totalSeconds: number): string => {
  if (isNaN(totalSeconds) || totalSeconds < 0) return '00:00'
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = Math.floor(totalSeconds % 60)
  return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
}

const currentTimeDisplay = computed(() => {
  if (isScrubbing.value) {
    return formatTime(scrubProgress.value * (playbackState.value.totalDuration || 0))
  }
  return formatTime(playbackState.value.currentTime)
})
const totalDurationDisplay = computed(() => formatTime(playbackState.value.totalDuration))

const currentProgressPercent = computed(() => {
  if (isScrubbing.value) {
    return scrubProgress.value * 100
  }
  return playbackState.value.progress * 100
})

const handleScrubStart = (event: Event) => {
  isScrubbing.value = true
  const input = event.target as HTMLInputElement
  scrubProgress.value = parseFloat(input.value) / 100
}

const handleScrubInput = (event: Event) => {
  const input = event.target as HTMLInputElement
  scrubProgress.value = parseFloat(input.value) / 100
}

const handleScrubChange = (event: Event) => {
  const input = event.target as HTMLInputElement
  const value = parseFloat(input.value) / 100
  props.player.seekToProgress(value)
  isScrubbing.value = false
}

const handleKeyDown = (e: KeyboardEvent) => {
  if (e.code === 'Space') {
    const target = e.target as HTMLElement
    const interactiveTags = ['INPUT', 'TEXTAREA', 'BUTTON', 'A', 'SELECT']
    if (
      interactiveTags.includes(target.tagName) ||
      target.isContentEditable ||
      document.querySelector('[role="dialog"][aria-modal="true"]') ||
      document.querySelector('.modal-backdrop') ||
      document.querySelector('.fixed.inset-0')
    ) {
      return
    }
    e.preventDefault()
    props.player.togglePlayPause()
  }
}

const handleExportAudio = async () => {
  if (isExportingAudio.value) return
  isExportingAudio.value = true
  exportSuccessMessage.value = null
  exportErrorMessage.value = null

  try {
    const { filename } = await props.player.exportAudio()
    exportSuccessMessage.value = `Exported ${filename}`
    setTimeout(() => {
      exportSuccessMessage.value = null
    }, 4000)
  } catch (err: any) {
    console.error('Audio export error:', err)
    exportErrorMessage.value = err?.message || 'Failed to export audio'
    setTimeout(() => {
      exportErrorMessage.value = null
    }, 5000)
  } finally {
    isExportingAudio.value = false
  }
}

watch(
  () => props.player,
  (newPlayer) => {
    if (unsubscribe) unsubscribe()
    unsubscribe = newPlayer.onStateChange((state) => {
      playbackState.value = state
      // Enforce A-B measure loop during active playback
      if (
        state.status === 'playing' &&
        loopStartMeasure.value !== null &&
        loopEndMeasure.value !== null &&
        state.currentMeasure > loopEndMeasure.value
      ) {
        newPlayer.jumpMeasures(loopStartMeasure.value - state.currentMeasure)
      }
      // Auto-open mixer if score has multiple melodic lines and user hasn't opened yet (desktop only)
      if (state.tracks.length > 1 && !isTracksOpen.value && state.hasSolo && !isMobile.value) {
        isTracksOpen.value = true
      }
    })
  },
  { immediate: true }
)

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
  window.addEventListener('scroll', updateViewportState, { passive: true })
  window.addEventListener('resize', updateViewportState, { passive: true })
  updateViewportState()
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
  window.removeEventListener('scroll', updateViewportState)
  window.removeEventListener('resize', updateViewportState)
  if (unsubscribe) {
    unsubscribe()
    unsubscribe = null
  }
})
</script>

<template>
  <!-- Backdrop for mobile sheet dismiss on outside click -->
  <div
    v-if="isMobile && (isMobileDrawerOpen || isTracksOpen)"
    class="mobile-sheet-backdrop"
    @click="closeMobileSheet"
    aria-label="Close settings sheet"
  />

  <div
    class="audio-player-card"
    :class="{
      'is-sticky-compact': isScrolledPast && !isMobile,
      'is-drawer-open': isMobileDrawerOpen || isTracksOpen
    }"
  >
    <!-- ============================================================== -->
    <!-- MOBILE VIEW (< 768px): Bottom-Docked Transport & Practice Sheet -->
    <!-- ============================================================== -->
    <div class="mobile-player-shell">
      <!-- Micro Scrubber along the top edge of player -->
      <div class="mobile-micro-scrubber">
        <div class="mobile-scrubber-fill" :style="{ width: `${currentProgressPercent}%` }" />
        <input
          type="range"
          min="0"
          max="100"
          step="0.1"
          :value="currentProgressPercent"
          @mousedown="handleScrubStart"
          @touchstart="handleScrubStart"
          @input="handleScrubInput"
          @change="handleScrubChange"
          class="mobile-scrubber-input"
          aria-label="Playback scrubber"
        />
      </div>

      <!-- Compact 58px Bar -->
      <div class="mobile-bar-row">
        <!-- Play / Pause primary thumb button (44x44px) -->
        <button
          class="mobile-play-btn"
          :class="{ 'is-playing': playbackState.status === 'playing' }"
          @click="player.togglePlayPause()"
          :aria-label="playbackState.status === 'playing' ? 'Pause' : 'Play'"
        >
          <Pause v-if="playbackState.status === 'playing'" :size="18" />
          <Play v-else :size="18" class="play-icon-offset" />
        </button>

        <!-- Measure Stepper & Readout Chip -->
        <div class="mobile-measure-stepper">
          <button
            type="button"
            class="mobile-measure-step-btn"
            @click="player.jumpMeasures(-1)"
            title="Previous Measure"
            aria-label="Previous Measure"
          >
            −
          </button>
          <div class="mobile-meta-chip" @click="togglePracticeDrawer">
            <span class="meta-measure">
              M.{{ playbackState.currentMeasure || 1 }}<span v-if="playbackState.totalMeasures > 0">/{{ playbackState.totalMeasures }}</span>
            </span>
            <span class="meta-dot">•</span>
            <span class="meta-time">{{ currentTimeDisplay }}</span>
          </div>
          <button
            type="button"
            class="mobile-measure-step-btn"
            @click="player.jumpMeasures(1)"
            title="Next Measure"
            aria-label="Next Measure"
          >
            +
          </button>
        </div>

        <!-- Quick Tempo chip -->
        <button
          class="mobile-tempo-chip"
          @click="togglePracticeDrawer"
          title="Tempo & practice settings"
        >
          <span class="tempo-num">{{ playbackState.bpm }}</span>
          <span class="tempo-unit">BPM</span>
        </button>

        <!-- Voice mixer trigger (if multi-voice) -->
        <button
          v-if="playbackState.tracks.length > 1 || player.canSplitChoralVoices()"
          class="mobile-voice-chip"
          :class="{ active: isTracksOpen, 'has-solo': playbackState.hasSolo }"
          @click="toggleVoicesDrawer"
          :title="t('player.stemsMixer')"
        >
          <SlidersHorizontal :size="14" />
          <span>{{ playbackState.tracks.length }}</span>
          <span v-if="playbackState.hasSolo" class="mini-solo-dot" />
        </button>

        <!-- Expand / Collapse Drawer button (44x44px) -->
        <button
          class="mobile-expand-btn"
          :class="{ active: isMobileDrawerOpen && !isTracksOpen }"
          @click="togglePracticeDrawer"
          :title="isMobileDrawerOpen || isTracksOpen ? 'Collapse settings' : 'Practice settings'"
          :aria-expanded="isMobileDrawerOpen || isTracksOpen"
        >
          <ChevronDown v-if="isMobileDrawerOpen || isTracksOpen" :size="18" />
          <Settings2 v-else :size="18" />
        </button>
      </div>

      <!-- Expandable Practice Sheet & Voices Mixer for Mobile -->
      <div v-if="isMobileDrawerOpen || isTracksOpen" class="mobile-drawer-body">
        <!-- Sticky Header with Navigation Tabs and Close Action -->
        <div class="mobile-sheet-header">
          <div class="sheet-tabs">
            <button
              type="button"
              class="sheet-tab-btn"
              data-tab="practice"
              :class="{ active: isMobileDrawerOpen && !isTracksOpen }"
              @click="isMobileDrawerOpen = true; isTracksOpen = false"
            >
              <Settings2 :size="14" />
              <span>Practice</span>
            </button>
            <button
              v-if="playbackState.tracks.length > 1 || player.canSplitChoralVoices()"
              type="button"
              class="sheet-tab-btn"
              data-tab="voices"
              :class="{ active: isTracksOpen }"
              @click="isTracksOpen = true; isMobileDrawerOpen = false"
            >
              <SlidersHorizontal :size="14" />
              <span>Voices ({{ playbackState.tracks.length }})</span>
              <span v-if="playbackState.hasSolo" class="mini-solo-dot" />
            </button>
          </div>

          <div class="sheet-header-actions">
            <button
              v-if="isTracksOpen"
              type="button"
              class="sheet-action-link"
              @click="player.resetTrackMix()"
              title="Reset all lines to unmuted, un-soloed, 80% volume"
            >
              Reset Mix
            </button>
            <button
              type="button"
              class="sheet-done-btn"
              @click="closeMobileSheet"
              title="Done"
            >
              Done
            </button>
          </div>
        </div>

        <!-- TAB 1: Practice Settings (Tempo, Sound, Reverb, Loops, Exports) -->
        <div v-if="isMobileDrawerOpen && !isTracksOpen" class="mobile-tab-content">
          <!-- Measure Jump, A-B Loop & Full Loop -->
          <div class="mobile-drawer-section">
            <div class="mobile-drawer-cluster">
              <button class="drawer-btn" @click="player.stop()" :title="t('player.stop')">
                <Square :size="14" />
                <span>{{ t('player.stop') }}</span>
              </button>
              <button
                class="drawer-btn"
                :class="{ active: loopStartMeasure !== null }"
                @click="handleToggleAbLoop"
                title="Set A-B Measure Practice Loop"
              >
                <Repeat :size="14" />
                <span>{{ abLoopLabel }}</span>
              </button>
              <button
                class="drawer-btn"
                :class="{ active: playbackState.isLooping }"
                @click="player.toggleLoop()"
                :title="t('player.loop')"
              >
                <Repeat :size="14" />
                <span>{{ t('player.loop') }}</span>
              </button>
            </div>
          </div>

          <!-- Tempo Stepper -->
          <div class="mobile-drawer-section">
            <div class="mobile-drawer-row">
              <span class="drawer-label">{{ t('player.tempo') }}</span>
              <div class="tempo-stepper-inline">
                <button class="stepper-btn" @click="player.setBpm(playbackState.bpm - 5)">−5</button>
                <button class="stepper-btn" @click="player.setBpm(playbackState.bpm - 1)">−</button>
                <span class="stepper-readout" @click="startEditBpm">{{ playbackState.bpm }} BPM</span>
                <button class="stepper-btn" @click="player.setBpm(playbackState.bpm + 1)">+</button>
                <button class="stepper-btn" @click="player.setBpm(playbackState.bpm + 5)">+5</button>
                <button class="reset-btn" @click="player.resetBpmToDefault()" title="Reset tempo">
                  <RotateCcw :size="14" />
                </button>
              </div>
            </div>
          </div>

          <!-- Instrument & Reverb Selectors -->
          <div class="mobile-drawer-section">
            <div class="mobile-select-grid">
              <div class="mobile-select-group">
                <label class="drawer-label">{{ t('player.sound') }}</label>
                <select
                  :value="playbackState.instrument"
                  @change="handleMasterInstrumentChange(($event.target as HTMLSelectElement).value as InstrumentType)"
                  class="drawer-select"
                >
                  <optgroup :label="t('player.sampledInstruments')">
                    <option
                      v-for="inst in INSTRUMENT_OPTIONS.filter((i) => i.category === 'soundfont')"
                      :key="inst.id"
                      :value="inst.id"
                    >
                      {{ inst.name }}
                    </option>
                  </optgroup>
                  <optgroup :label="t('player.synthesizedTimbre')">
                    <option
                      v-for="inst in INSTRUMENT_OPTIONS.filter((i) => i.category === 'synth')"
                      :key="inst.id"
                      :value="inst.id"
                    >
                      {{ inst.name }}
                    </option>
                  </optgroup>
                </select>
              </div>

              <div class="mobile-select-group">
                <label class="drawer-label">{{ t('player.reverb') }}</label>
                <select
                  :value="playbackState.reverbPreset"
                  @change="player.setReverbPreset(($event.target as HTMLSelectElement).value as ReverbPreset)"
                  class="drawer-select"
                >
                  <option v-for="r in REVERB_PRESETS" :key="r.id" :value="r.id">
                    {{ r.name }}
                  </option>
                </select>
              </div>
            </div>
          </div>

          <!-- Master Volume -->
          <div class="mobile-drawer-section">
            <div class="mobile-drawer-row">
              <div class="drawer-vol-label">
                <button class="icon-vol-btn" @click="player.toggleMute()">
                  <VolumeX v-if="playbackState.isMuted || playbackState.volume === 0" :size="15" class="mute-icon" />
                  <Volume2 v-else :size="15" />
                </button>
                <span class="drawer-label">Master Volume</span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                :value="playbackState.isMuted ? 0 : playbackState.volume"
                @input="player.setVolume(parseFloat(($event.target as HTMLInputElement).value))"
                class="mobile-vol-slider"
              />
              <span class="vol-num">{{ playbackState.isMuted ? '0%' : `${playbackState.volume}%` }}</span>
            </div>
          </div>

          <!-- Utility toggles: Cursor & Auto-scroll & Voices Shortcut -->
          <div class="mobile-drawer-section">
            <div class="mobile-drawer-cluster">
              <button
                class="drawer-btn"
                :class="{ active: playbackState.cursorVisible }"
                @click="player.toggleCursorVisible()"
              >
                <Eye v-if="playbackState.cursorVisible" :size="14" />
                <EyeOff v-else :size="14" />
                <span>{{ t('player.cursor') }}</span>
              </button>
              <button
                class="drawer-btn autoscroll-toggle-btn"
                :class="{
                  active: playbackState.autoScrollEnabled && !playbackState.autoScrollSuspended,
                  suspended: playbackState.autoScrollEnabled && playbackState.autoScrollSuspended
                }"
                @click="handleScrollToggle"
              >
                <MoveVertical :size="14" />
                <span>{{ autoscrollButtonLabel }}</span>
              </button>
              <button
                v-if="playbackState.tracks.length > 1 || player.canSplitChoralVoices()"
                class="drawer-btn"
                @click="switchToVoicesTab"
              >
                <SlidersHorizontal :size="14" />
                <span>{{ t('player.stemsMixer') }} ({{ playbackState.tracks.length }})</span>
              </button>
            </div>
          </div>

          <!-- Export Buttons -->
          <div class="mobile-drawer-section">
            <div class="mobile-drawer-cluster">
              <button
                class="drawer-btn export-action-btn"
                :disabled="isExportingAudio || playbackState.totalSteps === 0"
                @click="handleExportAudio"
              >
                <Loader2 v-if="isExportingAudio" class="spin-icon" :size="14" />
                <Check v-else-if="exportSuccessMessage" :size="14" class="success-icon" />
                <Download v-else :size="14" />
                <span>{{ isExportingAudio ? t('player.exportingAudio') : t('player.exportAudio') }}</span>
              </button>
              <button
                class="drawer-btn rehearsal-action-btn"
                :disabled="playbackState.totalSteps === 0"
                @click="isRehearsalModalOpen = true"
              >
                <Headphones :size="14" />
                <span>{{ t('player.rehearsalTracks') }}</span>
              </button>
            </div>
          </div>
        </div>

        <!-- TAB 2: Voices Mixer (Quick Solo Bar & Scrollable Voice Cards) -->
        <div v-if="isTracksOpen" class="mobile-voices-content">
          <!-- Mobile Voicing Mode Banner -->
          <div v-if="player.canSplitChoralVoices()" class="mobile-voicing-banner">
            <span class="quick-solo-label">Voicing Mode:</span>
            <div class="voicing-mode-toggle-group">
              <button
                type="button"
                class="voicing-toggle-pill"
                :class="{ active: playbackState.voicingMode === 'choral' || (playbackState.voicingMode === 'auto' && playbackState.tracks.length > 1) }"
                @click="player.setVoicingMode('choral')"
              >
                Choir (SATB)
              </button>
              <button
                type="button"
                class="voicing-toggle-pill"
                :class="{ active: playbackState.voicingMode === 'keyboard' || (playbackState.voicingMode === 'auto' && playbackState.tracks.length <= 1) }"
                @click="player.setVoicingMode('keyboard')"
              >
                Piano
              </button>
            </div>
          </div>

          <!-- Quick Solo Bar -->
          <div class="quick-solo-bar">
            <span class="quick-solo-label">{{ t('player.isolateMelodicLine') }}:</span>
            <button
              class="solo-pill"
              :class="{ active: !playbackState.hasSolo }"
              @click="player.clearAllSolo()"
              title="Hear all voices together in full harmony"
            >
              {{ t('player.allLines') }}
            </button>
            <button
              v-for="track in playbackState.tracks"
              :key="track.id"
              class="solo-pill"
              :class="[
                { active: track.isSolo },
                track.voiceTag ? `tag-${track.voiceTag.toLowerCase().replace(/[^a-z0-9]/g, '')}` : ''
              ]"
              @click="player.soloOnlyTrack(track.id)"
              :title="`Isolate only ${track.displayName || track.name}`"
            >
              <span v-if="track.voiceTag" class="voice-pill-tag">{{ track.voiceTag }}</span>
              <span class="voice-pill-name">{{ track.name }}</span>
            </button>
          </div>

          <!-- Tracks Grid / Scrollable List -->
          <div class="tracks-grid mobile-tracks-scroll">
            <div
              v-for="track in playbackState.tracks"
              :key="track.id"
              class="track-card"
              :class="{
                'is-soloed': track.isSolo,
                'is-muted': track.isMuted,
                'is-inaudible': !player.isTrackAudible(track.id),
              }"
            >
              <!-- Track Card Header -->
              <div class="track-card-header">
                <div class="track-title-wrapper">
                  <span
                    v-if="track.voiceTag"
                    class="track-voice-tag-badge"
                    :class="`tag-${track.voiceTag.toLowerCase().replace(/[^a-z0-9]/g, '')}`"
                    :title="track.displayName || track.name"
                  >
                    {{ track.voiceTag }}
                  </span>
                  <span class="track-name" :title="track.displayName || track.name">{{ track.name }}</span>
                  <span class="track-part-badge">{{ track.partId }}</span>
                </div>

                <!-- Solo & Mute DAW buttons -->
                <div class="track-btn-group">
                  <button
                    class="track-action-btn solo-btn"
                    :class="{ active: track.isSolo }"
                    @click="player.toggleTrackSolo(track.id)"
                    :title="track.isSolo ? `Unsolo ${track.name}` : `Solo ${track.name}`"
                  >
                    S
                  </button>
                  <button
                    class="track-action-btn mute-btn"
                    :class="{ active: track.isMuted }"
                    @click="player.toggleTrackMute(track.id)"
                    :title="track.isMuted ? `Unmute ${track.name}` : `Mute ${track.name}`"
                  >
                    M
                  </button>
                </div>
              </div>

              <!-- Track Controls -->
              <div class="track-card-body">
                <!-- Instrument Picker -->
                <div class="track-control-row">
                  <label class="track-label">Sound</label>
                  <select
                    :value="track.instrument"
                    @change="player.setTrackInstrument(track.id, ($event.target as HTMLSelectElement).value as InstrumentType)"
                    class="track-instrument-select"
                  >
                    <optgroup label="Sampled Instruments">
                      <option
                        v-for="inst in INSTRUMENT_OPTIONS.filter((i) => i.category === 'soundfont')"
                        :key="inst.id"
                        :value="inst.id"
                      >
                        {{ inst.name }}
                      </option>
                    </optgroup>
                    <optgroup label="Synthesized Timbre">
                      <option
                        v-for="inst in INSTRUMENT_OPTIONS.filter((i) => i.category === 'synth')"
                        :key="inst.id"
                        :value="inst.id"
                      >
                        {{ inst.name }}
                      </option>
                    </optgroup>
                  </select>
                </div>

                <!-- Volume Slider -->
                <div class="track-control-row">
                  <div class="track-vol-header">
                    <label class="track-label">Volume</label>
                    <span class="track-vol-text">{{ track.volume }}%</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    :value="track.volume"
                    @input="player.setTrackVolume(track.id, parseFloat(($event.target as HTMLInputElement).value))"
                    class="track-slider"
                    :aria-label="`${track.name} volume`"
                  />
                </div>

                <!-- Stereo Pan Slider -->
                <div class="track-control-row">
                  <div class="track-vol-header">
                    <label class="track-label">Pan</label>
                    <span class="track-vol-text">
                      {{ track.pan === 0 ? 'C' : track.pan < 0 ? `L${Math.round(Math.abs(track.pan) * 100)}` : `R${Math.round(track.pan * 100)}` }}
                    </span>
                  </div>
                  <input
                    type="range"
                    min="-1"
                    max="1"
                    step="0.05"
                    :value="track.pan"
                    @input="player.setTrackPan(track.id, parseFloat(($event.target as HTMLInputElement).value))"
                    class="track-slider pan-slider"
                    :aria-label="`${track.name} pan`"
                  />
                </div>

                <!-- Reverb Send Slider -->
                <div class="track-control-row">
                  <div class="track-vol-header">
                    <label class="track-label">Reverb Send</label>
                    <span class="track-vol-text">{{ Math.round((track.reverbSend ?? 0.25) * 100) }}%</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.05"
                    :value="track.reverbSend ?? 0.25"
                    @input="player.setTrackReverbSend(track.id, parseFloat(($event.target as HTMLInputElement).value))"
                    class="track-slider reverb-slider"
                    :aria-label="`${track.name} reverb send`"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ============================================================== -->
    <!-- DESKTOP VIEW (> 768px): Unified Studio Media Deck (~84px)      -->
    <!-- ============================================================== -->
    <div class="desktop-player-deck">
      <!-- Deck Row 1: Integrated Scrubber & Timeline Readouts -->
      <div class="desktop-timeline-row">
        <!-- Left Timeline Meta -->
        <div class="timeline-meta-left">
          <span class="time-readout">
            <strong class="time-current">{{ currentTimeDisplay }}</strong>
            <span class="time-divider">/</span>
            <span class="time-total">{{ totalDurationDisplay }}</span>
          </span>
          <span class="measure-chip" v-if="playbackState.totalMeasures > 0">
            {{ t('player.measure') }} {{ playbackState.currentMeasure }} / {{ playbackState.totalMeasures }}
          </span>
          <span
            v-if="playbackState.status === 'playing' && playbackState.currentNotesPlaying"
            class="now-playing-chip"
            :title="`Currently playing: ${playbackState.currentNotesPlaying}`"
          >
            <Music :size="11" class="playing-pulse-icon" />
            <strong class="playing-notes">{{ playbackState.currentNotesPlaying }}</strong>
          </span>
        </div>

        <!-- Timeline Scrubber -->
        <div class="desktop-slider-container">
          <div class="progress-bar-fill" :style="{ width: `${currentProgressPercent}%` }"></div>
          <input
            type="range"
            min="0"
            max="100"
            step="0.1"
            :value="currentProgressPercent"
            @mousedown="handleScrubStart"
            @touchstart="handleScrubStart"
            @input="handleScrubInput"
            @change="handleScrubChange"
            class="timeline-slider"
            aria-label="Score playback scrubber"
          />
        </div>

        <!-- Right Timeline Meta (Export feedback) -->
        <div class="timeline-meta-right">
          <span v-if="exportSuccessMessage" class="export-feedback success-feedback">
            <Check :size="12" /> {{ exportSuccessMessage }}
          </span>
          <span v-if="exportErrorMessage" class="export-feedback error-feedback">
            {{ exportErrorMessage }}
          </span>
        </div>
      </div>

      <!-- Deck Row 2: Transport, Tempo, Timbre, Reverb, Volume & Utilities -->
      <div class="desktop-controls-row">
        <!-- Transport Cluster -->
        <div class="transport-cluster">
          <button
            class="transport-btn main-play-btn"
            :class="{ 'is-playing': playbackState.status === 'playing' }"
            @click="player.togglePlayPause()"
            :title="playbackState.status === 'playing' ? 'Pause (Space)' : 'Play (Space)'"
          >
            <Pause v-if="playbackState.status === 'playing'" :size="17" />
            <Play v-else :size="17" class="play-icon-offset" />
            <span>{{ playbackState.status === 'playing' ? t('player.pause') : t('player.play') }}</span>
          </button>

          <button
            class="transport-btn icon-btn"
            @click="player.stop()"
            :title="t('player.stop')"
          >
            <Square :size="14" />
          </button>

          <div class="step-btn-group">
            <button
              class="transport-btn icon-btn"
              @click="player.jumpMeasures(-1)"
              :title="t('player.skipBack')"
            >
              <SkipBack :size="14" />
            </button>
            <button
              class="transport-btn icon-btn"
              @click="player.jumpMeasures(1)"
              :title="t('player.skipForward')"
            >
              <SkipForward :size="14" />
            </button>
          </div>
        </div>

        <!-- Tuning & Timbre Cluster -->
        <div class="tuning-cluster">
          <!-- Tempo Stepper Chip -->
          <div class="control-chip tempo-chip" :class="{ 'is-editing': isEditingBpm }">
            <button
              class="chip-stepper-btn"
              @click="player.setBpm(playbackState.bpm - 5)"
              title="Slow down 5 BPM"
              type="button"
            >
              <Minus :size="12" :stroke-width="2.5" />
            </button>
            <div
              v-if="!isEditingBpm"
              class="bpm-readout clickable"
              @click="startEditBpm"
              title="Click to edit tempo (BPM)"
            >
              <span class="bpm-num">{{ playbackState.bpm }}</span>
              <span class="bpm-suffix">BPM</span>
            </div>
            <input
              v-else
              ref="bpmInputRef"
              v-model.number="bpmInputValue"
              type="number"
              min="30"
              max="280"
              class="bpm-inline-input"
              @blur="commitBpm"
              @keydown.enter="commitBpm"
              @keydown.esc="isEditingBpm = false"
            />
            <button
              class="chip-stepper-btn"
              @click="player.setBpm(playbackState.bpm + 5)"
              title="Speed up 5 BPM"
              type="button"
            >
              <Plus :size="12" :stroke-width="2.5" />
            </button>
            <div class="tempo-divider"></div>
            <button
              class="chip-reset-btn"
              @click="player.resetBpmToDefault()"
              title="Reset to score default tempo"
              type="button"
            >
              <RotateCcw :size="11" />
            </button>
          </div>

          <!-- Sound Selector Chip -->
          <div class="control-chip select-chip">
            <select
              :value="playbackState.instrument"
              @change="handleMasterInstrumentChange(($event.target as HTMLSelectElement).value as InstrumentType)"
              class="deck-select"
              title="Synthesizer sound timbre"
            >
              <optgroup :label="t('player.sampledInstruments')">
                <option
                  v-for="inst in INSTRUMENT_OPTIONS.filter((i) => i.category === 'soundfont')"
                  :key="inst.id"
                  :value="inst.id"
                >
                  {{ inst.name }}
                </option>
              </optgroup>
              <optgroup :label="t('player.synthesizedTimbre')">
                <option
                  v-for="inst in INSTRUMENT_OPTIONS.filter((i) => i.category === 'synth')"
                  :key="inst.id"
                  :value="inst.id"
                >
                  {{ inst.name }}
                </option>
              </optgroup>
            </select>
          </div>

          <!-- Reverb Selector Chip -->
          <div class="control-chip select-chip">
            <select
              :value="playbackState.reverbPreset"
              @change="player.setReverbPreset(($event.target as HTMLSelectElement).value as ReverbPreset)"
              class="deck-select reverb-select"
              title="Acoustic space & convolution reverb"
            >
              <option v-for="r in REVERB_PRESETS" :key="r.id" :value="r.id">
                {{ r.name }}
              </option>
            </select>
          </div>
        </div>

        <!-- Master Volume & Utilities Cluster -->
        <div class="utility-cluster">
          <!-- Volume Slider -->
          <div class="control-chip volume-chip">
            <button
              class="icon-btn volume-btn"
              @click="player.toggleMute()"
              :title="playbackState.isMuted ? 'Unmute master' : 'Mute master'"
            >
              <VolumeX v-if="playbackState.isMuted || playbackState.volume === 0" :size="14" class="mute-icon" />
              <Volume2 v-else :size="14" />
            </button>
            <input
              type="range"
              min="0"
              max="100"
              :value="playbackState.isMuted ? 0 : playbackState.volume"
              @input="player.setVolume(parseFloat(($event.target as HTMLInputElement).value))"
              class="deck-volume-slider"
              aria-label="Master volume"
            />
            <span class="deck-volume-text">{{ playbackState.isMuted ? '0%' : `${playbackState.volume}%` }}</span>
          </div>

          <!-- Stems / Melodic Lines Toggle -->
          <button
            class="transport-btn tracks-btn"
            :class="{ active: isTracksOpen, 'has-solo': playbackState.hasSolo }"
            @click="isTracksOpen = !isTracksOpen"
            :title="t('player.stemsMixer')"
          >
            <SlidersHorizontal :size="14" />
            <span>{{ t('studio.ribbon.voice') }} ({{ playbackState.tracks.length }})</span>
            <span v-if="playbackState.hasSolo" class="mini-solo-indicator" title="Solo">Solo</span>
            <ChevronUp v-if="isTracksOpen" :size="13" />
            <ChevronDown v-else :size="13" />
          </button>

          <!-- Utilities: Loop, Cursor, Autoscroll -->
          <div class="deck-toggle-group">
            <button
              class="transport-btn icon-tool-btn"
              :class="{ active: playbackState.isLooping }"
              @click="player.toggleLoop()"
              :title="t('player.loop')"
            >
              <Repeat :size="14" />
            </button>
            <button
              class="transport-btn icon-tool-btn"
              :class="{ active: playbackState.cursorVisible }"
              @click="player.toggleCursorVisible()"
              :title="playbackState.cursorVisible ? 'Hide sheet music cursor' : 'Show sheet music cursor'"
            >
              <Eye v-if="playbackState.cursorVisible" :size="14" />
              <EyeOff v-else :size="14" />
            </button>
            <button
              class="transport-btn icon-tool-btn autoscroll-toggle-btn"
              :class="{
                active: playbackState.autoScrollEnabled && !playbackState.autoScrollSuspended,
                suspended: playbackState.autoScrollEnabled && playbackState.autoScrollSuspended
              }"
              @click="handleScrollToggle"
              :title="autoscrollTooltip"
            >
              <MoveVertical :size="14" />
            </button>
          </div>

          <!-- Audio WAV Export -->
          <button
            class="transport-btn export-wav-btn"
            :disabled="isExportingAudio || playbackState.totalSteps === 0"
            @click="handleExportAudio"
            :title="t('player.exportAudio')"
          >
            <Loader2 v-if="isExportingAudio" class="spin-icon" :size="14" />
            <Check v-else-if="exportSuccessMessage" :size="14" class="success-icon" />
            <Download v-else :size="14" />
            <span class="desktop-btn-text">{{ isExportingAudio ? t('player.exportingAudio') : t('player.exportAudio') }}</span>
          </button>

          <!-- Rehearsal Export -->
          <button
            class="transport-btn rehearsal-btn"
            :disabled="playbackState.totalSteps === 0"
            @click="isRehearsalModalOpen = true"
            :title="t('player.rehearsalTracksTooltip')"
          >
            <Headphones :size="14" />
            <span class="desktop-btn-text">{{ t('player.rehearsalTracks') }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- ============================================================== -->
    <!-- DESKTOP: Melodic Lines & Tracks Mixer Panel                     -->
    <!-- ============================================================== -->
    <div v-if="isTracksOpen && !isMobile" class="tracks-mixer-panel">
      <!-- Mixer Header & Quick Solo Bar -->
      <div class="mixer-header-row">
        <div class="quick-solo-bar">
          <span class="quick-solo-label">{{ t('player.isolateMelodicLine') }}:</span>
          <button
            class="solo-pill"
            :class="{ active: !playbackState.hasSolo }"
            @click="player.clearAllSolo()"
            title="Hear all voices together in full harmony"
          >
            {{ t('player.allLines') }}
          </button>
          <button
            v-for="track in playbackState.tracks"
            :key="track.id"
            class="solo-pill"
            :class="[
              { active: track.isSolo },
              track.voiceTag ? `tag-${track.voiceTag.toLowerCase().replace(/[^a-z0-9]/g, '')}` : ''
            ]"
            @click="player.soloOnlyTrack(track.id)"
            :title="`Isolate only ${track.displayName || track.name}`"
          >
            <span v-if="track.voiceTag" class="voice-pill-tag">{{ track.voiceTag }}</span>
            <span class="voice-pill-name">{{ track.name }}</span>
          </button>
        </div>

        <div class="mixer-actions">
          <div v-if="player.canSplitChoralVoices()" class="voicing-mode-toggle-group">
            <button
              type="button"
              class="voicing-toggle-pill"
              :class="{ active: playbackState.voicingMode === 'choral' || (playbackState.voicingMode === 'auto' && playbackState.tracks.length > 1) }"
              @click="player.setVoicingMode('choral')"
              title="Split score into SATB choral voices"
            >
              Choir (SATB)
            </button>
            <button
              type="button"
              class="voicing-toggle-pill"
              :class="{ active: playbackState.voicingMode === 'keyboard' || (playbackState.voicingMode === 'auto' && playbackState.tracks.length <= 1) }"
              @click="player.setVoicingMode('keyboard')"
              title="Keep as single keyboard/piano track"
            >
              Piano
            </button>
          </div>
          <button
            class="mixer-text-btn"
            @click="player.resetTrackMix()"
            title="Reset all lines to unmuted, un-soloed, 80% volume"
          >
            Reset Mix
          </button>
          <button
            class="mixer-close-btn"
            @click="isTracksOpen = false"
            title="Close mixer"
          >
            Done
          </button>
        </div>
      </div>

      <!-- Tracks Grid -->
      <div class="tracks-grid">
        <div
          v-for="track in playbackState.tracks"
          :key="track.id"
          class="track-card"
          :class="{
            'is-soloed': track.isSolo,
            'is-muted': track.isMuted,
            'is-inaudible': !player.isTrackAudible(track.id),
          }"
        >
          <!-- Track Card Header -->
          <div class="track-card-header">
            <div class="track-title-wrapper">
              <span
                v-if="track.voiceTag"
                class="track-voice-tag-badge"
                :class="`tag-${track.voiceTag.toLowerCase().replace(/[^a-z0-9]/g, '')}`"
                :title="track.displayName || track.name"
              >
                {{ track.voiceTag }}
              </span>
              <span class="track-name" :title="track.displayName || track.name">{{ track.name }}</span>
              <span class="track-part-badge">{{ track.partId }}</span>
            </div>

            <!-- Solo & Mute DAW buttons -->
            <div class="track-btn-group">
              <button
                class="track-action-btn solo-btn"
                :class="{ active: track.isSolo }"
                @click="player.toggleTrackSolo(track.id)"
                :title="track.isSolo ? `Unsolo ${track.name}` : `Solo ${track.name} (play only this line)`"
              >
                S
              </button>
              <button
                class="track-action-btn mute-btn"
                :class="{ active: track.isMuted }"
                @click="player.toggleTrackMute(track.id)"
                :title="track.isMuted ? `Unmute ${track.name}` : `Mute ${track.name}`"
              >
                M
              </button>
            </div>
          </div>

          <!-- Track Controls -->
          <div class="track-card-body">
            <!-- Instrument Picker -->
            <div class="track-control-row">
              <label class="track-label">Sound</label>
              <select
                :value="track.instrument"
                @change="player.setTrackInstrument(track.id, ($event.target as HTMLSelectElement).value as InstrumentType)"
                class="track-instrument-select"
              >
                <optgroup label="Sampled Instruments">
                  <option
                    v-for="inst in INSTRUMENT_OPTIONS.filter((i) => i.category === 'soundfont')"
                    :key="inst.id"
                    :value="inst.id"
                  >
                    {{ inst.name }}
                  </option>
                </optgroup>
                <optgroup label="Synthesized Timbre">
                  <option
                    v-for="inst in INSTRUMENT_OPTIONS.filter((i) => i.category === 'synth')"
                    :key="inst.id"
                    :value="inst.id"
                  >
                    {{ inst.name }}
                  </option>
                </optgroup>
              </select>
            </div>

            <!-- Volume Slider -->
            <div class="track-control-row">
              <div class="track-vol-header">
                <label class="track-label">Volume</label>
                <span class="track-vol-text">{{ track.volume }}%</span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                :value="track.volume"
                @input="player.setTrackVolume(track.id, parseFloat(($event.target as HTMLInputElement).value))"
                class="track-slider"
                :aria-label="`${track.name} volume`"
              />
            </div>

            <!-- Stereo Pan Slider -->
            <div class="track-control-row">
              <div class="track-vol-header">
                <label class="track-label">Pan</label>
                <span class="track-vol-text">
                  {{ track.pan === 0 ? 'C' : track.pan < 0 ? `L${Math.round(Math.abs(track.pan) * 100)}` : `R${Math.round(track.pan * 100)}` }}
                </span>
              </div>
              <input
                type="range"
                min="-1"
                max="1"
                step="0.05"
                :value="track.pan"
                @input="player.setTrackPan(track.id, parseFloat(($event.target as HTMLInputElement).value))"
                class="track-slider pan-slider"
                :aria-label="`${track.name} pan`"
              />
            </div>

            <!-- Reverb Send Slider -->
            <div class="track-control-row">
              <div class="track-vol-header">
                <label class="track-label">Reverb Send</label>
                <span class="track-vol-text">{{ Math.round((track.reverbSend ?? 0.25) * 100) }}%</span>
              </div>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                :value="track.reverbSend ?? 0.25"
                @input="player.setTrackReverbSend(track.id, parseFloat(($event.target as HTMLInputElement).value))"
                class="track-slider reverb-slider"
                :aria-label="`${track.name} reverb send`"
              />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Rehearsal Tracks Generator Modal -->
    <RehearsalExportModal
      :is-open="isRehearsalModalOpen"
      :player="player"
      @close="isRehearsalModalOpen = false"
    />
  </div>
</template>

<style scoped>
/* Main Player Container */
.audio-player-card {
  position: sticky;
  top: calc(var(--app-header-height, 65px) + 8px);
  z-index: 90;
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  border-radius: 12px;
  padding: 8px 12px;
  margin-bottom: 10px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.28), 0 1px 3px rgba(0, 0, 0, 0.15);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

:fullscreen .audio-player-card,
:global(.score-viewer-wrapper.is-fullscreen) .audio-player-card {
  top: 10px;
}

/* Mobile Sheet Backdrop (Outside-click dismiss) */
.mobile-sheet-backdrop {
  position: fixed;
  inset: 0;
  z-index: 8790;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  animation: backdropFadeIn 0.2s ease-out;
}

@keyframes backdropFadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* ============================================================== */
/* MOBILE VIEW STYLES (< 768px)                                   */
/* ============================================================== */
.mobile-player-shell {
  display: none;
}

@media (max-width: 768px) {
  .desktop-player-deck {
    display: none !important;
  }

  .mobile-player-shell {
    display: flex;
    flex-direction: column-reverse;
    width: 100%;
    max-height: 100%;
  }

  .audio-player-card {
    position: fixed;
    bottom: max(var(--sab, 0px), 8px);
    left: 8px;
    right: 8px;
    top: auto;
    z-index: 8800;
    padding: 0;
    overflow: hidden;
    border-radius: 16px;
    margin-bottom: 0;
    max-height: calc(100dvh - max(var(--sat, 0px), 16px) - 16px);
    display: flex;
    flex-direction: column-reverse;
    background: var(--bg-glass-heavy, var(--bg-card));
    backdrop-filter: blur(20px) saturate(180%);
    -webkit-backdrop-filter: blur(20px) saturate(180%);
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
  }

  .mobile-micro-scrubber {
    position: relative;
    width: 100%;
    height: 5px;
    background: var(--bg-subtle, rgba(255, 255, 255, 0.1));
  }

  .mobile-scrubber-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--color-primary, #6366f1), var(--color-accent, #22d3ee));
    pointer-events: none;
  }

  .mobile-scrubber-input {
    position: absolute;
    top: -12px;
    left: 0;
    width: 100%;
    height: 28px;
    opacity: 0;
    cursor: pointer;
    margin: 0;
  }

  .mobile-bar-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
    padding: 6px 10px;
    min-height: 54px;
  }

  .mobile-play-btn {
    width: 44px;
    height: 44px;
    min-width: 44px;
    border-radius: 50%;
    background: var(--color-primary, #6366f1);
    color: #ffffff;
    border: none;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: 0 3px 10px rgba(99, 102, 241, 0.4);
    transition: transform 0.15s ease, background 0.15s ease;
  }

  .mobile-play-btn.is-playing {
    background: var(--color-success, #10b981);
    box-shadow: 0 3px 10px rgba(16, 185, 129, 0.4);
  }

  .mobile-play-btn:active {
    transform: scale(0.92);
  }

  .play-icon-offset {
    margin-left: 2px;
  }

  .mobile-measure-stepper {
    display: inline-flex;
    align-items: center;
    background: var(--bg-subtle, rgba(255, 255, 255, 0.06));
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: 10px;
    overflow: hidden;
  }

  .mobile-measure-step-btn {
    width: 36px;
    height: 40px;
    background: transparent;
    border: none;
    color: var(--text-secondary);
    font-size: 1rem;
    font-weight: 700;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .mobile-measure-step-btn:active {
    background: var(--bg-hover);
    color: var(--text-primary);
  }

  .mobile-meta-chip {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 0.78rem;
    font-family: var(--font-mono, monospace);
    color: var(--text-primary, #f8fafc);
    padding: 0 6px;
    min-height: 40px;
    cursor: pointer;
  }

  .meta-measure {
    font-weight: 700;
    color: var(--color-accent, #38bdf8);
  }

  .meta-dot {
    opacity: 0.5;
  }

  .mobile-tempo-chip {
    display: flex;
    align-items: center;
    gap: 2px;
    font-size: 0.78rem;
    font-family: var(--font-mono, monospace);
    font-weight: 700;
    background: var(--bg-subtle, rgba(255, 255, 255, 0.06));
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    color: var(--text-primary, #f8fafc);
    padding: 0 10px;
    min-height: 40px;
    border-radius: 8px;
    cursor: pointer;
  }

  .tempo-unit {
    font-size: 0.62rem;
    color: var(--text-muted, #94a3b8);
  }

  .mobile-voice-chip {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 0.76rem;
    font-weight: 600;
    background: var(--bg-subtle, rgba(255, 255, 255, 0.06));
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    color: var(--text-primary, #f8fafc);
    padding: 0 10px;
    min-height: 40px;
    border-radius: 8px;
    cursor: pointer;
  }

  .mobile-voice-chip.has-solo {
    background: rgba(245, 158, 11, 0.2);
    border-color: #f59e0b;
    color: #f59e0b;
  }

  .mini-solo-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #f59e0b;
  }

  .mobile-expand-btn {
    width: 44px;
    height: 44px;
    min-width: 44px;
    border-radius: 10px;
    background: transparent;
    border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
    color: var(--text-secondary, #94a3b8);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .mobile-expand-btn.active {
    background: var(--color-primary-light, rgba(99, 102, 241, 0.2));
    border-color: var(--color-primary, #6366f1);
    color: var(--color-primary, #818cf8);
  }

  /* Mobile Practice & Voices Bottom Sheet */
  .mobile-drawer-body {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    display: flex;
    flex-direction: column;
    gap: 10px;
    max-height: calc(85dvh - 65px);
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    animation: drawerFadeIn 0.2s ease-out;
  }

  .mobile-sheet-header {
    position: sticky;
    top: -10px;
    z-index: 20;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin: -10px -12px 2px -12px;
    padding: 8px 12px;
    background: var(--bg-card, #151b28);
    border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
  }

  .sheet-tabs {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .sheet-tab-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: var(--bg-subtle, rgba(255, 255, 255, 0.06));
    border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
    color: var(--text-secondary, #94a3b8);
    border-radius: 8px;
    font-size: 0.78rem;
    font-weight: 600;
    padding: 6px 10px;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .sheet-tab-btn.active {
    background: var(--color-primary-light, rgba(99, 102, 241, 0.2));
    border-color: var(--color-primary, #6366f1);
    color: var(--color-primary, #a5b4fc);
  }

  .sheet-header-actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .sheet-action-link {
    background: none;
    border: none;
    color: var(--text-secondary, #94a3b8);
    font-size: 0.76rem;
    cursor: pointer;
    text-decoration: underline;
    padding: 4px;
  }

  .sheet-action-link:hover {
    color: var(--text-primary, #f8fafc);
  }

  .sheet-done-btn {
    background: var(--color-primary, #6366f1);
    color: #ffffff;
    border: none;
    font-size: 0.78rem;
    font-weight: 700;
    padding: 6px 14px;
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.15s ease, transform 0.1s ease;
  }

  .sheet-done-btn:active {
    transform: scale(0.96);
  }

  .mobile-tab-content {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .mobile-voices-content {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .mobile-voices-content .quick-solo-bar {
    padding-bottom: 4px;
  }

  .mobile-tracks-scroll {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  @keyframes drawerFadeIn {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .mobile-drawer-section {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .mobile-drawer-cluster {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }

  .drawer-btn {
    flex: 1 1 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    background: var(--bg-subtle, rgba(255, 255, 255, 0.06));
    border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
    color: var(--text-primary, #f8fafc);
    border-radius: 8px;
    font-size: 0.8rem;
    font-weight: 600;
    padding: 8px 12px;
    min-height: 42px;
    cursor: pointer;
  }

  .drawer-btn.active {
    background: var(--color-primary-light, rgba(99, 102, 241, 0.2));
    border-color: var(--color-primary, #6366f1);
    color: var(--color-primary, #a5b4fc);
  }

  .mobile-drawer-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    flex-wrap: wrap;
  }

  .drawer-label {
    font-size: 0.74rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    color: var(--text-secondary, #94a3b8);
  }

  .tempo-stepper-inline {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .stepper-btn {
    background: var(--bg-subtle, rgba(255, 255, 255, 0.08));
    border: 1px solid var(--border, rgba(255, 255, 255, 0.12));
    color: var(--text-primary, #f8fafc);
    border-radius: 6px;
    font-size: 0.8rem;
    font-weight: 600;
    min-width: 38px;
    height: 38px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .stepper-readout {
    font-size: 0.84rem;
    font-weight: 700;
    font-family: var(--font-mono, monospace);
    color: var(--color-accent, #38bdf8);
    min-width: 70px;
    text-align: center;
  }

  .reset-btn {
    background: transparent;
    border: none;
    color: var(--text-muted, #94a3b8);
    cursor: pointer;
    width: 36px;
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .mobile-select-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  .mobile-select-group {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .drawer-select {
    background: var(--input-bg, rgba(12, 15, 23, 0.8));
    border: 1px solid var(--input-border, #384666);
    color: var(--text-primary, #f8fafc);
    border-radius: 8px;
    padding: 8px 10px;
    min-height: 42px;
    font-size: 0.85rem;
    outline: none;
    width: 100%;
  }

  .drawer-vol-label {
    display: flex;
    align-items: center;
    gap: 5px;
  }

  .icon-vol-btn {
    background: transparent;
    border: none;
    color: var(--text-secondary, #94a3b8);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
  }

  .mobile-vol-slider {
    flex: 1;
    height: 6px;
    accent-color: var(--color-primary, #6366f1);
  }

  .vol-num {
    font-size: 0.78rem;
    font-family: var(--font-mono, monospace);
    color: var(--text-secondary, #94a3b8);
    min-width: 36px;
  }
}

/* ============================================================== */
/* DESKTOP VIEW STYLES (> 768px)                                  */
/* ============================================================== */
@media (min-width: 769px) {
  .desktop-player-deck {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  /* Deck Row 1: Timeline & Scrubber */
  .desktop-timeline-row {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .timeline-meta-left {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }

  .time-readout {
    font-family: var(--font-mono, monospace);
    font-size: 0.82rem;
    color: var(--text-secondary, #94a3b8);
    display: inline-flex;
    align-items: center;
    gap: 3px;
  }

  .time-current {
    color: var(--text-primary, #f8fafc);
    font-weight: 700;
  }

  .time-divider {
    opacity: 0.4;
  }

  .time-total {
    opacity: 0.75;
  }

  .measure-chip {
    font-size: 0.72rem;
    font-weight: 700;
    background: var(--bg-subtle, rgba(255, 255, 255, 0.08));
    border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
    color: var(--color-accent, #22d3ee);
    padding: 2px 7px;
    border-radius: 4px;
    letter-spacing: 0.02em;
  }

  .now-playing-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.72rem;
    color: var(--color-success, #10b981);
    background: var(--color-success-light, rgba(16, 185, 129, 0.12));
    border: 1px solid rgba(16, 185, 129, 0.3);
    padding: 2px 7px;
    border-radius: 4px;
    max-width: 160px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .playing-pulse-icon {
    animation: notePulse 1.2s infinite ease-in-out;
  }

  @keyframes notePulse {
    0%, 100% { transform: scale(1); opacity: 0.8; }
    50% { transform: scale(1.2); opacity: 1; }
  }

  .desktop-slider-container {
    flex: 1;
    position: relative;
    height: 18px;
    display: flex;
    align-items: center;
    cursor: pointer;
  }

  .progress-bar-fill {
    position: absolute;
    height: 4px;
    background: linear-gradient(90deg, var(--color-primary, #6366f1) 0%, var(--color-accent, #22d3ee) 100%);
    border-radius: 2px;
    pointer-events: none;
    z-index: 1;
  }

  .timeline-slider {
    position: relative;
    width: 100%;
    height: 4px;
    background: var(--bg-subtle, rgba(255, 255, 255, 0.12));
    border-radius: 2px;
    outline: none;
    cursor: pointer;
    margin: 0;
    accent-color: var(--color-accent, #22d3ee);
    z-index: 2;
  }

  .timeline-meta-right {
    flex-shrink: 0;
    min-width: 20px;
  }

  /* Deck Row 2: Controls */
  .desktop-controls-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: nowrap;
  }

  .transport-cluster {
    display: flex;
    align-items: center;
    gap: 5px;
    flex-shrink: 0;
  }

  .tuning-cluster {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 1;
    min-width: 0;
  }

  .utility-cluster {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }

  /* Buttons & Chips */
  .transport-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    border: 1px solid var(--border, #2e3a54);
    background: var(--bg-card, #151b28);
    color: var(--text-primary, #f8fafc);
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.15s ease;
    font-weight: 500;
    font-size: 0.78rem;
    padding: 5px 10px;
    height: 32px;
    user-select: none;
  }

  .transport-btn:hover:not(:disabled) {
    background: var(--bg-subtle, #1c2336);
    border-color: var(--color-primary, #6366f1);
    color: var(--color-primary-hover, #818cf8);
  }

  .main-play-btn {
    background: var(--color-primary, #6366f1);
    color: #ffffff;
    border: none;
    padding: 5px 14px;
    font-size: 0.82rem;
    font-weight: 600;
    min-width: 76px;
    box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
  }

  .main-play-btn:hover {
    background: var(--color-primary-hover, #4f46e5);
    color: #ffffff;
  }

  .main-play-btn.is-playing {
    background: var(--color-success, #10b981);
    box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);
  }

  .icon-btn {
    width: 32px;
    height: 32px;
    padding: 0;
  }

  .step-btn-group {
    display: inline-flex;
    gap: 3px;
  }

  .control-chip {
    display: inline-flex;
    align-items: center;
    background: var(--bg-subtle, #1c2336);
    border: 1px solid var(--border, #28334a);
    border-radius: 6px;
    height: 32px;
    padding: 0 6px;
  }

  .tempo-chip {
    gap: 3px;
    padding: 2px 4px;
    background: var(--bg-card, #151b28);
    border: 1px solid var(--border, #28334a);
    border-radius: 7px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
    transition: border-color 0.15s, box-shadow 0.15s;
  }

  .tempo-chip:hover {
    border-color: rgba(99, 102, 241, 0.35);
  }

  .tempo-chip.is-editing {
    border-color: var(--color-primary, #6366f1);
    box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
  }

  .chip-stepper-btn {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid transparent;
    color: var(--text-secondary, #94a3b8);
    cursor: pointer;
    width: 22px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 4px;
    transition: background 0.15s, color 0.15s, transform 0.1s;
    padding: 0;
  }

  .chip-stepper-btn:hover {
    background: rgba(255, 255, 255, 0.12);
    color: #ffffff;
  }

  .chip-stepper-btn:active {
    transform: scale(0.92);
  }

  .bpm-readout {
    display: inline-flex;
    align-items: baseline;
    justify-content: center;
    gap: 3px;
    padding: 0 5px;
    min-width: 60px;
    cursor: pointer;
    user-select: none;
    border-radius: 4px;
    transition: background 0.15s;
  }

  .bpm-readout:hover {
    background: rgba(255, 255, 255, 0.06);
  }

  .bpm-num {
    font-size: 0.86rem;
    font-weight: 700;
    color: var(--text-primary, #f8fafc);
    font-variant-numeric: tabular-nums;
    line-height: 1;
  }

  .bpm-suffix {
    font-size: 0.68rem;
    font-weight: 600;
    color: var(--text-muted, #94a3b8);
    letter-spacing: 0.04em;
    text-transform: uppercase;
    line-height: 1;
  }

  .bpm-inline-input {
    width: 58px;
    height: 24px;
    background: var(--input-bg, #0b0f19);
    border: 1px solid var(--color-primary, #6366f1);
    color: #ffffff;
    border-radius: 4px;
    font-size: 0.84rem;
    font-weight: 700;
    text-align: center;
    outline: none;
    padding: 0;
  }

  .tempo-divider {
    width: 1px;
    height: 14px;
    background: var(--border, #28334a);
    margin: 0 1px;
  }

  .chip-reset-btn {
    background: transparent;
    border: none;
    color: var(--text-muted, #64748b);
    cursor: pointer;
    width: 20px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 4px;
    transition: color 0.15s, background 0.15s, transform 0.2s;
    padding: 0;
  }

  .chip-reset-btn:hover {
    color: var(--color-primary, #818cf8);
    background: rgba(255, 255, 255, 0.06);
    transform: rotate(-30deg);
  }

  .select-chip {
    padding: 0;
  }

  .deck-select {
    background: transparent;
    border: none;
    color: var(--text-primary, #f8fafc);
    font-size: 0.76rem;
    font-weight: 500;
    padding: 4px 8px;
    cursor: pointer;
    outline: none;
    max-width: 140px;
  }

  .deck-select option,
  .deck-select optgroup {
    background: var(--bg-card, #151b28);
    color: var(--text-primary, #f8fafc);
  }

  .reverb-select {
    max-width: 120px;
  }

  .volume-chip {
    gap: 6px;
    padding: 0 8px;
  }

  .deck-volume-slider {
    width: 60px;
    height: 4px;
    accent-color: var(--color-primary, #6366f1);
    cursor: pointer;
  }

  .deck-volume-text {
    font-size: 0.72rem;
    font-family: var(--font-mono, monospace);
    color: var(--text-secondary, #94a3b8);
    min-width: 28px;
  }

  .tracks-btn.active {
    background: var(--color-primary-light, rgba(99, 102, 241, 0.15));
    border-color: var(--color-primary, #6366f1);
    color: var(--color-primary-hover, #818cf8);
  }

  .tracks-btn.has-solo {
    background: rgba(245, 158, 11, 0.15);
    border-color: #f59e0b;
    color: #f59e0b;
  }

  .mini-solo-indicator {
    background: #f59e0b;
    color: #1e293b;
    font-size: 0.62rem;
    font-weight: 800;
    padding: 0 4px;
    border-radius: 3px;
    text-transform: uppercase;
  }

  .deck-toggle-group {
    display: inline-flex;
    gap: 3px;
  }

  .icon-tool-btn {
    width: 32px;
    height: 32px;
    padding: 0;
  }

  .icon-tool-btn.active {
    background: var(--color-primary-light, rgba(99, 102, 241, 0.18));
    border-color: var(--color-primary, #6366f1);
    color: var(--color-primary, #818cf8);
  }

  .autoscroll-toggle-btn.suspended {
    background: rgba(245, 158, 11, 0.15);
    border-color: rgba(245, 158, 11, 0.5);
    color: #f59e0b;
  }

  .export-wav-btn,
  .rehearsal-btn {
    font-size: 0.76rem;
  }

  .desktop-btn-text {
    max-width: 90px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Compact Sticky Scrolling Modifier on Desktop */
  .audio-player-card.is-sticky-compact {
    padding: 6px 12px;
    box-shadow: 0 8px 26px rgba(0, 0, 0, 0.4);
    border-color: var(--border-focus, #6366f1);
  }

  .audio-player-card.is-sticky-compact .reverb-select,
  .audio-player-card.is-sticky-compact .export-wav-btn .desktop-btn-text,
  .audio-player-card.is-sticky-compact .rehearsal-btn .desktop-btn-text {
    display: none;
  }
}

/* ============================================================== */
/* SHARED STEMS & TRACKS MIXER PANEL                              */
/* ============================================================== */
.tracks-mixer-panel {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border, #28334a);
  animation: fadeIn 0.15s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

.mixer-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}

.quick-solo-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.quick-solo-label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text-secondary, #94a3b8);
  margin-right: 4px;
}

.solo-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border-radius: 20px;
  font-size: 0.76rem;
  font-weight: 600;
  border: 1px solid var(--border, #28334a);
  background: var(--bg-card, #151b28);
  color: var(--text-primary, #f8fafc);
  cursor: pointer;
  transition: all 0.15s ease;
}

.voice-pill-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  font-size: 0.64rem;
  font-weight: 800;
  line-height: 1;
  text-transform: uppercase;
}

.solo-pill.tag-s .voice-pill-tag,
.solo-pill.tag-s1 .voice-pill-tag,
.solo-pill.tag-s2 .voice-pill-tag { background: #f43f5e; color: #ffffff; }
.solo-pill.tag-a .voice-pill-tag,
.solo-pill.tag-a1 .voice-pill-tag,
.solo-pill.tag-a2 .voice-pill-tag { background: #8b5cf6; color: #ffffff; }
.solo-pill.tag-t .voice-pill-tag,
.solo-pill.tag-t1 .voice-pill-tag,
.solo-pill.tag-t2 .voice-pill-tag { background: #06b6d4; color: #ffffff; }
.solo-pill.tag-b .voice-pill-tag,
.solo-pill.tag-b1 .voice-pill-tag,
.solo-pill.tag-b2 .voice-pill-tag { background: #3b82f6; color: #ffffff; }
.solo-pill.tag-bar .voice-pill-tag { background: #6366f1; color: #ffffff; }
.solo-pill.tag-ms .voice-pill-tag { background: #d946ef; color: #ffffff; }
.solo-pill.tag-pno .voice-pill-tag,
.solo-pill.tag-piano .voice-pill-tag { background: #f59e0b; color: #1e293b; }
.solo-pill.tag-org .voice-pill-tag { background: #b45309; color: #ffffff; }
.solo-pill.tag-v .voice-pill-tag { background: #10b981; color: #ffffff; }

.solo-pill:hover {
  background: var(--bg-subtle, #1c2336);
  border-color: var(--color-primary, #6366f1);
}

.solo-pill.active {
  background: var(--color-warning, #f59e0b);
  border-color: #d97706;
  color: #1e293b;
  box-shadow: 0 2px 6px rgba(245, 158, 11, 0.3);
}

.solo-pill.active .voice-pill-tag {
  background: rgba(0, 0, 0, 0.25);
  color: #ffffff;
}

.mixer-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mixer-text-btn {
  background: none;
  border: none;
  color: var(--text-secondary, #94a3b8);
  font-size: 0.78rem;
  cursor: pointer;
  text-decoration: underline;
}

.mixer-text-btn:hover {
  color: var(--text-primary, #f8fafc);
}

.mixer-close-btn {
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #28334a);
  color: var(--text-primary, #f8fafc);
  font-size: 0.76rem;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 4px;
  cursor: pointer;
}

/* Tracks Grid */
.tracks-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
}

.track-card {
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #28334a);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: all 0.15s ease;
}

.track-card:hover {
  border-color: var(--border-focus, #6366f1);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.track-card.is-soloed {
  border-color: var(--color-warning, #f59e0b);
  background: rgba(245, 158, 11, 0.08);
  box-shadow: 0 2px 10px rgba(245, 158, 11, 0.15);
}

.track-card.is-muted {
  opacity: 0.6;
}

.track-card.is-inaudible {
  opacity: 0.45;
}

.track-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.track-title-wrapper {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.track-voice-tag-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.65rem;
  font-weight: 800;
  padding: 1px 6px;
  border-radius: 4px;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  flex-shrink: 0;
}

.track-voice-tag-badge.tag-s,
.track-voice-tag-badge.tag-s1,
.track-voice-tag-badge.tag-s2 { background: #f43f5e; color: #ffffff; }
.track-voice-tag-badge.tag-a,
.track-voice-tag-badge.tag-a1,
.track-voice-tag-badge.tag-a2 { background: #8b5cf6; color: #ffffff; }
.track-voice-tag-badge.tag-t,
.track-voice-tag-badge.tag-t1,
.track-voice-tag-badge.tag-t2 { background: #06b6d4; color: #ffffff; }
.track-voice-tag-badge.tag-b,
.track-voice-tag-badge.tag-b1,
.track-voice-tag-badge.tag-b2 { background: #3b82f6; color: #ffffff; }
.track-voice-tag-badge.tag-bar { background: #6366f1; color: #ffffff; }
.track-voice-tag-badge.tag-ms { background: #d946ef; color: #ffffff; }
.track-voice-tag-badge.tag-pno,
.track-voice-tag-badge.tag-piano { background: #f59e0b; color: #1e293b; }
.track-voice-tag-badge.tag-org { background: #b45309; color: #ffffff; }
.track-voice-tag-badge.tag-v { background: #10b981; color: #ffffff; }

.track-name {
  font-size: 0.84rem;
  font-weight: 600;
  color: var(--text-primary, #f8fafc);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.track-part-badge {
  font-size: 0.65rem;
  font-weight: 700;
  background: var(--bg-elevated, #222c42);
  color: var(--text-secondary, #94a3b8);
  padding: 1px 5px;
  border-radius: 3px;
}

.track-btn-group {
  display: flex;
  gap: 3px;
}

.track-action-btn {
  width: 28px;
  height: 28px;
  min-width: 28px;
  min-height: 28px;
  border-radius: 4px;
  font-size: 0.74rem;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border, #28334a);
  background: var(--bg-card, #151b28);
  color: var(--text-secondary, #94a3b8);
  transition: all 0.15s;
}

.solo-btn:hover {
  background: rgba(245, 158, 11, 0.2);
  border-color: #f59e0b;
  color: #f59e0b;
}

.solo-btn.active {
  background: var(--color-warning, #f59e0b);
  border-color: #d97706;
  color: #1e293b;
}

.mute-btn:hover {
  background: rgba(239, 68, 68, 0.2);
  border-color: #ef4444;
  color: #ef4444;
}

.mute-btn.active {
  background: var(--color-danger, #ef4444);
  border-color: #dc2626;
  color: #ffffff;
}

.track-card-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.track-control-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.track-label {
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--text-secondary, #94a3b8);
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.track-instrument-select {
  background: var(--input-bg, #0c0f17);
  border: 1px solid var(--input-border, #384666);
  border-radius: 4px;
  padding: 3px 6px;
  font-size: 0.76rem;
  color: var(--text-primary, #f8fafc);
  outline: none;
  cursor: pointer;
  width: 100%;
}

.track-vol-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.track-vol-text {
  font-size: 0.7rem;
  font-family: var(--font-mono, monospace);
  color: var(--text-secondary, #94a3b8);
}

.track-slider {
  width: 100%;
  height: 4px;
  accent-color: var(--color-primary, #6366f1);
  cursor: pointer;
}

.pan-slider { accent-color: #06b6d4; }
.reverb-slider { accent-color: #8b5cf6; }

/* Feedback icons */
.export-feedback {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.74rem;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
}

.success-feedback {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
}

.error-feedback {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.spin-icon {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.voicing-mode-toggle-group {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.voicing-toggle-pill {
  padding: 0.25rem 0.6rem;
  font-size: 0.74rem;
  font-weight: 500;
  border-radius: 6px;
  border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
  background: var(--bg-app, #0b1120);
  color: var(--text-muted, #94a3b8);
  cursor: pointer;
  transition: all 0.15s ease;
}

.voicing-toggle-pill:hover {
  color: #fff;
  border-color: rgba(255, 255, 255, 0.25);
}

.voicing-toggle-pill.active {
  background: rgba(56, 189, 248, 0.15);
  border-color: #38bdf8;
  color: #38bdf8;
  font-weight: 600;
}

.mobile-voicing-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.4rem 0.75rem;
  margin-bottom: 0.5rem;
  background: var(--bg-card, #131b2e);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  border-radius: 6px;
}
</style>
