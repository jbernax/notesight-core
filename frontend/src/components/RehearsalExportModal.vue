<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import {
  X,
  Headphones,
  Download,
  Archive,
  Check,
  Loader2,
  Play,
  RotateCcw,
  Info
} from 'lucide-vue-next'
import {
  ScorePlaybackController,
  type TrackConfig,
  type RehearsalProgress,
  type RehearsalRenderResult
} from '../audio/scorePlayer'
import { INSTRUMENT_OPTIONS, type InstrumentType } from '../audio/synth'
import { downloadAudioBlob } from '../audio/wavEncoder'
import { t } from '../i18n'

const props = defineProps<{
  isOpen: boolean
  player: ScorePlaybackController
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

// Configuration State (Matching user example: Lead 100% Piano, Background 10% Flute)
const leadVolume = ref<number>(100)
const leadInstrument = ref<InstrumentType | 'original'>('piano')
const backgroundVolume = ref<number>(10)
const backgroundInstrument = ref<InstrumentType | 'original' | 'muted'>('flute')
const rehearsalTempo = ref<number>(100)
const downloadFormat = ref<'zip' | 'wav'>('zip')
const scoreTitleInput = ref<string>('')

// Selected Tracks
const selectedTrackIds = ref<string[]>([])
const tracks = computed<TrackConfig[]>(() => props.player.getTracks())

// Progress & Status
const isRendering = ref<boolean>(false)
const progress = ref<RehearsalProgress | null>(null)
const feedbackMessage = ref<string | null>(null)
const errorMessage = ref<string | null>(null)
const singleRenderingTrackId = ref<string | null>(null)

// Voicing Mode override (Choir SATB vs Keyboard)
const canSplitChoralVoices = computed(() => props.player.canSplitChoralVoices())
const currentVoicingMode = ref<'auto' | 'choral' | 'keyboard'>(props.player.getVoicingMode())

const setVoicing = (mode: 'choral' | 'keyboard') => {
  currentVoicingMode.value = mode
  props.player.setVoicingMode(mode)
  const newTracks = props.player.getTracks()
  selectedTrackIds.value = newTracks.map((t) => t.id)
}

// Initialize tracks, tempo, and score title when modal opens
watch(
  () => props.isOpen,
  (open) => {
    if (open) {
      const allTracks = props.player.getTracks()
      selectedTrackIds.value = allTracks.map((t) => t.id)
      rehearsalTempo.value = props.player.getSnapshot().bpm || 100
      const currentTitle = props.player.getScoreTitle() || props.player.getSnapshot().title
      scoreTitleInput.value = currentTitle && currentTitle !== 'score' && currentTitle !== 'NoteSight Score'
        ? currentTitle
        : ''
      feedbackMessage.value = null
      errorMessage.value = null
      progress.value = null

      // If player has 0 duration, attempt self-healing reload if OSMD instance is attached
      if (props.player.getTotalDurationSeconds() <= 0 && (props.player as any).osmd) {
        try {
          props.player.loadScore((props.player as any).osmd)
          const refreshedTracks = props.player.getTracks()
          if (refreshedTracks.length > 0 && selectedTrackIds.value.length === 0) {
            selectedTrackIds.value = refreshedTracks.map((t) => t.id)
          }
        } catch {}
      }
    }
  },
  { immediate: true }
)

const effectiveScoreTitle = computed<string>(() => {
  const custom = scoreTitleInput.value.trim()
  if (custom) return custom
  const current = props.player.getScoreTitle() || props.player.getSnapshot().title
  if (current && current !== 'score' && current !== 'NoteSight Score') return current
  return 'score'
})

const isAllSelected = computed(
  () => tracks.value.length > 0 && selectedTrackIds.value.length === tracks.value.length
)

const toggleTrack = (trackId: string) => {
  if (selectedTrackIds.value.includes(trackId)) {
    selectedTrackIds.value = selectedTrackIds.value.filter((id) => id !== trackId)
  } else {
    selectedTrackIds.value.push(trackId)
  }
}

const selectAllTracks = () => {
  selectedTrackIds.value = tracks.value.map((t) => t.id)
}

const deselectAllTracks = () => {
  selectedTrackIds.value = []
}

// Generate expected filename preview for a track (strictly .mp3)
const getTrackFilenamePreview = (track: TrackConfig): string => {
  const safeScore = effectiveScoreTitle.value.replace(/[^a-zA-Z0-9_\-\s]/g, '').replace(/\s+/g, '_') || 'score'
  const rawVoice = track.displayName || track.name
  const safeVoice = rawVoice.trim().replace(/[^a-zA-Z0-9_\-\s]/g, '').replace(/\s+/g, '_')
  return `${safeScore}_${safeVoice}_rehearsal.mp3`
}

const getZipFilenamePreview = computed<string>(() => {
  const safeScore = effectiveScoreTitle.value.replace(/[^a-zA-Z0-9_\-\s]/g, '').replace(/\s+/g, '_') || 'score'
  return `${safeScore}_rehearsal_tracks.zip`
})

// Estimated size and savings indicator (strict 128 kbps MP3)
const estimatedExportStats = computed(() => {
  const count = selectedTrackIds.value.length
  if (count === 0) return null

  const durationSec = props.player.getTotalDurationSeconds() || 120
  const durationMin = Math.max(0.2, durationSec / 60)

  // 128 kbps MP3: ~0.96 MB per min per track
  const mbPerMin = 0.96
  const rawTotalMB = count * durationMin * mbPerMin

  const isZip = downloadFormat.value === 'zip'
  const effectiveMB = isZip ? rawTotalMB * 0.98 : rawTotalMB

  const displayMB = effectiveMB < 1 ? effectiveMB.toFixed(1) : Math.round(effectiveMB).toString()
  const wavZipMB = Math.round(count * durationMin * 10.58 * (isZip ? 0.75 : 1))

  return {
    sizeDisplay: `~${displayMB} MB`,
    savingsPercent: Math.max(85, Math.min(95, Math.round((1 - (effectiveMB / Math.max(1, wavZipMB))) * 100))),
    rawWavMB: `~${wavZipMB} MB`,
  }
})

// Audition live in the player
const handleAudition = (trackId: string) => {
  try {
    props.player.applyRehearsalMix(
      trackId,
      leadVolume.value,
      leadInstrument.value,
      backgroundVolume.value,
      backgroundInstrument.value
    )
    feedbackMessage.value = t('player.rehearsalMixApplied')
    setTimeout(() => {
      feedbackMessage.value = null
    }, 4000)
  } catch (err: any) {
    errorMessage.value = err?.message || 'Failed to apply rehearsal mix'
  }
}

// Download single track directly (MP3)
const handleDownloadSingleTrack = async (track: TrackConfig) => {
  if (isRendering.value || singleRenderingTrackId.value) return
  singleRenderingTrackId.value = track.id
  errorMessage.value = null
  feedbackMessage.value = null

  try {
    const result: RehearsalRenderResult = await props.player.renderRehearsalTrack({
      leadTrackId: track.id,
      leadVolume: leadVolume.value,
      leadInstrument: leadInstrument.value,
      backgroundVolume: backgroundVolume.value,
      backgroundInstrument: backgroundInstrument.value,
      tempoBpm: rehearsalTempo.value,
      scoreTitle: effectiveScoreTitle.value,
    })
    downloadAudioBlob(result.blob, result.filename)
    feedbackMessage.value = `Downloaded ${result.filename}`
    setTimeout(() => {
      feedbackMessage.value = null
    }, 4000)
  } catch (err: any) {
    console.error('Rehearsal export error:', err)
    errorMessage.value = err?.message || 'Failed to export rehearsal track'
  } finally {
    singleRenderingTrackId.value = null
  }
}

// Download all selected tracks (ZIP or simultaneous individual MP3s)
const handleDownloadAll = async () => {
  if (isRendering.value || selectedTrackIds.value.length === 0) return
  isRendering.value = true
  errorMessage.value = null
  feedbackMessage.value = null

  try {
    const isZip = downloadFormat.value === 'zip'
    const result = await props.player.exportRehearsalTracksBatch({
      selectedTrackIds: selectedTrackIds.value,
      leadVolume: leadVolume.value,
      leadInstrument: leadInstrument.value,
      backgroundVolume: backgroundVolume.value,
      backgroundInstrument: backgroundInstrument.value,
      tempoBpm: rehearsalTempo.value,
      scoreTitle: effectiveScoreTitle.value,
      downloadAsZip: isZip,
      downloadDirect: true,
      onProgress: (p) => {
        progress.value = p
      },
    })

    const count = result.results.length
    if (isZip && result.zipFilename) {
      feedbackMessage.value = `Successfully exported ${count} voices in ${result.zipFilename}!`
    } else {
      feedbackMessage.value = `Successfully downloaded ${count} rehearsal audio tracks!`
    }

    setTimeout(() => {
      feedbackMessage.value = null
      progress.value = null
    }, 6000)
  } catch (err: any) {
    console.error('Batch rehearsal export error:', err)
    errorMessage.value = err?.message || 'Failed to generate rehearsal tracks'
  } finally {
    isRendering.value = false
  }
}

const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && props.isOpen && !isRendering.value) {
    emit('close')
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <teleport to="body">
    <div v-if="isOpen" class="rehearsal-modal-backdrop" @click.self="!isRendering && emit('close')">
      <div class="rehearsal-modal-container" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <!-- Modal Header -->
      <div class="modal-header">
        <div class="header-title-row">
          <div class="icon-avatar">
            <Headphones :size="20" class="primary-icon" />
          </div>
          <div>
            <h2 id="modal-title" class="title">{{ t('player.rehearsalModalTitle') }}</h2>
            <p class="subtitle">{{ t('player.rehearsalModalSubtitle') }}</p>
          </div>
        </div>
        <button
          class="btn-close"
          :disabled="isRendering"
          @click="emit('close')"
          aria-label="Close dialog"
        >
          <X :size="18" />
        </button>
      </div>

      <!-- Feedback / Alerts -->
      <div v-if="feedbackMessage" class="alert-box alert-success">
        <Check :size="16" />
        <span>{{ feedbackMessage }}</span>
      </div>
      <div v-if="errorMessage" class="alert-box alert-error">
        <Info :size="16" />
        <span>{{ errorMessage }}</span>
      </div>

      <div class="modal-body">
        <!-- Score Title / Prefix Row -->
        <div class="score-naming-row">
          <div class="naming-label-wrap">
            <span class="naming-title">{{ t('player.scoreName') }}:</span>
            <span class="naming-hint">{{ t('player.scoreNameHint') }}</span>
          </div>
          <input
            v-model="scoreTitleInput"
            type="text"
            :placeholder="effectiveScoreTitle"
            class="score-title-input"
            :disabled="isRendering"
          />
        </div>

        <!-- Rehearsal Mixer Balance Configuration -->
        <div class="config-grid">
          <!-- Main Voice Card -->
          <div class="config-card lead-card">
            <div class="config-card-header">
              <span class="badge-role lead-badge">{{ t('player.leadBadge') }} {{ leadVolume }}%</span>
              <h3 class="card-title">{{ t('player.mainVoiceConfig') }}</h3>
            </div>
            <p class="card-desc">{{ t('player.leadVoiceDesc') }}</p>

            <div class="form-row">
              <label class="form-label">
                <span>{{ t('player.leadVolume') }}</span>
                <span class="val-display">{{ leadVolume }}%</span>
              </label>
              <input
                v-model.number="leadVolume"
                type="range"
                min="10"
                max="100"
                step="5"
                class="range-slider range-primary"
              />
            </div>

            <div class="form-row">
              <label class="form-label">
                <span>{{ t('player.leadInstrument') }}</span>
              </label>
              <select v-model="leadInstrument" class="select-input">
                <option value="original">{{ t('player.originalInstrument') }}</option>
                <option v-for="inst in INSTRUMENT_OPTIONS" :key="inst.id" :value="inst.id">
                  {{ inst.name }}
                </option>
              </select>
            </div>
          </div>

          <!-- Other Voices Card -->
          <div class="config-card background-card">
            <div class="config-card-header">
              <span class="badge-role bg-badge">{{ t('player.backgroundBadge') }} {{ backgroundVolume }}%</span>
              <h3 class="card-title">{{ t('player.otherVoicesConfig') }}</h3>
            </div>
            <p class="card-desc">{{ t('player.otherVoicesDesc') }}</p>

            <div class="form-row">
              <label class="form-label">
                <span>{{ t('player.backgroundVolume') }}</span>
                <span class="val-display">{{ backgroundVolume }}%</span>
              </label>
              <input
                v-model.number="backgroundVolume"
                type="range"
                min="0"
                max="50"
                step="5"
                class="range-slider range-secondary"
              />
            </div>

            <div class="form-row">
              <label class="form-label">
                <span>{{ t('player.backgroundInstrument') }}</span>
              </label>
              <select v-model="backgroundInstrument" class="select-input">
                <option value="original">{{ t('player.originalInstrument') }}</option>
                <option value="muted">{{ t('player.mutedInstrument') }}</option>
                <option v-for="inst in INSTRUMENT_OPTIONS" :key="inst.id" :value="inst.id">
                  {{ inst.name }}
                </option>
              </select>
            </div>
          </div>
        </div>

        <!-- Practice Tempo Row -->
        <div class="tempo-config-row">
          <div class="tempo-label-wrap">
            <span class="tempo-title">{{ t('player.rehearsalTempo') }}:</span>
            <span class="tempo-desc">{{ t('player.rehearsalTempoDesc') }}</span>
          </div>
          <div class="tempo-stepper">
            <button
              type="button"
              class="stepper-btn"
              @click="rehearsalTempo = Math.max(30, rehearsalTempo - 5)"
              :disabled="isRendering"
            >
              −
            </button>
            <input
              v-model.number="rehearsalTempo"
              type="number"
              min="30"
              max="280"
              class="tempo-input"
            />
            <span class="bpm-unit">BPM</span>
            <button
              type="button"
              class="stepper-btn"
              @click="rehearsalTempo = Math.min(280, rehearsalTempo + 5)"
              :disabled="isRendering"
            >
              +
            </button>
            <button
              type="button"
              class="btn-reset-tempo"
              @click="rehearsalTempo = player.getSnapshot().bpm || 100"
              :title="t('player.resetScoreTempo')"
              :disabled="isRendering"
            >
              <RotateCcw :size="13" />
            </button>
          </div>
        </div>

        <!-- Voices List & Selection -->
        <div class="voices-section">
          <div v-if="canSplitChoralVoices" class="voicing-mode-banner">
            <span class="voicing-mode-label">Voicing Mode:</span>
            <div class="voicing-toggle-pills">
              <button
                type="button"
                class="voicing-pill-btn"
                :class="{ active: currentVoicingMode === 'choral' || (currentVoicingMode === 'auto' && tracks.length > 1) }"
                @click="setVoicing('choral')"
                :disabled="isRendering"
              >
                Choir (SATB / Split)
              </button>
              <button
                type="button"
                class="voicing-pill-btn"
                :class="{ active: currentVoicingMode === 'keyboard' || (currentVoicingMode === 'auto' && tracks.length <= 1) }"
                @click="setVoicing('keyboard')"
                :disabled="isRendering"
              >
                Keyboard (Single Track)
              </button>
            </div>
          </div>

          <div class="voices-header">
            <h3 class="voices-title">
              {{ t('player.voicesToExport') }} ({{ selectedTrackIds.length }}/{{ tracks.length }})
            </h3>
            <div class="selection-actions">
              <button
                type="button"
                class="text-btn"
                @click="selectAllTracks"
                :disabled="isAllSelected || isRendering"
              >
                {{ t('player.selectAll') }}
              </button>
              <span class="sep">•</span>
              <button
                type="button"
                class="text-btn"
                @click="deselectAllTracks"
                :disabled="selectedTrackIds.length === 0 || isRendering"
              >
                {{ t('player.deselectAll') }}
              </button>
            </div>
          </div>

          <div class="voices-table-container">
            <div
              v-for="track in tracks"
              :key="track.id"
              class="voice-item"
              :class="{ 'is-selected': selectedTrackIds.includes(track.id) }"
            >
              <label class="voice-checkbox-label">
                <input
                  type="checkbox"
                  :checked="selectedTrackIds.includes(track.id)"
                  @change="toggleTrack(track.id)"
                  :disabled="isRendering"
                  class="checkbox"
                />
                <span
                  v-if="track.voiceTag"
                  class="voice-tag-badge"
                  :class="`tag-${track.voiceTag.toLowerCase().replace(/[^a-z0-9]/g, '')}`"
                >
                  {{ track.voiceTag }}
                </span>
                <span class="voice-name">{{ track.displayName || track.name }}</span>
              </label>

              <span class="voice-filename-preview" :title="getTrackFilenamePreview(track)">
                {{ getTrackFilenamePreview(track) }}
              </span>

              <div class="voice-row-actions">
                <button
                  type="button"
                  class="btn-audition"
                  @click="handleAudition(track.id)"
                  :title="t('player.testInPlayer')"
                  :disabled="isRendering"
                >
                  <Play :size="12" />
                  <span>{{ t('player.testInPlayer') }}</span>
                </button>

                <button
                  type="button"
                  class="btn-single-download"
                  @click="handleDownloadSingleTrack(track)"
                  :title="`${t('player.downloadTrack')} ${track.name} (.MP3)`"
                  :disabled="isRendering || singleRenderingTrackId === track.id"
                >
                  <Loader2 v-if="singleRenderingTrackId === track.id" class="spin-icon" :size="13" />
                  <Download v-else :size="13" />
                  <span>{{ t('player.downloadTrack') }}</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Progress Bar when rendering -->
        <div v-if="isRendering && progress" class="render-progress-card">
          <div class="progress-info-row">
            <span class="progress-task">
              <Loader2 class="spin-icon" :size="14" />
              <strong>{{ progress.currentTrackName }}</strong> ({{ progress.currentTrackIndex }}/{{ progress.totalTracks }})
            </span>
            <span class="progress-percent">{{ progress.percent }}%</span>
          </div>
          <div class="progress-bar-bg">
            <div class="progress-bar-fill" :style="{ width: `${progress.percent}%` }"></div>
          </div>
        </div>
      </div>

      <!-- Modal Footer -->
      <div class="modal-footer">
        <div class="export-options-cluster">
          <!-- Packaging & Size Estimate (Strict MP3 128 kbps) -->
          <div class="packaging-row">
            <div class="format-picker">
              <label class="radio-label">
                <input
                  type="radio"
                  value="zip"
                  v-model="downloadFormat"
                  :disabled="isRendering"
                />
                <Archive :size="14" />
                <span>{{ t('player.zipArchive') }} ({{ getZipFilenamePreview }})</span>
              </label>
              <label class="radio-label">
                <input
                  type="radio"
                  value="wav"
                  v-model="downloadFormat"
                  :disabled="isRendering"
                />
                <Download :size="14" />
                <span>{{ t('player.individualTracks') || t('player.individualWavs') || 'Individual MP3s' }}</span>
              </label>
            </div>

            <!-- MP3 128 kbps Format & Size Badge -->
            <div class="format-info-pill">
              <span class="format-name-badge">MP3 128 kbps</span>
              <div v-if="estimatedExportStats" class="size-estimate-badge is-savings">
                <span class="size-label">{{ t('player.estimatedSize') || 'Est. Size' }}:</span>
                <strong class="size-val">{{ estimatedExportStats.sizeDisplay }}</strong>
                <span class="savings-pill">
                  {{ estimatedExportStats.savingsPercent }}% smaller
                </span>
              </div>
            </div>
          </div>
        </div>

        <div class="footer-buttons">
          <button
            type="button"
            class="btn-secondary"
            @click="emit('close')"
            :disabled="isRendering"
          >
            {{ t('common.close') || 'Close' }}
          </button>

          <button
            type="button"
            class="btn-primary"
            :disabled="isRendering || selectedTrackIds.length === 0"
            @click="handleDownloadAll"
          >
            <Loader2 v-if="isRendering" class="spin-icon" :size="16" />
            <Archive v-else-if="downloadFormat === 'zip'" :size="16" />
            <Download v-else :size="16" />
            <span>
              {{ isRendering ? t('player.renderingRehearsal') : downloadFormat === 'zip' ? t('player.downloadAllZip') : `${t('player.downloadTrack')} All (.MP3)` }}
              ({{ selectedTrackIds.length }})
            </span>
          </button>
        </div>
      </div>
    </div>
  </div>
  </teleport>
</template>

<style scoped>
.rehearsal-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 10050;
  background: rgba(10, 15, 29, 0.75);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.25rem;
}

