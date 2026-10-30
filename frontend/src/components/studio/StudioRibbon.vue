<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import {
  Plus,
  Trash2,
  ChevronUp,
  ChevronDown,
  Type,
  Volume2,
  Sliders,
  Check,
  LayoutGrid,
  Music
} from 'lucide-vue-next'
import type { ParsedNote, MeasureAttributes } from '../../composables/useScoreMutation'
import { activeDraggingTool } from '../../composables/useScoreInteraction'
import { t } from '../../i18n'


const props = defineProps<{
  selectedNote: ParsedNote | null
  measureAttributes: MeasureAttributes
  currentMeasureNum: number
  totalMeasures: number
  activePartId?: string
  activePartName?: string
  totalParts?: number
  activeVoiceNumber?: number
  hasMultipleVoices?: boolean
}>()

const emit = defineEmits<{
  (e: 'transpose', semitones: number): void
  (e: 'addMeasure'): void
  (e: 'deleteMeasure'): void
  (e: 'fillLine'): void
  (e: 'fillPage'): void
  (e: 'deletePart', partId: string): void
  (e: 'deleteVoice', payload: { partId: string; voiceNumber: number }): void
  (e: 'setTimeSignature', beats: number, beatType: number): void
  (e: 'setKeySignature', fifths: number): void
  (e: 'setClef', sign: string, line: number): void
  (e: 'setLyrics', lyrics: string): void
  (e: 'setDynamics', dynamic: string): void
}>()

const lyricInputRef = ref<HTMLInputElement | null>(null)

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

type RibbonCategory = 'measure' | 'signatures' | 'dynamics' | 'text'
const activeCategory = ref<RibbonCategory>('measure')
const isCollapsed = ref<boolean>(typeof window !== 'undefined' && window.innerWidth <= 768)

const selectCategory = (cat: RibbonCategory) => {
  if (activeCategory.value === cat && !isCollapsed.value) {
    isCollapsed.value = true
    return
  }
  activeCategory.value = cat
  isCollapsed.value = false
}

const lyricsInput = ref(props.selectedNote?.lyrics || '')

watch(
  () => props.selectedNote,
  (newNote) => {
    lyricsInput.value = newNote?.lyrics || ''
    if (activeCategory.value === 'text') {
      nextTick(() => {
        lyricInputRef.value?.focus()
        lyricInputRef.value?.select()
      })
    }
  }
)

watch(activeCategory, (newCat) => {
  if (newCat === 'text') {
    nextTick(() => {
      lyricInputRef.value?.focus()
      lyricInputRef.value?.select()
    })
  }
})

const TIME_SIGNATURES = [
  { beats: 4, beatType: 4, label: '4/4' },
  { beats: 3, beatType: 4, label: '3/4' },
  { beats: 2, beatType: 4, label: '2/4' },
  { beats: 6, beatType: 8, label: '6/8' },
  { beats: 12, beatType: 8, label: '12/8' }
]

const KEY_SIGNATURES = [
  { fifths: 0, label: 'C Maj / A min' },
  { fifths: 1, label: 'G Maj (1♯)' },
  { fifths: 2, label: 'D Maj (2♯)' },
  { fifths: 3, label: 'A Maj (3♯)' },
  { fifths: 4, label: 'E Maj (4♯)' },
  { fifths: -1, label: 'F Maj (1♭)' },
  { fifths: -2, label: 'B♭ Maj (2♭)' },
  { fifths: -3, label: 'E♭ Maj (3♭)' },
  { fifths: -4, label: 'A♭ Maj (4♭)' }
]

const CLEFS = [
  { sign: 'G', line: 2, label: 'Treble (G)', symbol: '𝄞' },
  { sign: 'F', line: 4, label: 'Bass (F)', symbol: '𝄢' },
  { sign: 'C', line: 3, label: 'Alto (C)', symbol: '𝄡' }
]

const handleDynamicsClick = (dyn: string) => {
  emit('setDynamics', dyn)
}

const handleLyricsSubmit = () => {
  emit('setLyrics', lyricsInput.value)
}

