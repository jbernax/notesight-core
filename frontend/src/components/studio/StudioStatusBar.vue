<script setup lang="ts">
import type { ParsedNote, MeasureAttributes } from '../../composables/useScoreMutation'

const props = defineProps<{
  currentMeasureNum: number
  totalMeasures: number
  selectedNote: ParsedNote | null
  measureAttributes: MeasureAttributes
  voiceTag?: string
  partName?: string
  isPlaying?: boolean
  playingNotes?: string
  isMidiConnected?: boolean
  lastMidiNote?: string | null
}>()
</script>

<template>
  <footer class="studio-status-bar">
    <div class="status-left">
      <div class="status-item">
        <span class="label">{{ $t('studio.statusBar.measure') }}</span>
        <span class="value">{{ currentMeasureNum }} / {{ totalMeasures }}</span>
      </div>

      <div class="status-divider"></div>

      <!-- Live Playing Follower Indicator -->
      <div class="status-item playing-indicator-item" v-if="isPlaying && playingNotes">
        <span class="label">{{ $t('studio.statusBar.playing') }}</span>
        <span class="value playing-badge">
          <span class="status-live-dot"></span>
          {{ playingNotes }}
        </span>
      </div>
      <template v-else>
        <div class="status-item" v-if="selectedNote">
          <span class="label">{{ $t('studio.statusBar.selected') }}</span>
          <span class="value note-badge">{{ selectedNote.summary }}</span>
        </div>
        <div class="status-item" v-else>
          <span class="label">{{ $t('studio.statusBar.selection') }}</span>
          <span class="value text-muted">{{ $t('studio.statusBar.clickToEdit') }}</span>
        </div>
      </template>

      <template v-if="voiceTag || partName">
        <div class="status-divider"></div>
        <div class="status-item">
          <span class="label">{{ $t('studio.statusBar.voice') }}</span>
          <span class="value voice-badge" :class="voiceTag ? `tag-${voiceTag.toLowerCase().replace(/[^a-z0-9]/g, '')}` : ''">
            <span v-if="voiceTag" class="voice-badge-tag">[{{ voiceTag }}]</span>
            <span class="voice-badge-name">{{ partName || '' }}</span>
          </span>
        </div>
      </template>

      <div class="status-divider"></div>

      <div class="status-item">
        <span class="label">{{ $t('studio.statusBar.time') }}</span>
        <span class="value">{{ measureAttributes.beats }}/{{ measureAttributes.beatType }}</span>
      </div>

      <div class="status-item">
        <span class="label">{{ $t('studio.statusBar.clef') }}</span>
        <span class="value">{{ measureAttributes.clefSign }}</span>
      </div>
    </div>

    <div class="status-right shortcuts-guide">
      <span v-if="isMidiConnected" class="guide-chip midi-active-chip" title="Web MIDI connected: Play notes on keyboard to input into active measure">
        <span class="status-live-dot"></span>
        MIDI{{ lastMidiNote ? `: ${lastMidiNote}` : '' }}
      </span>
      <span class="guide-chip"><kbd>↑</kbd><kbd>↓</kbd> {{ $t('studio.statusBar.pitchShortcut') }}</span>
      <span class="guide-chip"><kbd>1</kbd>–<kbd>6</kbd> {{ $t('studio.statusBar.durationShortcut') }}</span>
      <span class="guide-chip"><kbd>.</kbd> {{ $t('studio.statusBar.dotShortcut') }}</span>
      <span class="guide-chip"><kbd>R</kbd> {{ $t('studio.statusBar.restShortcut') }}</span>
      <span class="guide-chip"><kbd>Space</kbd> {{ $t('studio.statusBar.playShortcut') }}</span>
    </div>
  </footer>
</template>

<style scoped>
.studio-status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-card, #151b28);
  border-top: 1px solid var(--border, #242f48);
  padding: 4px 16px;
  min-height: 28px;
  font-size: 0.75rem;
  color: var(--text-secondary, #94a3b8);
  user-select: none;
  z-index: 10;
}

.status-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.status-divider {
  width: 1px;
  height: 14px;
  background: var(--border, #242f48);
}

.label {
  color: var(--text-secondary, #64748b);
  font-weight: 500;
}

.value {
  color: var(--text-primary, #ffffff);
  font-weight: 600;
}

.note-badge {
  background: rgba(99, 102, 241, 0.15);
  color: #a5b4fc;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid rgba(99, 102, 241, 0.3);
}

.playing-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: rgba(16, 185, 129, 0.18);
  color: #6ee7b7;
  padding: 1px 8px;
  border-radius: 4px;
  border: 1px solid rgba(16, 185, 129, 0.45);
  font-family: var(--font-mono, monospace);
  font-weight: 700;
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.25);
}

.status-live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 6px #10b981;
  animation: pulseDot 1s ease-in-out infinite alternate;
}

@keyframes pulseDot {
  from { opacity: 0.5; transform: scale(0.8); }
  to { opacity: 1; transform: scale(1.2); }
}

.voice-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: rgba(255, 255, 255, 0.06);
  padding: 1px 7px;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.voice-badge-tag {
  font-weight: 800;
  letter-spacing: 0.02em;
}

.voice-badge.tag-s { color: #f43f5e; border-color: rgba(244, 63, 94, 0.3); }
.voice-badge.tag-a { color: #a855f7; border-color: rgba(168, 85, 247, 0.3); }
.voice-badge.tag-t { color: #06b6d4; border-color: rgba(6, 182, 212, 0.3); }
.voice-badge.tag-b { color: #3b82f6; border-color: rgba(59, 130, 246, 0.3); }
.voice-badge.tag-pno, .voice-badge.tag-piano { color: #f59e0b; border-color: rgba(245, 158, 11, 0.3); }
.voice-badge.tag-bar { color: #6366f1; border-color: rgba(99, 102, 241, 0.3); }
.voice-badge.tag-ms { color: #d946ef; border-color: rgba(217, 70, 239, 0.3); }

.text-muted {
  color: #64748b;
  font-style: italic;
}

.shortcuts-guide {
  display: flex;
  align-items: center;
  gap: 8px;
}

.guide-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 0.7rem;
  color: #94a3b8;
}

kbd {
  background: var(--bg-elevated, #0c1017);
  border: 1px solid var(--border, #242f48);
  border-radius: 3px;
  padding: 1px 4px;
  font-family: inherit;
  font-size: 0.68rem;
  color: var(--text-primary, #e2e8f0);
}

.midi-active-chip {
  background: rgba(16, 185, 129, 0.15) !important;
  color: #10b981 !important;
  border: 1px solid rgba(16, 185, 129, 0.4);
  border-radius: 4px;
  padding: 1px 6px;
  font-weight: 600;
}

@media (max-width: 768px) {
  .studio-status-bar {
    display: none;
  }
}
</style>
