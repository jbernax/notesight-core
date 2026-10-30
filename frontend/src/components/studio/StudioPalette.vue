<script setup lang="ts">
import { ref } from 'vue'
import { ChevronLeft, ChevronRight } from 'lucide-vue-next'
import type { ParsedNote } from '../../composables/useScoreMutation'
import { activeDraggingTool } from '../../composables/useScoreInteraction'
import { t } from '../../i18n'


const props = defineProps<{
  selectedNote: ParsedNote | null
}>()

const isCollapsed = ref(false)

const emit = defineEmits<{
  (e: 'setNoteType', type: string): void
  (e: 'setRestType', type: string): void
  (e: 'toggleDot'): void
  (e: 'toggleRest'): void
  (e: 'toggleTie'): void
  (e: 'toggleAccidental', alter: number): void
}>()

const NOTE_DURATIONS = [
  { type: 'whole', symbol: '𝅝', label: 'Whole note (1)', shortcut: '1' },
  { type: 'half', symbol: '𝅗𝅥', label: 'Half note (2)', shortcut: '2' },
  { type: 'quarter', symbol: '𝅘𝅥', label: 'Quarter note (3)', shortcut: '3' },
  { type: 'eighth', symbol: '𝅘𝅥𝅮', label: 'Eighth note (4)', shortcut: '4' },
  { type: '16th', symbol: '𝅘𝅥𝅯', label: '16th note (5)', shortcut: '5' },
  { type: '32nd', symbol: '𝅘𝅥𝅰', label: '32nd note (6)', shortcut: '6' }
]

const REST_DURATIONS = [
  { type: 'whole', symbol: '𝄻', label: 'Whole rest', shortcut: 'W' },
  { type: 'half', symbol: '𝄼', label: 'Half rest', shortcut: 'H' },
  { type: 'quarter', symbol: '𝄽', label: 'Quarter rest', shortcut: 'Q' },
  { type: 'eighth', symbol: '𝄾', label: 'Eighth rest', shortcut: 'E' },
  { type: '16th', symbol: '𝄿', label: '16th rest', shortcut: 'S' },
  { type: '32nd', symbol: '𝅀', label: '32nd rest', shortcut: 'T' }
]

const ACCIDENTALS = [
  { alter: -2, symbol: '𝄫', label: 'Double Flat' },
  { alter: -1, symbol: '♭', label: 'Flat' },
  { alter: 0, symbol: '♮', label: 'Natural' },
  { alter: 1, symbol: '♯', label: 'Sharp' },
  { alter: 2, symbol: '𝄪', label: 'Double Sharp' }
]

const handleDragStart = (e: DragEvent, tool: { type: string; value?: any; label?: string; symbol?: string }) => {
  if (!e.dataTransfer) return
  const payload = {
    type: tool.type,
    value: tool.value,
    label: tool.label || tool.value || tool.type,
    symbol: tool.symbol || (tool.type === 'duration' ? '𝅘𝅥' : '•')
  }
  activeDraggingTool.value = payload
  e.dataTransfer.setData('application/notesight-tool', JSON.stringify(payload))
  e.dataTransfer.effectAllowed = 'copy'

  try {
    const dragGhost = document.createElement('div')
    dragGhost.style.position = 'absolute'
    dragGhost.style.top = '-9999px'
    dragGhost.style.left = '-9999px'
    dragGhost.style.padding = '6px 14px'
    dragGhost.style.background = '#4f46e5'
    dragGhost.style.color = '#ffffff'
    dragGhost.style.borderRadius = '8px'
    dragGhost.style.fontSize = '16px'
    dragGhost.style.fontWeight = 'bold'
    dragGhost.style.boxShadow = '0 6px 18px rgba(0,0,0,0.45)'
    dragGhost.textContent = `${payload.symbol} ${payload.label}`
    document.body.appendChild(dragGhost)
    e.dataTransfer.setDragImage(dragGhost, 16, 16)
    setTimeout(() => dragGhost.remove(), 0)
  } catch {}
}

const handleDragEnd = () => {
  activeDraggingTool.value = null
}

