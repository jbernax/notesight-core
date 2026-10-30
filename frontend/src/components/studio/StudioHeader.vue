<script setup lang="ts">
import {
  ArrowLeft,
  Undo2,
  Redo2,
  Play,
  Pause,
  Square,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Minimize2,
  Save,
  Columns,
  BookOpen,
  SlidersHorizontal,
  LogOut,
  Share2,
  MessageSquare,
  Minus,
  Plus
} from 'lucide-vue-next'
import type { PeerInfo } from '../../composables/useCollaboration'

const props = defineProps<{
  canUndo: boolean
  canRedo: boolean
  isPlaying: boolean
  bpm: number
  zoomLevel: number
  viewMode: 'paginated' | 'continuous'
  isFullscreen: boolean
  isSplitReview: boolean
  isMixerOpen?: boolean
  isAnnotationsOpen?: boolean
  hasOriginalSource: boolean
  isSaving: boolean
  scoreTitle?: string
  collaborators?: PeerInfo[]
  annotationCount?: number
}>()

const emit = defineEmits<{
  (e: 'undo'): void
  (e: 'redo'): void
  (e: 'togglePlay'): void
  (e: 'stop'): void
  (e: 'update:bpm', bpm: number): void
  (e: 'zoomIn'): void
  (e: 'zoomOut'): void
  (e: 'resetZoom'): void
  (e: 'toggleViewMode'): void
  (e: 'toggleFullscreen'): void
  (e: 'toggleSplitReview'): void
  (e: 'toggleMixer'): void
  (e: 'toggleAnnotations'): void
  (e: 'openShare'): void
  (e: 'save'): void
  (e: 'exitStudio'): void
}>()
</script>

