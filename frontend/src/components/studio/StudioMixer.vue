<script setup lang="ts">
import { ref, computed } from 'vue'
import { SlidersHorizontal, X, RotateCcw, Trash2, Headphones } from 'lucide-vue-next'
import { ScorePlaybackController, type PlaybackStateSnapshot, type TrackConfig } from '../../audio/scorePlayer'
import { INSTRUMENT_OPTIONS, type InstrumentType, type InstrumentOption } from '../../audio/synth'
import { REVERB_PRESETS, type ReverbPreset } from '../../audio/effectsBus'
import { preferences, savePreferences } from '../../composables/useSettings'
import RehearsalExportModal from '../RehearsalExportModal.vue'

const props = defineProps<{
  player: ScorePlaybackController
  playbackState: PlaybackStateSnapshot
}>()

function handleMasterTimbreChange(inst: InstrumentType) {
  props.player.setInstrument(inst)
  preferences.value.defaultInstrument = inst
  savePreferences()
}

const isRehearsalModalOpen = ref(false)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'deleteTrack', track: TrackConfig): void
}>()

const activeTracks = computed(() => props.playbackState.tracks)
const sampledInstruments = computed(() => INSTRUMENT_OPTIONS.filter((i: InstrumentOption) => i.category === 'soundfont'))
const synthInstruments = computed(() => INSTRUMENT_OPTIONS.filter((i: InstrumentOption) => i.category === 'synth'))
</script>