const handleRestClick = (restType: string) => {
  if (props.selectedNote && props.selectedNote.isRest) {
    emit('setNoteType', restType)
  } else if (props.selectedNote && !props.selectedNote.isRest) {
    emit('setRestType', restType)
  } else {
    emit('toggleRest')
  }
}
</script>

<template>
  <aside class="studio-palette" :class="{ 'is-collapsed': isCollapsed }" aria-label="Unified Notation Tool Palette">
    <!-- Header indicator -->
    <div class="palette-header">
      <span v-if="!isCollapsed" class="palette-badge">{{ t('studio.palette.tools') }}</span>
      <button
        type="button"
        class="palette-collapse-btn"
        :title="isCollapsed ? 'Expand tool palette' : 'Collapse tool palette'"
        @click="isCollapsed = !isCollapsed"
      >
        <ChevronRight v-if="isCollapsed" :size="13" />
        <ChevronLeft v-else :size="13" />
      </button>
    </div>

    <!-- Collapsed Quick Rail -->
    <div v-if="isCollapsed" class="palette-mini-rail">
      <button
        type="button"
        class="palette-mini-btn"
        :class="{ active: selectedNote && !selectedNote.isRest && selectedNote.type === 'quarter' }"
        title="Quarter note (3)"
        @click="emit('setNoteType', 'quarter')"
      >
        𝅘𝅥
      </button>
      <button
        type="button"
        class="palette-mini-btn"
        :class="{ active: selectedNote && !selectedNote.isRest && selectedNote.type === 'eighth' }"
        title="Eighth note (4)"
        @click="emit('setNoteType', 'eighth')"
      >
        𝅘𝅥𝅮
      </button>
      <button
        type="button"
        class="palette-mini-btn"
        :class="{ active: selectedNote && selectedNote.isRest }"
        title="Toggle Rest (R)"
        @click="emit('toggleRest')"
      >
        𝄽
      </button>
      <button
        type="button"
        class="palette-mini-btn"
        :class="{ active: selectedNote?.isDotted }"
        title="Dotted Note (.)"
        @click="emit('toggleDot')"
      >
        •
      </button>
    </div>

    <!-- Full Palette Content -->
    <template v-else>
      <!-- Dual Column: Notes & Silence -->
      <div class="palette-durations-container">
      <div class="column-header-row">
        <span class="col-title" :title="t('studio.palette.notes')">{{ t('studio.palette.notes') }}</span>
        <span class="col-title" :title="t('studio.palette.rests')">{{ t('studio.palette.rests') }}</span>
      </div>

      <div class="duration-grid">
        <!-- Rows of [Note, Rest] -->
        <template v-for="(noteItem, idx) in NOTE_DURATIONS" :key="noteItem.type">
          <!-- Column 1: Note -->
          <button
            type="button"
            draggable="true"
            class="palette-btn duration-btn"
            :class="{ active: selectedNote && !selectedNote.isRest && selectedNote.type === noteItem.type }"
            :title="`${noteItem.label} (Drag or click to place)`"
            @click="emit('setNoteType', noteItem.type)"
            @dragstart="handleDragStart($event, { type: 'duration', value: noteItem.type, label: noteItem.label, symbol: noteItem.symbol })"
            @dragend="handleDragEnd"
          >
            <span class="symbol note-sym">{{ noteItem.symbol }}</span>
            <span class="sub-key">{{ noteItem.shortcut }}</span>
          </button>

          <!-- Column 2: Rest -->
          <button
            type="button"
            draggable="true"
            class="palette-btn rest-btn"
            :class="{ active: selectedNote && selectedNote.isRest && selectedNote.type === REST_DURATIONS[idx].type }"
            :title="`${REST_DURATIONS[idx].label} (Drag or click to place)`"
            @click="handleRestClick(REST_DURATIONS[idx].type)"
            @dragstart="handleDragStart($event, { type: 'rest', value: REST_DURATIONS[idx].type, label: REST_DURATIONS[idx].label, symbol: REST_DURATIONS[idx].symbol })"
            @dragend="handleDragEnd"
          >
            <span class="symbol rest-sym">{{ REST_DURATIONS[idx].symbol }}</span>
            <span class="sub-key">{{ REST_DURATIONS[idx].shortcut }}</span>
          </button>
        </template>
      </div>
    </div>

    <div class="palette-divider"></div>

    <!-- Modifiers: Dotted & Rest toggle -->
    <div class="palette-section">
      <span class="section-label">Modifiers</span>
      <div class="modifiers-row">
        <button
          type="button"
          draggable="true"
          class="palette-btn mod-btn"
          :class="{ active: selectedNote?.isDotted }"
          title="Dotted Note (.) - Drag or click"
          @click="emit('toggleDot')"
          @dragstart="handleDragStart($event, { type: 'dot', label: 'Dotted Note', symbol: '•' })"
          @dragend="handleDragEnd"
        >
          <span class="symbol dot-sym">•</span>
          <span class="sub-key">.</span>
        </button>

        <button
          type="button"
          draggable="true"
          class="palette-btn mod-btn"
          :class="{ active: selectedNote?.isRest }"
          title="Toggle Rest (R) - Drag or click"
          @click="emit('toggleRest')"
          @dragstart="handleDragStart($event, { type: 'rest', label: 'Rest', symbol: '𝄽' })"
          @dragend="handleDragEnd"
        >
          <span class="symbol rest-sym">𝄽</span>
          <span class="sub-key">R</span>
        </button>

        <button
          type="button"
          draggable="true"
          class="palette-btn mod-btn"
          :class="{ active: selectedNote?.hasTieStart || selectedNote?.hasTieStop }"
          title="Toggle Tie (T) - Drag or click"
          @click="emit('toggleTie')"
          @dragstart="handleDragStart($event, { type: 'tie', label: 'Tie', symbol: '⌒' })"
          @dragend="handleDragEnd"
        >
          <span class="symbol tie-sym">⌒</span>
          <span class="sub-key">T</span>
        </button>
      </div>
    </div>

    <div class="palette-divider"></div>

    <!-- Accidentals Sub-deck -->
    <div class="palette-section">
      <span class="section-label">{{ t('studio.palette.accidentals') }}</span>
      <div class="accidentals-grid">
        <button
          v-for="acc in ACCIDENTALS"
          :key="acc.alter"
          type="button"
          draggable="true"
          class="palette-btn acc-btn"
          :class="{ active: selectedNote && !selectedNote.isRest && selectedNote.alter === acc.alter }"
          :title="`${acc.label} - Drag or click`"
          @click="emit('toggleAccidental', acc.alter)"
          @dragstart="handleDragStart($event, { type: 'accidental', value: acc.alter, label: acc.label, symbol: acc.symbol })"
          @dragend="handleDragEnd"
        >
          <span class="symbol acc-sym">{{ acc.symbol }}</span>
        </button>
      </div>
    </div>
    </template>
  </aside>