<template>
  <header class="studio-header">
    <div class="header-left">
      <button type="button" class="studio-badge clickable" @click="emit('exitStudio')" :title="$t('studio.header.exitStudio')">
        <ArrowLeft :size="16" />
        <span class="studio-dot"></span>
        <span class="studio-name">NoteSight Studio</span>
      </button>

      <!-- Studio Score Title Badge -->
      <div v-if="scoreTitle" class="studio-score-title-group" :title="scoreTitle">
        <span class="studio-score-title">{{ scoreTitle }}</span>
      </div>

      <!-- Peer Collaborator Avatar Cluster -->
      <div v-if="collaborators && collaborators.length > 0" class="collaborators-pill-cluster" title="Active collaborators editing this score">
        <div
          v-for="c in collaborators"
          :key="c.client_id"
          class="collaborator-avatar"
          :style="{ backgroundColor: c.color }"
          :title="`${c.user_name} (Measure ${c.current_measure})`"
        >
          {{ (c.user_name || 'M').charAt(0).toUpperCase() }}
        </div>
        <span class="live-dot" title="Live Collaboration Active"></span>
      </div>

      <div class="divider"></div>

      <!-- History Controls -->
      <div class="btn-group">
        <button
          type="button"
          class="tool-btn"
          :disabled="!canUndo"
          title="Undo (Ctrl+Z)"
          @click="emit('undo')"
        >
          <Undo2 :size="16" />
        </button>
        <button
          type="button"
          class="tool-btn"
          :disabled="!canRedo"
          title="Redo (Ctrl+Y)"
          @click="emit('redo')"
        >
          <Redo2 :size="16" />
        </button>
      </div>

      <div class="divider"></div>

      <!-- Playback Controls -->
      <div class="playback-group">
        <button
          type="button"
          class="playback-btn"
          :class="{ 'is-playing': isPlaying }"
          :title="isPlaying ? 'Pause playback (Space)' : 'Play score (Space)'"
          @click="emit('togglePlay')"
        >
          <Pause v-if="isPlaying" :size="16" />
          <Play v-else :size="16" />
        </button>
        <button
          type="button"
          class="playback-btn stop-btn"
          title="Stop playback"
          @click="emit('stop')"
        >
          <Square :size="14" />
        </button>

        <div class="tempo-control" title="Playback Tempo (BPM)">
          <button
            type="button"
            class="tempo-step-btn"
            @click="emit('update:bpm', Math.max(30, bpm - 5))"
            title="Slow down 5 BPM"
          >
            <Minus :size="11" :stroke-width="2.5" />
          </button>
          <input
            type="number"
            class="tempo-input"
            :value="bpm"
            min="30"
            max="300"
            step="5"
            @input="emit('update:bpm', parseInt(($event.target as HTMLInputElement).value || '120', 10))"
          />
          <span class="tempo-unit">BPM</span>
          <button
            type="button"
            class="tempo-step-btn"
            @click="emit('update:bpm', Math.min(300, bpm + 5))"
            title="Speed up 5 BPM"
          >
            <Plus :size="11" :stroke-width="2.5" />
          </button>
        </div>

        <button
          type="button"
          class="playback-btn mixer-toggle-btn"
          :class="{ 'active-mixer': isMixerOpen }"
          :title="$t('studio.header.mixer')"
          @click="emit('toggleMixer')"
        >
          <SlidersHorizontal :size="15" />
          <span class="mixer-btn-label">{{ $t('studio.header.mixer') }}</span>
        </button>
      </div>
    </div>

    <div class="header-right">
      <!-- Split Review Toggle (if source exists) -->
      <button
        v-if="hasOriginalSource"
        type="button"
        class="header-action-btn"
        :class="{ 'active-mode': isSplitReview }"
        :title="isSplitReview ? $t('studio.header.closeOriginal') : $t('studio.header.reviewOriginal')"
        @click="emit('toggleSplitReview')"
      >
        <Columns :size="15" />
        <span class="btn-label-text">{{ isSplitReview ? $t('studio.header.closeOriginal') : $t('studio.header.reviewOriginal') }}</span>
      </button>

      <!-- View Mode & Zoom -->
      <div class="btn-group">
        <button
          type="button"
          class="tool-btn"
          :title="viewMode === 'paginated' ? 'Switch to continuous scroll' : 'Switch to paginated view'"
          @click="emit('toggleViewMode')"
        >
          <BookOpen v-if="viewMode === 'paginated'" :size="14" />
          <Columns v-else :size="14" />
        </button>
        <button type="button" class="tool-btn" title="Zoom out" @click="emit('zoomOut')">
          <ZoomOut :size="14" />
        </button>
        <button type="button" class="tool-btn zoom-indicator" title="Reset zoom (100%)" @click="emit('resetZoom')">
          {{ Math.round(zoomLevel * 100) }}%
        </button>
        <button type="button" class="tool-btn" title="Zoom in" @click="emit('zoomIn')">
          <ZoomIn :size="14" />
        </button>
      </div>

      <button
        type="button"
        class="tool-btn"
        :title="isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'"
        @click="emit('toggleFullscreen')"
      >
        <Minimize2 v-if="isFullscreen" :size="15" />
        <Maximize2 v-else :size="15" />
      </button>

      <!-- Annotations Panel Toggle -->
      <button
        type="button"
        class="header-action-btn annotations-toggle-btn"
        :class="{ 'active-mode': isAnnotationsOpen }"
        :title="$t('studio.header.annotations')"
        @click="emit('toggleAnnotations')"
      >
        <MessageSquare :size="14" />
        <span class="btn-label-text">{{ $t('studio.header.annotations') }}</span>
        <span v-if="annotationCount && annotationCount > 0" class="ann-count-badge">{{ annotationCount }}</span>
      </button>

      <!-- Share Score Modal Button -->
      <button
        type="button"
        class="header-action-btn share-header-btn"
        :title="$t('studio.header.share')"
        @click="emit('openShare')"
      >
        <Share2 :size="14" />
        <span class="btn-label-text">{{ $t('studio.header.share') }}</span>
      </button>

      <!-- Save Button -->
      <button
        type="button"
        class="primary-save-btn"
        :disabled="isSaving"
        @click="emit('save')"
      >
        <Save :size="14" />
        <span>{{ isSaving ? $t('studio.header.saving') : $t('studio.header.save') }}</span>
      </button>

      <!-- Exit Studio Button -->
      <button
        type="button"
        class="secondary-exit-btn studio-mode-btn"
        :title="$t('studio.header.exitStudio')"
        @click="emit('exitStudio')"
      >
        <LogOut :size="14" />
        <span class="btn-label-text">{{ $t('studio.header.exitStudio') }}</span>
      </button>
    </div>
  </header>
</template>

<style scoped>
.studio-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-card, #151b28);
  border-bottom: 1px solid var(--border, #242f48);
  padding: 4px 12px;
  height: 44px;
  min-height: 44px;
  gap: 8px;
  flex-wrap: nowrap;
  user-select: none;
  overflow-x: auto;
  scrollbar-width: none;
}

.studio-header::-webkit-scrollbar {
  display: none;
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.studio-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 0.95rem;
  letter-spacing: -0.01em;
  color: var(--text-primary, #ffffff);
  background: transparent;
  border: none;
}

.studio-badge.clickable {
  cursor: pointer;
  padding: 3px 6px;
  border-radius: 6px;
  transition: background 0.15s;
}

.studio-badge.clickable:hover {
  background: rgba(255, 255, 255, 0.06);
}

.studio-score-title-group {
  display: inline-flex;
  align-items: center;
  max-width: 180px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--border, #242f48);
}

.studio-score-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-primary, #e2e8f0);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.studio-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.6);
}