<template>
  <div class="studio-mixer-backdrop" @click="emit('close')" aria-label="Close mixer" />
  <div class="studio-mixer-drawer" role="dialog" aria-label="Studio Audio Mixer Drawer">
    <div class="mixer-drawer-header">
      <div class="header-top-row">
        <div class="header-title-wrap">
          <SlidersHorizontal :size="18" class="title-icon" />
          <span class="drawer-title">{{ $t('studio.mixer.mixerTitle') }}</span>
          <span class="tracks-count-badge">{{ $t('studio.mixer.tracksCount', { count: activeTracks.length }) }}</span>
        </div>

        <button
          type="button"
          class="btn-close-drawer mobile-only-close"
          @click="emit('close')"
          :title="$t('common.close')"
        >
          <X :size="18" />
        </button>
      </div>

      <!-- Master Reverb & Master Instrument Controls -->
      <div class="master-bus-controls">
        <div class="bus-ctrl-item">
          <label class="bus-ctrl-label">{{ $t('studio.mixer.masterReverb') }}</label>
          <select
            :value="playbackState.reverbPreset"
            @change="player.setReverbPreset(($event.target as HTMLSelectElement).value as ReverbPreset)"
            class="mixer-select"
            title="Master acoustic convolution space"
          >
            <option v-for="r in REVERB_PRESETS" :key="r.id" :value="r.id">
              {{ r.name }} ({{ r.description }})
            </option>
          </select>
        </div>

        <div class="bus-ctrl-item">
          <label class="bus-ctrl-label">{{ $t('studio.mixer.masterTimbre') }}</label>
          <select
            :value="playbackState.instrument"
            @change="handleMasterTimbreChange(($event.target as HTMLSelectElement).value as InstrumentType)"
            class="mixer-select"
            title="Default instrument timbre"
          >
            <optgroup :label="$t('studio.mixer.sampledGroup')">
              <option
                v-for="inst in sampledInstruments"
                :key="inst.id"
                :value="inst.id"
              >
                {{ inst.name }}
              </option>
            </optgroup>
            <optgroup :label="$t('studio.mixer.synthGroup')">
              <option
                v-for="inst in synthInstruments"
                :key="inst.id"
                :value="inst.id"
              >
                {{ inst.name }}
              </option>
            </optgroup>
          </select>
        </div>

        <button
          type="button"
          class="btn-rehearsal-tracks"
          @click="isRehearsalModalOpen = true"
          :title="$t('studio.mixer.exportRehearsalTracks')"
        >
          <Headphones :size="13" />
          <span>{{ $t('studio.mixer.rehearsalTracks') }}</span>
        </button>

        <button
          type="button"
          class="btn-reset-mix"
          @click="player.resetTrackMix()"
          :title="$t('studio.mixer.resetMix')"
        >
          <RotateCcw :size="13" />
          <span>{{ $t('studio.mixer.resetMix') }}</span>
        </button>

        <button
          type="button"
          class="btn-close-drawer desktop-only-close"
          @click="emit('close')"
          :title="$t('common.close')"
        >
          <X :size="16" />
        </button>
      </div>
    </div>

    <!-- Mixer Channels Strip -->
    <div class="mixer-channels-scroll">
      <div
        v-for="track in activeTracks"
        :key="track.id"
        class="mixer-channel-strip"
        :class="{
          'is-solo': track.isSolo,
          'is-mute': track.isMuted,
          'is-inaudible': !player.isTrackAudible(track.id)
        }"
      >
        <div class="strip-header">
          <span
            v-if="track.voiceTag"
            class="channel-voice-tag"
            :class="`tag-${track.voiceTag.toLowerCase().replace(/[^a-z0-9]/g, '')}`"
          >
            {{ track.voiceTag }}
          </span>
          <span class="channel-name" :title="track.displayName || track.name">
            {{ track.name }}
          </span>
          <button
            type="button"
            class="strip-delete-btn"
            :disabled="activeTracks.length <= 1"
            :title="activeTracks.length <= 1 ? 'Score must retain at least one track' : `Delete line: ${track.name}`"
            @click="emit('deleteTrack', track)"
          >
            <Trash2 :size="12" />
          </button>
        </div>

        <!-- Solo / Mute Group -->
        <div class="strip-btn-group">
          <button
            type="button"
            class="strip-btn solo-btn"
            :class="{ active: track.isSolo }"
            @click="player.toggleTrackSolo(track.id)"
            :title="$t('studio.mixer.solo')"
          >
            S
          </button>
          <button
            type="button"
            class="strip-btn mute-btn"
            :class="{ active: track.isMuted }"
            @click="player.toggleTrackMute(track.id)"
            :title="$t('studio.mixer.mute')"
          >
            M
          </button>
        </div>

        <!-- Instrument Selector -->
        <div class="strip-section">
          <label class="strip-label">{{ $t('studio.mixer.instrument') }}</label>
          <select
            :value="track.instrument"
            @change="player.setTrackInstrument(track.id, ($event.target as HTMLSelectElement).value as InstrumentType)"
            class="channel-select"
          >
            <optgroup :label="$t('studio.mixer.sampledGroup')">
              <option
                v-for="inst in sampledInstruments"
                :key="inst.id"
                :value="inst.id"
              >
                {{ inst.name }}
              </option>
            </optgroup>
            <optgroup :label="$t('studio.mixer.synthGroup')">
              <option
                v-for="inst in synthInstruments"
                :key="inst.id"
                :value="inst.id"
              >
                {{ inst.name }}
              </option>
            </optgroup>
          </select>
        </div>

        <!-- Pan Control -->
        <div class="strip-section">
          <div class="strip-label-row">
            <span class="strip-label">{{ $t('studio.mixer.pan') }}</span>
            <span class="strip-value">{{ track.pan === 0 ? 'C' : track.pan < 0 ? `L${Math.round(Math.abs(track.pan) * 100)}` : `R${Math.round(track.pan * 100)}` }}</span>
          </div>
          <input
            type="range"
            min="-1"
            max="1"
            step="0.05"
            :value="track.pan"
            @input="player.setTrackPan(track.id, parseFloat(($event.target as HTMLInputElement).value))"
            class="channel-slider pan-slider"
          />
        </div>

        <!-- Reverb Send Control -->
        <div class="strip-section">
          <div class="strip-label-row">
            <span class="strip-label">{{ $t('studio.mixer.reverb') }}</span>
            <span class="strip-value">{{ Math.round((track.reverbSend ?? 0.25) * 100) }}%</span>
          </div>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            :value="track.reverbSend ?? 0.25"
            @input="player.setTrackReverbSend(track.id, parseFloat(($event.target as HTMLInputElement).value))"
            class="channel-slider reverb-slider"
          />
        </div>

        <!-- Volume Fader -->
        <div class="strip-section fader-section">
          <div class="strip-label-row">
            <span class="strip-label">{{ $t('studio.mixer.level') }}</span>
            <span class="strip-value">{{ track.volume }}%</span>
          </div>
          <input
            type="range"
            min="0"
            max="100"
            :value="track.volume"
            @input="player.setTrackVolume(track.id, parseFloat(($event.target as HTMLInputElement).value))"
            class="channel-slider vol-slider"
          />
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
.studio-mixer-drawer {
  background: var(--bg-card, #151b28);
  border-top: 1px solid var(--border, #242f48);
  box-shadow: 0 -8px 24px rgba(0, 0, 0, 0.35);
  display: flex;
  flex-direction: column;
  z-index: 25;
  animation: slideUp 0.18s ease-out;
}

@keyframes slideUp {
  from {
    transform: translateY(100%);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

.mixer-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: rgba(15, 23, 42, 0.7);
  border-bottom: 1px solid var(--border, #242f48);
  flex-wrap: wrap;
  gap: 12px;
}

.header-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.title-icon {
  color: var(--color-primary, #3b82f6);
}

.drawer-title {
  font-weight: 700;
  font-size: 0.88rem;
  color: var(--text-primary, #f1f5f9);
}

.tracks-count-badge {
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
  font-size: 0.72rem;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 600;
}

.master-bus-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.bus-ctrl-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.bus-ctrl-label {
  font-size: 0.75rem;
  color: var(--text-secondary, #94a3b8);
  font-weight: 600;
}

.mixer-select {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #334155);
  border-radius: 6px;
  color: var(--text-primary, #f1f5f9);
  padding: 4px 8px;
  font-size: 0.78rem;
  outline: none;
  cursor: pointer;
  min-height: 32px;
}

.btn-rehearsal-tracks {
  display: flex;
  align-items: center;
  gap: 5px;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.3);
  color: #38bdf8;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  min-height: 32px;
}

.btn-rehearsal-tracks:hover {
  background: #38bdf8;
  color: #0b1120;
}

.btn-reset-mix {
  display: flex;
  align-items: center;
  gap: 4px;
  background: transparent;
  border: 1px solid var(--border, #334155);
  color: var(--text-secondary, #94a3b8);
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s;
  min-height: 32px;
}

.btn-reset-mix:hover {
  background: var(--bg-hover, rgba(255, 255, 255, 0.06));
  color: var(--text-primary, #ffffff);
}

.btn-close-drawer {
  background: transparent;
  border: none;
  color: var(--text-secondary, #94a3b8);
  cursor: pointer;
  padding: 6px;
  display: flex;
  align-items: center;
  border-radius: 4px;
  min-height: 32px;
}

.btn-close-drawer:hover {
  background: var(--color-danger-light, rgba(239, 68, 68, 0.15));
  color: var(--color-danger, #ef4444);
}

.mixer-channels-scroll {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  overflow-x: auto;
}

.mixer-channel-strip {
  min-width: 170px;
  max-width: 190px;
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #242f48);
  border-radius: 8px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-shadow: var(--shadow-sm);
  transition: all 0.15s;
}

.mixer-channel-strip.is-solo {
  border-color: #f59e0b;
  box-shadow: 0 0 10px rgba(245, 158, 11, 0.2);
}

.mixer-channel-strip.is-inaudible {
  opacity: 0.55;
  filter: grayscale(40%);
}

.strip-header {
  display: flex;
  align-items: center;
  gap: 6px;
}

.channel-voice-tag {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 4px;
  background: #3b82f6;
  color: white;
}

.channel-name {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

.strip-delete-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary, #64748b);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
  margin-left: auto;
}

.strip-delete-btn:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

.strip-delete-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.strip-btn-group {
  display: flex;
  gap: 6px;
}

.strip-btn {
  flex: 1;
  padding: 3px 0;
  font-size: 0.72rem;
  font-weight: 700;
  border-radius: 4px;
  border: 1px solid var(--border, #334155);
  background: transparent;
  color: var(--text-secondary, #94a3b8);
  cursor: pointer;
}

.solo-btn.active {
  background: #f59e0b;
  border-color: #d97706;
  color: #ffffff;
}

.mute-btn.active {
  background: #ef4444;
  border-color: #dc2626;
  color: #ffffff;
}

.strip-section {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.strip-label-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.strip-label {
  font-size: 0.68rem;
  text-transform: uppercase;
  color: var(--text-secondary, #64748b);
  font-weight: 700;
  letter-spacing: 0.03em;
}

.strip-value {
  font-size: 0.7rem;
  font-family: monospace;
  color: var(--text-secondary, #94a3b8);
}

.channel-select {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 4px;
  color: #f1f5f9;
  font-size: 0.75rem;
  padding: 3px 5px;
  outline: none;
  cursor: pointer;
}

.channel-slider {
  width: 100%;
  height: 4px;
  cursor: pointer;
}

.vol-slider {
  accent-color: #3b82f6;
}

.pan-slider {
  accent-color: #06b6d4;
}

.reverb-slider {
  accent-color: #8b5cf6;
}

.studio-mixer-backdrop {
  display: none;
}

.mobile-only-close {
  display: none;
}

.desktop-only-close {
  display: flex;
}

.header-top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

@media (max-width: 768px) {
  .studio-mixer-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 9990;
    background: rgba(0, 0, 0, 0.65);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
  }

  .mobile-only-close {
    display: flex;
  }

  .desktop-only-close {
    display: none;
  }

  .studio-mixer-drawer {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    max-height: 85vh;
    border-radius: 16px 16px 0 0;
    z-index: 10000;
    padding-bottom: calc(var(--sab) + 12px);
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }

  .mixer-drawer-header {
    position: sticky;
    top: 0;
    z-index: 10;
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
    padding: 12px 14px;
    background: var(--bg-card, #151b28);
  }

  .master-bus-controls {
    flex-direction: column;
    gap: 8px;
    width: 100%;
  }

  .mixer-channel-strip {
    min-width: 160px;
  }
}
</style>