.rehearsal-modal-container {
  background: var(--bg-card, #131b2e);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
  border-radius: 14px;
  width: 100%;
  max-width: 780px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.45);
  overflow: hidden;
  color: var(--text-primary, #f8fafc);
}

.modal-header {
  padding: 1.25rem 1.5rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  background: var(--bg-elevated, #1a243a);
}

.header-title-row {
  display: flex;
  align-items: center;
  gap: 0.85rem;
}

.icon-avatar {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: rgba(56, 189, 248, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #38bdf8;
}

.title {
  margin: 0;
  font-size: 1.2rem;
  font-weight: 700;
}

.subtitle {
  margin: 0.15rem 0 0;
  font-size: 0.85rem;
  color: var(--text-secondary, #94a3b8);
}

.btn-close {
  background: transparent;
  border: none;
  color: var(--text-muted, #64748b);
  cursor: pointer;
  padding: 0.4rem;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}

.btn-close:hover:not(:disabled) {
  color: var(--text-primary, #f8fafc);
  background: rgba(255, 255, 255, 0.08);
}

.modal-body {
  padding: 1.25rem 1.5rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.alert-box {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.75rem 1rem;
  margin: 0.75rem 1.5rem 0;
  border-radius: 8px;
  font-size: 0.88rem;
}

.alert-success {
  background: rgba(34, 197, 94, 0.15);
  border: 1px solid rgba(34, 197, 94, 0.35);
  color: #4ade80;
}

.alert-error {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.35);
  color: #f87171;
}

/* Score Naming Row */
.score-naming-row {
  background: var(--bg-app, #0b1120);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  border-radius: 10px;
  padding: 0.85rem 1.1rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

@media (max-width: 640px) {
  .score-naming-row {
    flex-direction: column;
    align-items: flex-start;
  }
}

.naming-label-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.naming-title {
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--text-primary, #f8fafc);
}

.naming-hint {
  font-size: 0.74rem;
  color: var(--text-muted, #64748b);
}

.score-title-input {
  flex: 1;
  max-width: 320px;
  background: var(--bg-card, #131b2e);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.15));
  border-radius: 6px;
  color: var(--text-primary, #f8fafc);
  padding: 0.5rem 0.75rem;
  font-size: 0.85rem;
  font-weight: 500;
  outline: none;
  transition: border-color 0.15s ease;
}

.score-title-input:focus {
  border-color: #38bdf8;
}

/* Config Grid */
.config-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

@media (max-width: 640px) {
  .config-grid {
    grid-template-columns: 1fr;
  }
}

.config-card {
  background: var(--bg-app, #0b1120);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  border-radius: 10px;
  padding: 1.1rem;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.lead-card {
  border-left: 3px solid #38bdf8;
}

.background-card {
  border-left: 3px solid #a855f7;
}

.config-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.badge-role {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
}

.lead-badge {
  background: rgba(56, 189, 248, 0.2);
  color: #38bdf8;
}

.bg-badge {
  background: rgba(168, 85, 247, 0.2);
  color: #c084fc;
}

.card-title {
  margin: 0;
  font-size: 0.98rem;
  font-weight: 600;
}

.card-desc {
  margin: 0;
  font-size: 0.78rem;
  color: var(--text-muted, #64748b);
  line-height: 1.35;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.form-label {
  display: flex;
  justify-content: space-between;
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--text-secondary, #94a3b8);
}

.val-display {
  font-weight: 700;
  color: var(--text-primary, #f8fafc);
}

.range-slider {
  width: 100%;
  height: 6px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.1);
  outline: none;
  cursor: pointer;
  accent-color: #38bdf8;
}

.range-secondary {
  accent-color: #a855f7;
}

.select-input {
  background: var(--bg-card, #131b2e);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.12));
  color: var(--text-primary, #f8fafc);
  padding: 0.5rem 0.65rem;
  border-radius: 6px;
  font-size: 0.85rem;
  outline: none;
}

.select-input:focus {
  border-color: #38bdf8;
}

/* Practice Tempo Row */
.tempo-config-row {
  background: var(--bg-app, #0b1120);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  border-radius: 10px;
  padding: 0.85rem 1.1rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.tempo-label-wrap {
  display: flex;
  flex-direction: column;
}

.tempo-title {
  font-size: 0.9rem;
  font-weight: 600;
}

.tempo-desc {
  font-size: 0.75rem;
  color: var(--text-muted, #64748b);
}

.tempo-stepper {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.stepper-btn {
  width: 28px;
  height: 28px;
  background: var(--bg-elevated, #1a243a);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
  border-radius: 6px;
  color: var(--text-primary, #f8fafc);
  cursor: pointer;
  font-size: 1rem;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}

.stepper-btn:hover:not(:disabled) {
  background: #38bdf8;
  color: #0b1120;
}

.tempo-input {
  width: 55px;
  padding: 0.35rem 0.4rem;
  text-align: center;
  background: var(--bg-card, #131b2e);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.15));
  border-radius: 6px;
  color: var(--text-primary, #f8fafc);
  font-size: 0.88rem;
  font-weight: 700;
}

.bpm-unit {
  font-size: 0.75rem;
  color: var(--text-muted, #64748b);
  margin-right: 0.35rem;
}

.btn-reset-tempo {
  background: transparent;
  border: none;
  color: var(--text-muted, #64748b);
  cursor: pointer;
  padding: 0.35rem;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-reset-tempo:hover:not(:disabled) {
  color: #38bdf8;
}

/* Voices Section */
.voices-section {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.voicing-mode-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  background: var(--bg-card, #131b2e);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  border-radius: 8px;
  padding: 0.5rem 0.75rem;
  margin-bottom: 0.75rem;
}

.voicing-mode-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-muted, #94a3b8);
}

.voicing-toggle-pills {
  display: flex;
  gap: 0.35rem;
}

.voicing-pill-btn {
  padding: 0.3rem 0.65rem;
  font-size: 0.76rem;
  font-weight: 500;
  border-radius: 6px;
  border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
  background: var(--bg-app, #0b1120);
  color: var(--text-muted, #94a3b8);
  cursor: pointer;
  transition: all 0.15s ease;
}

.voicing-pill-btn:hover:not(:disabled) {
  color: #fff;
  border-color: rgba(255, 255, 255, 0.25);
}

.voicing-pill-btn.active {
  background: rgba(56, 189, 248, 0.15);
  border-color: #38bdf8;
  color: #38bdf8;
  font-weight: 600;
}

.voices-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.voices-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
}

.selection-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.text-btn {
  background: transparent;
  border: none;
  color: #38bdf8;
  cursor: pointer;
  font-size: 0.78rem;
  padding: 0;
  text-decoration: underline;
}

.text-btn:hover:not(:disabled) {
  color: #7dd3fc;
}

.sep {
  color: var(--text-muted, #64748b);
  font-size: 0.75rem;
}

.voices-table-container {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  max-height: 230px;
  overflow-y: auto;
  border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  border-radius: 8px;
  padding: 0.5rem;
  background: var(--bg-app, #0b1120);
}

.voice-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.5rem 0.65rem;
  border-radius: 6px;
  background: var(--bg-card, #131b2e);
  transition: all 0.15s ease;
}

.voice-item.is-selected {
  border-left: 3px solid #38bdf8;
}

.voice-checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  cursor: pointer;
  flex: 1;
}

.checkbox {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: #38bdf8;
}

.voice-tag-badge {
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-primary, #f8fafc);
}

.tag-s, .tag-s1, .tag-s2 { background: rgba(56, 189, 248, 0.2); color: #38bdf8; }
.tag-a, .tag-a1, .tag-a2 { background: rgba(168, 85, 247, 0.2); color: #c084fc; }
.tag-t, .tag-t1, .tag-t2 { background: rgba(234, 179, 8, 0.2); color: #facc15; }
.tag-b, .tag-b1, .tag-b2 { background: rgba(34, 197, 94, 0.2); color: #4ade80; }
.tag-pno { background: rgba(244, 63, 94, 0.2); color: #fb7185; }

.voice-name {
  font-size: 0.88rem;
  font-weight: 600;
}

.voice-filename-preview {
  font-size: 0.75rem;
  font-family: monospace;
  color: var(--text-muted, #64748b);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}

.voice-row-actions {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.btn-audition {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  background: var(--bg-elevated, #1a243a);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
  border-radius: 5px;
  padding: 0.3rem 0.55rem;
  font-size: 0.75rem;
  color: var(--text-secondary, #94a3b8);
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-audition:hover:not(:disabled) {
  color: #38bdf8;
  border-color: #38bdf8;
}

.btn-single-download {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.3);
  border-radius: 5px;
  padding: 0.3rem 0.55rem;
  font-size: 0.75rem;
  color: #38bdf8;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-single-download:hover:not(:disabled) {
  background: #38bdf8;
  color: #0b1120;
}

/* Progress Card */
.render-progress-card {
  background: var(--bg-elevated, #1a243a);
  border: 1px solid rgba(56, 189, 248, 0.3);
  border-radius: 8px;
  padding: 0.85rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.progress-info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.82rem;
}

.progress-task {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.progress-percent {
  font-weight: 700;
  color: #38bdf8;
}

.progress-bar-bg {
  width: 100%;
  height: 6px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.1);
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #38bdf8, #a855f7);
  transition: width 0.2s ease;
}

/* Modal Footer */
.modal-footer {
  padding: 1rem 1.5rem;
  background: var(--bg-elevated, #1a243a);
  border-top: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}

.export-options-cluster {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.packaging-row {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
}

.format-info-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}

.format-name-badge {
  font-size: 0.74rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: rgba(56, 189, 248, 0.15);
  color: #38bdf8;
  padding: 0.2rem 0.5rem;
  border-radius: 6px;
  border: 1px solid rgba(56, 189, 248, 0.3);
}

.size-estimate-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.8rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
  padding: 0.2rem 0.6rem;
  border-radius: 6px;
  color: var(--text-secondary, #94a3b8);
}

.size-estimate-badge.is-savings {
  background: rgba(56, 189, 248, 0.1);
  border-color: rgba(56, 189, 248, 0.3);
  color: #e0f2fe;
}

.size-val {
  color: #38bdf8;
  font-weight: 700;
}

.savings-pill {
  background: rgba(34, 197, 94, 0.2);
  color: #4ade80;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
}

.format-picker {
  display: flex;
  align-items: center;
  gap: 1.25rem;
}

.radio-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  cursor: pointer;
  color: var(--text-secondary, #94a3b8);
}

.radio-label input {
  accent-color: #38bdf8;
}

.footer-buttons {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.btn-secondary {
  background: transparent;
  border: 1px solid var(--border, rgba(255, 255, 255, 0.15));
  border-radius: 7px;
  padding: 0.55rem 1rem;
  color: var(--text-secondary, #94a3b8);
  font-size: 0.88rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-secondary:hover:not(:disabled) {
  color: var(--text-primary, #f8fafc);
  background: rgba(255, 255, 255, 0.05);
}

.btn-primary {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: #38bdf8;
  color: #0b1120;
  border: none;
  border-radius: 7px;
  padding: 0.55rem 1.15rem;
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-primary:hover:not(:disabled) {
  background: #7dd3fc;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.spin-icon {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@media (max-width: 768px) {
  .rehearsal-modal-backdrop {
    padding: 0;
    align-items: stretch;
  }

  .rehearsal-modal-container {
    width: 100%;
    height: 100%;
    max-height: 100dvh;
    border-radius: 0;
    border: none;
    box-shadow: none;
    padding-top: env(safe-area-inset-top, 0);
  }

  .modal-header {
    padding: 12px 14px;
    flex-shrink: 0;
  }

  .modal-body {
    padding: 14px 12px;
    flex: 1;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }

  .modal-footer {
    padding: 12px 14px;
    padding-bottom: max(env(safe-area-inset-bottom, 0px), 14px);
    flex-shrink: 0;
  }

  .format-picker {
    width: 100%;
    justify-content: flex-start;
  }

  .footer-buttons {
    width: 100%;
  }

  .btn-secondary,
  .btn-primary {
    flex: 1;
    justify-content: center;
  }
}
</style>