.studio-name {
  background: linear-gradient(135deg, #a5b4fc 0%, #818cf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.divider {
  width: 1px;
  height: 22px;
  background: var(--border, #242f48);
}

.btn-group {
  display: inline-flex;
  align-items: center;
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #242f48);
  border-radius: 6px;
  padding: 2px;
  gap: 2px;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: var(--text-secondary, #94a3b8);
  padding: 6px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 0.8rem;
  font-weight: 500;
}

.tool-btn:hover:not(:disabled) {
  background: var(--bg-hover, rgba(255, 255, 255, 0.08));
  color: var(--text-primary, #ffffff);
}

.tool-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.zoom-indicator {
  min-width: 44px;
  font-family: monospace;
}

.playback-group {
  display: flex;
  align-items: center;
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #242f48);
  border-radius: 6px;
  padding: 2px 6px;
  gap: 6px;
}

.playback-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 4px;
  border: none;
  background: var(--color-primary, #6366f1);
  color: white;
  cursor: pointer;
  transition: all 0.15s ease;
}

.playback-btn:hover {
  background: var(--color-primary-hover, #4f46e5);
  transform: scale(1.04);
}

.playback-btn.is-playing {
  background: var(--color-warning, #f59e0b);
}

.stop-btn {
  background: transparent;
  color: var(--text-secondary, #94a3b8);
}

.stop-btn:hover {
  background: var(--color-danger-light, rgba(239, 68, 68, 0.2));
  color: var(--color-danger, #ef4444);
}

.tempo-control {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #242f48);
  border-radius: 6px;
  padding: 1px 4px;
  height: 30px;
}

.tempo-step-btn {
  background: rgba(255, 255, 255, 0.04);
  border: none;
  color: var(--text-secondary, #94a3b8);
  cursor: pointer;
  width: 18px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  padding: 0;
  transition: background 0.15s, color 0.15s;
}

.tempo-step-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.tempo-input {
  width: 42px;
  background: transparent;
  border: none;
  color: var(--text-primary, #ffffff);
  font-weight: 700;
  font-size: 0.82rem;
  font-variant-numeric: tabular-nums;
  padding: 0;
  text-align: center;
}

.tempo-input:focus {
  outline: none;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 3px;
}

.tempo-unit {
  font-size: 0.66rem;
  font-weight: 600;
  color: var(--text-muted, #94a3b8);
  text-transform: uppercase;
  margin: 0 1px;
}

.header-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #242f48);
  color: var(--text-secondary, #94a3b8);
  font-size: 0.78rem;
  font-weight: 500;
  padding: 4px 8px;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.header-action-btn:hover {
  background: var(--bg-hover, rgba(255, 255, 255, 0.06));
  color: var(--text-primary, #ffffff);
}

.header-action-btn.active-mode {
  background: var(--color-primary-light, rgba(99, 102, 241, 0.15));
  border-color: var(--color-primary, #6366f1);
  color: var(--color-primary, #6366f1);
}

.primary-save-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%);
  color: white;
  border: none;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s ease;
  box-shadow: 0 2px 6px rgba(79, 70, 229, 0.3);
  white-space: nowrap;
}

.primary-save-btn:hover:not(:disabled) {
  opacity: 0.95;
  transform: translateY(-1px);
}

.primary-save-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.secondary-exit-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #242f48);
  color: var(--text-secondary, #94a3b8);
  font-size: 0.78rem;
  font-weight: 500;
  padding: 4px 8px;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.secondary-exit-btn:hover {
  background: var(--color-danger-light, rgba(239, 68, 68, 0.12));
  border-color: var(--color-danger, #ef4444);
  color: var(--color-danger, #ef4444);
  transform: translateY(-1px);
}

@media (max-width: 1280px) {
  .btn-label-text {
    display: none;
  }
}

.collaborators-pill-cluster {
  display: flex;
  align-items: center;
  gap: -6px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 9999px;
  padding: 2px 6px;
  margin-left: 4px;
}

.collaborator-avatar {
  width: 20px;
  height: 20px;
  min-width: 20px;
  min-height: 20px;
  flex-shrink: 0;
  aspect-ratio: 1 / 1;
  border-radius: 50%;
  border: 2px solid #151b28;
  color: white;
  font-size: 10px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: -4px;
  cursor: default;
  transition: transform 0.15s;
}

.collaborator-avatar:hover {
  transform: scale(1.2) translateY(-2px);
  z-index: 10;
}

.live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
  margin-left: 8px;
  box-shadow: 0 0 8px #10b981;
  animation: pulse 2s infinite;
}

.ann-count-badge {
  background: #6366f1;
  color: white;
  font-size: 10px;
  font-weight: 700;
  border-radius: 9999px;
  padding: 1px 5px;
  margin-left: 4px;
}

@media (max-width: 768px) {
  .studio-header {
    padding: calc(6px + var(--sat, 0px)) 8px 6px 8px;
    height: auto;
    min-height: calc(48px + var(--sat, 0px));
    gap: 6px;
    justify-content: space-between;
  }
  .studio-name,
  .mixer-btn-label,
  .btn-label-text,
  .primary-save-btn span,
  .tempo-control,
  .header-right .btn-group {
    display: none;
  }
  .header-left,
  .header-right {
    gap: 4px;
  }
  .divider {
    display: none;
  }
  .tool-btn,
  .playback-btn,
  .header-action-btn,
  .primary-save-btn,
  .secondary-exit-btn {
    min-width: 38px;
    min-height: 38px;
    padding: 6px 8px;
  }
}
</style>