</template>

<style scoped>
.studio-palette {
  display: flex;
  flex-direction: column;
  align-items: center;
  background: var(--bg-card, #151b28);
  border-right: 1px solid var(--border, #242f48);
  padding: 6px 4px;
  gap: 6px;
  user-select: none;
  width: 86px;
  flex-shrink: 0;
  z-index: 10;
  box-sizing: border-box;
  transition: width 0.2s ease, padding 0.2s ease;
}

.studio-palette.is-collapsed {
  width: 32px;
  padding: 6px 2px;
}

.palette-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2px;
  padding: 0 2px;
}

.studio-palette.is-collapsed .palette-header {
  justify-content: center;
  padding: 0;
}

.palette-collapse-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary, #94a3b8);
  padding: 2px;
  border-radius: 4px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}

.palette-collapse-btn:hover {
  background: var(--bg-hover, rgba(255, 255, 255, 0.08));
  color: var(--text-primary, #ffffff);
}

.palette-mini-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  width: 100%;
  margin-top: 4px;
}

.palette-mini-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  background: var(--bg-elevated, #222c42);
  border: 1px solid var(--border, #242f48);
  border-radius: 4px;
  color: var(--text-primary, #ffffff);
  font-size: 1rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.palette-mini-btn:hover {
  border-color: var(--color-primary, #6366f1);
  color: var(--color-primary, #6366f1);
}

.palette-mini-btn.active {
  background: var(--color-primary-light, rgba(99, 102, 241, 0.25));
  border-color: var(--color-primary, #818cf8);
  color: var(--color-primary, #6366f1);
}

.palette-badge {
  font-size: 0.62rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: var(--text-secondary, #64748b);
  background: var(--bg-hover, rgba(255, 255, 255, 0.04));
  padding: 2px 8px;
  border-radius: 4px;
}

.palette-durations-container {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.column-header-row {
  display: flex;
  justify-content: space-around;
  width: 100%;
  margin-bottom: 2px;
}

.col-title {
  font-size: 0.65rem;
  font-weight: 600;
  color: var(--text-secondary, #94a3b8);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.duration-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 5px;
  width: 100%;
}

.palette-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  width: 100%;
}

.section-label {
  font-size: 0.62rem;
  font-weight: 700;
  color: var(--text-secondary, #64748b);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 2px;
  align-self: flex-start;
  padding-left: 2px;
}

.modifiers-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 5px;
  width: 100%;
}

.accidentals-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  width: 100%;
}

.palette-divider {
  width: 100%;
  height: 1px;
  background: var(--border, #242f48);
  margin: 2px 0;
}

.palette-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 33px;
  background: var(--bg-elevated, #222c42);
  border: 1px solid var(--border, #242f48);
  border-radius: 4px;
  color: var(--text-primary, #ffffff);
  cursor: grab;
  transition: all 0.15s ease;
  position: relative;
  padding: 0;
}

.palette-btn:active {
  cursor: grabbing;
}

.palette-btn:hover:not(:disabled) {
  border-color: var(--color-primary, #6366f1);
  background: var(--color-primary-light, rgba(99, 102, 241, 0.12));
  color: var(--color-primary, #6366f1);
  transform: translateY(-1px);
}

.palette-btn.active {
  background: var(--color-primary-light, rgba(99, 102, 241, 0.25));
  border-color: var(--color-primary, #818cf8);
  color: var(--color-primary, #6366f1);
  box-shadow: 0 0 8px rgba(99, 102, 241, 0.3);
}

.palette-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.symbol {
  line-height: 1;
}

.note-sym {
  font-size: 1.55rem;
}

.rest-sym {
  font-size: 1.45rem;
}

.dot-sym {
  font-size: 2rem;
  line-height: 0.7;
}

.acc-sym {
  font-size: 1.35rem;
  font-weight: bold;
}

.sub-key {
  position: absolute;
  bottom: 1px;
  right: 2px;
  font-size: 0.5rem;
  font-weight: 700;
  color: var(--text-secondary, #64748b);
  line-height: 1;
}

@media (max-width: 768px) {
  .studio-palette {
    width: 100%;
    flex-direction: row;
    align-items: center;
    overflow-x: auto;
    padding: 6px 10px;
    border-right: none;
    border-bottom: 1px solid var(--border, #242f48);
    gap: 6px;
  }

  .palette-header {
    display: none;
  }

  .palette-durations-container {
    flex-direction: row;
    align-items: center;
    width: auto;
    gap: 6px;
  }

  .column-header-row {
    display: none;
  }

  .duration-grid {
    display: flex;
    gap: 4px;
    width: auto;
  }

  .palette-section {
    flex-direction: row;
    align-items: center;
    width: auto;
    gap: 4px;
  }

  .section-label {
    display: none;
  }

  .modifiers-row {
    display: flex;
    gap: 4px;
    width: auto;
  }

  .accidentals-grid {
    display: flex;
    gap: 4px;
    width: auto;
  }

  .palette-divider {
    width: 1px;
    height: 28px;
    margin: 0 4px;
  }

  .palette-btn {
    width: 44px;
    min-width: 44px;
    height: 44px;
  }
}
</style>