const handleLyricKeydown = (e: KeyboardEvent) => {
  if (e.key === ' ' || e.key === 'Tab') {
    e.preventDefault()
    handleLyricsSubmit()
  }
}
</script>

<template>
  <div class="studio-ribbon-container">
    <!-- Category Tabs -->
    <div class="ribbon-tabs">
      <div class="tabs-list">
        <button
          type="button"
          class="ribbon-tab"
          :class="{ active: activeCategory === 'measure' && !isCollapsed }"
          @click="selectCategory('measure')"
        >
          <Sliders :size="13" />
          <span>{{ t('studio.ribbon.addMeasure') }}</span>
        </button>

        <button
          type="button"
          class="ribbon-tab"
          :class="{ active: activeCategory === 'signatures' && !isCollapsed }"
          @click="selectCategory('signatures')"
        >
          <Music :size="13" />
          <span>{{ t('studio.ribbon.keySignature') }} &amp; {{ t('studio.ribbon.clef') }}</span>
        </button>

        <button
          type="button"
          class="ribbon-tab"
          :class="{ active: activeCategory === 'dynamics' && !isCollapsed }"
          @click="selectCategory('dynamics')"
        >
          <Volume2 :size="13" />
          <span>{{ t('studio.ribbon.dynamics') }}</span>
        </button>

        <button
          type="button"
          class="ribbon-tab"
          :class="{ active: activeCategory === 'text' && !isCollapsed }"
          @click="selectCategory('text')"
        >
          <Type :size="13" />
          <span>{{ t('studio.ribbon.lyrics') }}</span>
        </button>
      </div>

      <button
        type="button"
        class="ribbon-collapse-btn"
        :class="{ 'is-collapsed': isCollapsed }"
        :title="isCollapsed ? 'Expand ribbon tools' : 'Collapse ribbon tools'"
        @click="isCollapsed = !isCollapsed"
      >
        <ChevronDown v-if="isCollapsed" :size="13" />
        <ChevronUp v-else :size="13" />
      </button>
    </div>

    <!-- Ribbon Content Deck -->
    <div v-show="!isCollapsed" class="ribbon-deck">
      <!-- 1. MEASURE & LAYOUT TAB -->
      <div v-if="activeCategory === 'measure'" class="ribbon-shelf">
        <!-- Add / Delete Measure -->
        <div class="ribbon-group">
          <span class="group-title">{{ t('studio.ribbon.measureNumber', { current: currentMeasureNum, total: totalMeasures }) }}</span>
          <div class="shelf-buttons">
            <button
              type="button"
              class="ribbon-btn action-positive"
              :title="t('studio.ribbon.addMeasure')"
              @click="emit('addMeasure')"
            >
              <Plus :size="15" />
              <span class="btn-label">{{ t('studio.ribbon.addMeasure') }}</span>
            </button>
            <button
              type="button"
              class="ribbon-btn action-danger"
              :disabled="totalMeasures <= 1"
              :title="t('studio.ribbon.deleteMeasure')"
              @click="emit('deleteMeasure')"
            >
              <Trash2 :size="15" />
              <span class="btn-label">{{ t('studio.ribbon.deleteMeasure') }}</span>
            </button>
            <button
              type="button"
              class="ribbon-btn"
              :title="t('studio.ribbon.fillLine')"
              @click="emit('fillLine')"
            >
              <LayoutGrid :size="14" />
              <span class="btn-label">{{ t('studio.ribbon.fillLine') }}</span>
            </button>
            <button
              type="button"
              class="ribbon-btn action-positive"
              :title="t('studio.ribbon.fillPage')"
              @click="emit('fillPage')"
            >
              <LayoutGrid :size="14" />
              <span class="btn-label">{{ t('studio.ribbon.fillPage') }}</span>
            </button>
          </div>
        </div>

        <div class="shelf-divider"></div>

        <!-- Lines & Voices Operations -->
        <div class="ribbon-group">
          <span class="group-title">{{ t('studio.ribbon.voice') }} &amp; {{ t('studio.ribbon.part') }}</span>
          <div class="shelf-buttons">
            <button
              type="button"
              class="ribbon-btn action-danger"
              :disabled="(totalParts ?? 1) <= 1 || !activePartId"
              :title="activePartName ? `Delete entire line: ${activePartName}` : 'Delete active musical line/part'"
              @click="activePartId && emit('deletePart', activePartId)"
            >
              <Trash2 :size="15" />
              <span class="btn-label">{{ t('studio.ribbon.deletePart') }}{{ activePartName ? ` (${activePartName})` : '' }}</span>
            </button>
            <button
              v-if="hasMultipleVoices && activePartId && activeVoiceNumber"
              type="button"
              class="ribbon-btn action-danger"
              :title="`Delete polyphonic Voice ${activeVoiceNumber} across this line`"
              @click="emit('deleteVoice', { partId: activePartId, voiceNumber: activeVoiceNumber })"
            >
              <Trash2 :size="15" />
              <span class="btn-label">{{ t('studio.ribbon.deleteVoice') }} {{ activeVoiceNumber }}</span>
            </button>
          </div>
        </div>

        <div class="shelf-divider"></div>

        <!-- Transpose Pitch -->
        <div class="ribbon-group">
          <span class="group-title">{{ t('studio.ribbon.transpose') }}</span>
          <div class="shelf-buttons">
            <button
              type="button"
              class="ribbon-btn"
              :title="t('studio.ribbon.transposeUp')"
              @click="emit('transpose', 1)"
            >
              <ChevronUp :size="16" />
              <span class="btn-label">+1</span>
            </button>
            <button
              type="button"
              class="ribbon-btn"
              :title="t('studio.ribbon.transposeDown')"
              @click="emit('transpose', -1)"
            >
              <ChevronDown :size="16" />
              <span class="btn-label">-1</span>
            </button>
            <button
              type="button"
              class="ribbon-btn"
              title="+8va"
              @click="emit('transpose', 12)"
            >
              <span class="btn-label">+8va</span>
            </button>
            <button
              type="button"
              class="ribbon-btn"
              title="-8vb"
              @click="emit('transpose', -12)"
            >
              <span class="btn-label">-8vb</span>
            </button>
          </div>
        </div>
      </div>

      <!-- 2. SIGNATURES & CLEF TAB -->
      <div v-else-if="activeCategory === 'signatures'" class="ribbon-shelf">
        <!-- Time Signature -->
        <div class="ribbon-group">
          <span class="group-title">{{ t('creationModal.timeSignature') }}</span>
          <div class="shelf-buttons">
            <button
              v-for="ts in TIME_SIGNATURES"
              :key="ts.label"
              type="button"
              class="ribbon-btn"
              :class="{ active: measureAttributes.beats === ts.beats && measureAttributes.beatType === ts.beatType }"
              @click="emit('setTimeSignature', ts.beats, ts.beatType)"
            >
              <span class="ts-badge">{{ ts.label }}</span>
            </button>
          </div>
        </div>

        <div class="shelf-divider"></div>

        <!-- Key Signature -->
        <div class="ribbon-group">
          <span class="group-title">{{ t('creationModal.keySignature') }}</span>
          <div class="shelf-buttons">
            <select
              class="ribbon-select"
              :value="measureAttributes.fifths"
              @change="emit('setKeySignature', parseInt(($event.target as HTMLSelectElement).value, 10))"
            >
              <option v-for="ks in KEY_SIGNATURES" :key="ks.fifths" :value="ks.fifths">
                {{ ks.label }}
              </option>
            </select>
          </div>
        </div>

        <div class="shelf-divider"></div>

        <!-- Clef -->
        <div class="ribbon-group">
          <span class="group-title">{{ t('creationModal.startingClef') }}</span>
          <div class="shelf-buttons">
            <button
              v-for="c in CLEFS"
              :key="c.sign"
              type="button"
              class="ribbon-btn"
              :class="{ active: measureAttributes.clefSign === c.sign }"
              @click="emit('setClef', c.sign, c.line)"
            >
              <span class="clef-symbol">{{ c.symbol }}</span>
              <span class="btn-label">{{ c.label.split(' ')[0] }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- 3. DYNAMICS TAB -->
      <div v-else-if="activeCategory === 'dynamics'" class="ribbon-shelf">
        <div class="ribbon-group">
          <span class="group-title">{{ t('studio.ribbon.dynamics') }}</span>
          <div class="shelf-buttons">
            <button
              v-for="dyn in ['pp', 'p', 'mp', 'mf', 'f', 'ff']"
              :key="dyn"
              type="button"
              draggable="true"
              class="ribbon-btn dynamic-btn"
              :class="{ active: selectedNote?.dynamics === dyn }"
              :title="`Dynamic expression ${dyn} (Drag or click to apply)`"
              @click="handleDynamicsClick(dyn)"
              @dragstart="handleDragStart($event, { type: 'dynamic', value: dyn, label: dyn, symbol: dyn })"
              @dragend="handleDragEnd"
            >
              <span class="dynamic-symbol">{{ dyn }}</span>
            </button>
          </div>
        </div>
        <div class="shelf-info">
          <span class="info-text">💡 {{ t('studio.ribbon.dynamicHint') }}</span>
        </div>
      </div>

      <!-- 4. TEXT & LYRICS TAB -->
      <div v-else-if="activeCategory === 'text'" class="ribbon-shelf">
        <div class="ribbon-group lyrics-group">
          <span class="group-title">{{ t('studio.ribbon.lyrics') }}</span>
          <form class="lyrics-form" @submit.prevent="handleLyricsSubmit">
            <input
              ref="lyricInputRef"
              v-model="lyricsInput"
              type="text"
              class="ribbon-input"
              :placeholder="t('studio.ribbon.lyricsPlaceholder')"
              :disabled="!selectedNote"
              @keydown="handleLyricKeydown"
            />
            <button
              type="submit"
              class="ribbon-btn apply-btn"
              :disabled="!selectedNote"
              title="Apply lyrics (Enter, Space, or Tab advances to next note)"
            >
              <Check :size="14" />
              <span>{{ t('studio.ribbon.apply') }}</span>
            </button>
          </form>
        </div>
        <div class="shelf-info">
          <span class="info-text" v-if="selectedNote">
            Editing note <strong>{{ selectedNote.summary }}</strong>. Press <kbd>Space</kbd>, <kbd>Tab</kbd>, or <kbd>Enter</kbd> to jump to next note.
          </span>
          <span class="info-text muted" v-else>
            Select a note first to attach lyrics or syllable text.
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.studio-ribbon-container {
  display: flex;
  flex-direction: column;
  background: var(--bg-card, #151b28);
  border-bottom: 1px solid var(--border, #242f48);
  user-select: none;
  z-index: 10;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.ribbon-tabs {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 8px 0 8px;
  background: var(--bg-subtle, #1c2336);
  border-bottom: 1px solid var(--border, #242f48);
}

.tabs-list {
  display: flex;
  align-items: center;
  gap: 3px;
  overflow-x: auto;
  scrollbar-width: none;
}

.tabs-list::-webkit-scrollbar {
  display: none;
}

.ribbon-collapse-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  background: transparent;
  border: none;
  color: var(--text-secondary, #94a3b8);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
  margin-bottom: 2px;
}

.ribbon-collapse-btn:hover {
  background: var(--bg-hover, rgba(255, 255, 255, 0.08));
  color: var(--text-primary, #ffffff);
}

.ribbon-tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  font-size: 0.76rem;
  font-weight: 500;
  color: var(--text-secondary, #94a3b8);
  background: transparent;
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: 5px 5px 0 0;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.ribbon-tab:hover {
  color: var(--text-primary, #ffffff);
  background: var(--bg-hover, rgba(255, 255, 255, 0.04));
}

.ribbon-tab.active {
  color: var(--color-primary, #6366f1);
  background: var(--bg-card, #151b28);
  border-color: var(--border, #242f48);
  font-weight: 600;
  position: relative;
}

.ribbon-tab.active::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 0;
  right: 0;
  height: 1px;
  background: var(--bg-card, #151b28);
}

.ribbon-deck {
  padding: 4px 10px;
  min-height: 40px;
  display: flex;
  align-items: center;
  background: var(--bg-card, #151b28);
  overflow-x: auto;
}

.ribbon-shelf {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  min-width: max-content;
}

.ribbon-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.group-title {
  font-size: 0.6rem;
  font-weight: 700;
  color: var(--text-secondary, #64748b);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.shelf-buttons {
  display: flex;
  align-items: center;
  gap: 4px;
}

.shelf-divider {
  width: 1px;
  height: 24px;
  background: var(--border, #242f48);
}

.ribbon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 27px;
  padding: 0 8px;
  background: var(--bg-elevated, #222c42);
  border: 1px solid var(--border, #242f48);
  border-radius: 5px;
  color: var(--text-primary, #ffffff);
  font-size: 0.74rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.ribbon-btn:hover:not(:disabled) {
  border-color: var(--color-primary, #6366f1);
  background: var(--color-primary-light, rgba(99, 102, 241, 0.12));
  color: var(--color-primary, #6366f1);
}

.ribbon-btn.active {
  background: var(--color-primary-light, rgba(99, 102, 241, 0.25));
  border-color: var(--color-primary, #818cf8);
  color: var(--color-primary, #6366f1);
}

.ribbon-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.action-positive:hover:not(:disabled) {
  border-color: var(--color-success, #10b981);
  background: var(--color-success-light, rgba(16, 185, 129, 0.15));
  color: var(--color-success, #10b981);
}

.action-danger:hover:not(:disabled) {
  border-color: var(--color-danger, #ef4444);
  background: var(--color-danger-light, rgba(239, 68, 68, 0.15));
  color: var(--color-danger, #ef4444);
}

.dynamic-btn {
  font-family: serif;
  font-style: italic;
  font-weight: bold;
  font-size: 1.15rem;
  min-width: 36px;
  cursor: grab;
}

.dynamic-btn:active {
  cursor: grabbing;
}

.ts-badge {
  font-weight: 700;
  font-size: 0.85rem;
}

.clef-symbol {
  font-size: 1.2rem;
  margin-right: 2px;
}

.ribbon-select {
  height: 32px;
  background: var(--input-bg, #121824);
  border: 1px solid var(--input-border, var(--border, #242f48));
  border-radius: 6px;
  color: var(--text-primary, #ffffff);
  font-size: 0.8rem;
  padding: 0 8px;
  cursor: pointer;
  outline: none;
}

.ribbon-select:focus {
  border-color: var(--color-primary, #6366f1);
}

.lyrics-form {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ribbon-input {
  height: 32px;
  background: var(--input-bg, #121824);
  border: 1px solid var(--input-border, var(--border, #242f48));
  border-radius: 6px;
  color: var(--text-primary, #ffffff);
  font-size: 0.85rem;
  padding: 0 10px;
  outline: none;
  min-width: 220px;
}

.ribbon-input:focus {
  border-color: var(--input-border-focus, var(--color-primary, #6366f1));
}

.apply-btn {
  background: var(--color-primary, #4f46e5);
  border-color: var(--color-primary, #6366f1);
  color: #ffffff;
}

.apply-btn:hover:not(:disabled) {
  background: var(--color-primary-hover, #4338ca);
  color: #ffffff;
}

.shelf-info {
  margin-left: auto;
  font-size: 0.75rem;
  color: var(--text-secondary, #94a3b8);
}

.shelf-info kbd {
  background: var(--bg-elevated, rgba(255, 255, 255, 0.08));
  border: 1px solid var(--border, #242f48);
  border-radius: 4px;
  padding: 1px 4px;
  font-size: 0.7rem;
  color: var(--text-primary, #ffffff);
}

.shelf-info .muted {
  color: var(--text-muted, #64748b);
}

@media (max-width: 768px) {
  .ribbon-btn {
    height: 38px;
    min-height: 38px;
    padding: 0 10px;
    font-size: 0.82rem;
  }
  .ribbon-deck {
    min-height: 48px;
    padding: 6px 8px;
  }
  .ribbon-input {
    font-size: 16px !important;
    height: 38px;
  }
  .shelf-info {
    display: none;
  }
}
</style>
