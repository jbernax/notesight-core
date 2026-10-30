<script setup lang="ts">
import { ref } from 'vue';
import {
  Undo2,
  Redo2,
  Plus,
  Trash2,
  SlidersHorizontal,
  MessageSquare,
  Sliders,
  X,
  Type,
  Volume2,
  Piano,
} from 'lucide-vue-next';
import type { ParsedNote } from '../../composables/useScoreMutation';
import { useNativePlatform } from '../../composables/useNativePlatform';
import MobileVirtualKeyboard from './MobileVirtualKeyboard.vue';

const props = defineProps<{
  selectedNote: ParsedNote | null;
  canUndo: boolean;
  canRedo: boolean;
  currentMeasureNum: number;
  totalMeasures: number;
}>();

const emit = defineEmits<{
  (e: 'setNoteType', type: string): void;
  (e: 'setRestType', type: string): void;
  (e: 'toggleDot'): void;
  (e: 'toggleRest'): void;
  (e: 'toggleTie'): void;
  (e: 'toggleAccidental', alter: number): void;
  (e: 'transpose', semitones: number): void;
  (e: 'setPitch', pitch: { step: string; octave: number; alter: number }): void;
  (e: 'addMeasure'): void;
  (e: 'deleteMeasure'): void;
  (e: 'fillLine'): void;
  (e: 'fillPage'): void;
  (e: 'undo'): void;
  (e: 'redo'): void;
  (e: 'toggleMixer'): void;
  (e: 'toggleAnnotations'): void;
  (e: 'setTimeSignature', beats: number, beatType: number): void;
  (e: 'setKeySignature', fifths: number): void;
  (e: 'setClef', sign: string, line: number): void;
  (e: 'setLyrics', lyrics: string): void;
  (e: 'setDynamics', dynamic: string): void;
}>();

const { triggerHapticLight, triggerHapticMedium } = useNativePlatform();

const isKeyboardOpen = ref(false);

const handleKeyboardNoteInput = (pitch: { step: string; octave: number; alter: number }) => {
  emit('setPitch', pitch);
};

const isMacrosOpen = ref(false);
const activeMacroTab = ref<'signatures' | 'lyrics' | 'dynamics'>('signatures');
const lyricInput = ref('');

const NOTE_DURATIONS = [
  { type: 'whole', symbol: '𝅝', label: 'Whole' },
  { type: 'half', symbol: '𝅗𝅥', label: 'Half' },
  { type: 'quarter', symbol: '𝅘𝅥', label: 'Quarter' },
  { type: 'eighth', symbol: '𝅘𝅥𝅮', label: 'Eighth' },
  { type: '16th', symbol: '𝅘𝅥𝅯', label: '16th' },
  { type: '32nd', symbol: '𝅘𝅥𝅰', label: '32nd' },
];

const ACCIDENTALS = [
  { alter: -2, symbol: '𝄫', label: 'Double Flat' },
  { alter: -1, symbol: '♭', label: 'Flat' },
  { alter: 0, symbol: '♮', label: 'Natural' },
  { alter: 1, symbol: '♯', label: 'Sharp' },
  { alter: 2, symbol: '𝄪', label: 'Double Sharp' },
];

const DYNAMICS_LIST = ['pp', 'p', 'mp', 'mf', 'f', 'ff'];

const applyDuration = (type: string) => {
  triggerHapticLight();
  if (props.selectedNote?.isRest) {
    emit('setRestType', type);
  } else {
    emit('setNoteType', type);
  }
};

const applyAccidental = (alter: number) => {
  triggerHapticLight();
  emit('toggleAccidental', alter);
};

const applyTranspose = (semitones: number) => {
  triggerHapticLight();
  emit('transpose', semitones);
};

const applyLyrics = () => {
  if (!lyricInput.value.trim()) return;
  triggerHapticMedium();
  emit('setLyrics', lyricInput.value.trim());
  lyricInput.value = '';
};

const applyDynamic = (dyn: string) => {
  triggerHapticLight();
  emit('setDynamics', dyn);
};
</script>

<template>
  <div class="mobile-studio-dock" role="toolbar" aria-label="Mobile Notation Palette">
    <!-- Macro Drawer Extension (Time/Key/Clef, Lyrics, Dynamics) -->
    <div v-if="isMacrosOpen" class="mobile-macros-drawer">
      <div class="macros-drawer-header">
        <div class="macro-tabs">
          <button
            class="macro-tab-btn"
            :class="{ active: activeMacroTab === 'signatures' }"
            @click="activeMacroTab = 'signatures'"
          >
            <Sliders :size="13" />
            <span>Signatures</span>
          </button>
          <button
            class="macro-tab-btn"
            :class="{ active: activeMacroTab === 'lyrics' }"
            @click="activeMacroTab = 'lyrics'"
          >
            <Type :size="13" />
            <span>Lyrics</span>
          </button>
          <button
            class="macro-tab-btn"
            :class="{ active: activeMacroTab === 'dynamics' }"
            @click="activeMacroTab = 'dynamics'"
          >
            <Volume2 :size="13" />
            <span>Dynamics</span>
          </button>
        </div>
        <button class="macro-close-btn" @click="isMacrosOpen = false" aria-label="Close Drawer">
          <X :size="16" />
        </button>
      </div>

      <!-- Tab 1: Time, Key, Clef, Layout Macros -->
      <div v-if="activeMacroTab === 'signatures'" class="macro-content-pane">
        <div class="macro-row">
          <span class="macro-row-label">Time Signature</span>
          <div class="macro-chip-group">
            <button class="macro-chip-btn" @click="emit('setTimeSignature', 4, 4)">4/4</button>
            <button class="macro-chip-btn" @click="emit('setTimeSignature', 3, 4)">3/4</button>
            <button class="macro-chip-btn" @click="emit('setTimeSignature', 2, 4)">2/4</button>
            <button class="macro-chip-btn" @click="emit('setTimeSignature', 6, 8)">6/8</button>
          </div>
        </div>

        <div class="macro-row">
          <span class="macro-row-label">Key Signature</span>
          <div class="macro-chip-group">
            <button class="macro-chip-btn" @click="emit('setKeySignature', 0)">C Maj</button>
            <button class="macro-chip-btn" @click="emit('setKeySignature', 1)">1 ♯ (G)</button>
            <button class="macro-chip-btn" @click="emit('setKeySignature', 2)">2 ♯ (D)</button>
            <button class="macro-chip-btn" @click="emit('setKeySignature', -1)">1 ♭ (F)</button>
            <button class="macro-chip-btn" @click="emit('setKeySignature', -2)">2 ♭ (B♭)</button>
          </div>
        </div>

        <div class="macro-row">
          <span class="macro-row-label">Clef &amp; Layout</span>
          <div class="macro-chip-group">
            <button class="macro-chip-btn" @click="emit('setClef', 'G', 2)">𝄞 Treble</button>
            <button class="macro-chip-btn" @click="emit('setClef', 'F', 4)">𝄢 Bass</button>
            <button class="macro-chip-btn" @click="emit('setClef', 'C', 3)">𝄡 Alto</button>
            <button class="macro-chip-btn" @click="emit('fillLine')">+ Fill Line (4m)</button>
            <button class="macro-chip-btn" @click="emit('fillPage')">+ Fill Page (16m)</button>
          </div>
        </div>
      </div>

      <!-- Tab 2: Lyrics -->
      <div v-else-if="activeMacroTab === 'lyrics'" class="macro-content-pane">
        <div class="lyrics-input-row">
          <input
            v-model="lyricInput"
            type="text"
            placeholder="Type lyric syllable..."
            class="mobile-lyric-field"
            @keyup.enter="applyLyrics"
          />
          <button class="mobile-apply-btn" @click="applyLyrics">Apply</button>
        </div>
      </div>

      <!-- Tab 3: Dynamics -->
      <div v-else class="macro-content-pane">
        <div class="macro-chip-group dynamics-grid">
          <button
            v-for="dyn in DYNAMICS_LIST"
            :key="dyn"
            class="macro-chip-btn dynamic-btn"
            @click="applyDynamic(dyn)"
          >
            {{ dyn }}
          </button>
        </div>
      </div>
    </div>

    <!-- Top Action Bar (Selected Note Status, Pitch Steppers, Undo/Redo) -->
    <div class="palette-subbar">
      <!-- Selected Note Info -->
      <div class="note-status-badge">
        <template v-if="selectedNote">
          <span class="status-name">{{ selectedNote.summary }}</span>
          <span class="status-dur">{{ selectedNote.type }}</span>
        </template>
        <template v-else>
          <span class="status-hint">Tap note to edit</span>
        </template>
      </div>

      <!-- Pitch Stepper (-1, +1 semitones) -->
      <div class="pitch-stepper-cluster">
        <button class="stepper-action-btn" title="Transpose -1 Semitone" @click="applyTranspose(-1)">
          -1
        </button>
        <button class="stepper-action-btn" title="Transpose +1 Semitone" @click="applyTranspose(1)">
          +1
        </button>
        <button class="stepper-action-btn" title="Octave Down (-12)" @click="applyTranspose(-12)">
          -8va
        </button>
        <button class="stepper-action-btn" title="Octave Up (+12)" @click="applyTranspose(12)">
          +8va
        </button>
      </div>

      <!-- Undo / Redo & Macros -->
      <div class="quick-system-actions">
        <button
          class="subbar-icon-btn"
          :disabled="!canUndo"
          title="Undo"
          @click="emit('undo')"
        >
          <Undo2 :size="16" />
        </button>
        <button
          class="subbar-icon-btn"
          :disabled="!canRedo"
          title="Redo"
          @click="emit('redo')"
        >
          <Redo2 :size="16" />
        </button>
        <button
          class="subbar-icon-btn"
          :class="{ active: isKeyboardOpen }"
          title="Virtual Piano Keyboard"
          @click="isKeyboardOpen = !isKeyboardOpen"
        >
          <Piano :size="16" />
        </button>
        <button
          class="subbar-icon-btn"
          :class="{ active: isMacrosOpen }"
          title="Score Signatures & Lyrics"
          @click="isMacrosOpen = !isMacrosOpen"
        >
          <Sliders :size="16" />
        </button>
        <button
          class="subbar-icon-btn"
          title="Audio Mixer"
          @click="emit('toggleMixer')"
        >
          <SlidersHorizontal :size="16" />
        </button>
        <button
          class="subbar-icon-btn"
          title="Annotations"
          @click="emit('toggleAnnotations')"
        >
          <MessageSquare :size="16" />
        </button>
      </div>
    </div>

    <!-- Main Tool Rail (Scrollable Durations, Accidentals, Modifiers) -->
    <div class="palette-tools-strip">
      <!-- Note Durations -->
      <div class="tool-section">
        <button
          v-for="dur in NOTE_DURATIONS"
          :key="dur.type"
          class="studio-tool-btn"
          :class="{ active: selectedNote?.type === dur.type && !selectedNote?.isRest }"
          :title="dur.label"
          @click="applyDuration(dur.type)"
        >
          <span class="tool-sym">{{ dur.symbol }}</span>
        </button>
      </div>

      <div class="tool-divider"></div>

      <!-- Modifiers: Dot, Tie, Rest -->
      <div class="tool-section">
        <button
          class="studio-tool-btn"
          :class="{ active: selectedNote?.isDotted }"
          title="Toggle Dot"
          @click="emit('toggleDot')"
        >
          <span class="tool-sym">•</span>
        </button>
        <button
          class="studio-tool-btn"
          :class="{ active: selectedNote?.isRest }"
          title="Toggle Rest"
          @click="emit('toggleRest')"
        >
          <span class="tool-sym">𝄽</span>
        </button>
        <button
          class="studio-tool-btn"
          :class="{ active: selectedNote?.hasTieStart || selectedNote?.hasTieStop }"
          title="Toggle Tie"
          @click="emit('toggleTie')"
        >
          <span class="tool-sym">⌒</span>
        </button>
      </div>

      <div class="tool-divider"></div>

      <!-- Accidentals -->
      <div class="tool-section">
        <button
          v-for="acc in ACCIDENTALS"
          :key="acc.alter"
          class="studio-tool-btn"
          :class="{ active: selectedNote?.alter === acc.alter }"
          :title="acc.label"
          @click="applyAccidental(acc.alter)"
        >
          <span class="tool-sym">{{ acc.symbol }}</span>
        </button>
      </div>

      <div class="tool-divider"></div>

      <!-- Measure Ops -->
      <div class="tool-section">
        <button
          class="studio-tool-btn action-op"
          title="Add Measure"
          @click="emit('addMeasure')"
        >
          <Plus :size="18" />
        </button>
        <button
          class="studio-tool-btn action-op danger"
          title="Delete Measure"
          @click="emit('deleteMeasure')"
        >
          <Trash2 :size="18" />
        </button>
      </div>
    </div>

    <!-- Virtual Piano Keyboard Modal / Drawer -->
    <MobileVirtualKeyboard
      v-if="isKeyboardOpen"
      :active-duration="selectedNote?.type || 'quarter'"
      @close="isKeyboardOpen = false"
      @note-input="handleKeyboardNoteInput"
      @select-duration="(dur) => emit('setNoteType', dur)"
    />
  </div>
</template>

<style scoped>
.mobile-studio-dock {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 8500;
  background: var(--bg-glass-heavy, rgba(15, 23, 42, 0.96));
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-top: 1px solid var(--border, rgba(255, 255, 255, 0.12));
  padding-bottom: max(var(--sab, 0px), 6px);
  display: flex;
  flex-direction: column;
  box-shadow: 0 -8px 28px rgba(0, 0, 0, 0.35);
}

.palette-subbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: var(--bg-card, rgba(30, 41, 59, 0.85));
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  font-size: 0.75rem;
  gap: 6px;
}

.note-status-badge {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 82px;
}

.status-name {
  color: var(--accent, #6366f1);
  font-family: ui-monospace, monospace;
  font-weight: 700;
  font-size: 0.85rem;
}

.status-dur {
  font-size: 0.72rem;
  color: var(--text-secondary, #94a3b8);
  text-transform: capitalize;
}

.status-hint {
  font-size: 0.72rem;
  color: var(--text-secondary, #94a3b8);
}

.pitch-stepper-cluster {
  display: flex;
  align-items: center;
  gap: 4px;
}

.stepper-action-btn {
  background: var(--bg-elevated, rgba(255, 255, 255, 0.08));
  border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
  color: var(--text-primary, #f1f5f9);
  border-radius: 6px;
  min-height: 36px;
  min-width: 36px;
  padding: 0 7px;
  font-size: 0.72rem;
  font-weight: 700;
  cursor: pointer;
}

.quick-system-actions {
  display: flex;
  align-items: center;
  gap: 3px;
}

.subbar-icon-btn {
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-secondary, #94a3b8);
  width: 38px;
  height: 38px;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.subbar-icon-btn.active {
  color: var(--accent, #6366f1);
  background: var(--accent-soft, rgba(99, 102, 241, 0.2));
  border-color: var(--accent, #6366f1);
}

.subbar-icon-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.palette-tools-strip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.tool-section {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
}

.tool-divider {
  width: 1px;
  height: 28px;
  background: var(--border, rgba(255, 255, 255, 0.12));
  flex-shrink: 0;
  margin: 0 2px;
}

.studio-tool-btn {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: var(--bg-elevated, rgba(255, 255, 255, 0.06));
  border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
  color: var(--text-primary, #ffffff);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.12s ease;
  user-select: none;
}

.studio-tool-btn.active {
  background: var(--accent, #6366f1);
  border-color: var(--accent-hover, #818cf8);
  color: #ffffff;
  box-shadow: 0 2px 10px rgba(99, 102, 241, 0.45);
}

.studio-tool-btn.action-op {
  color: var(--accent, #6366f1);
}

.studio-tool-btn.action-op.danger {
  color: var(--error, #ef4444);
}

.tool-sym {
  font-size: 1.25rem;
  line-height: 1;
}

/* Macros Drawer */
.mobile-macros-drawer {
  background: var(--bg-card, #1e293b);
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.1));
  padding: 10px 12px;
  animation: slideDownDrawer 0.2s ease-out;
}

@keyframes slideDownDrawer {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.macros-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.macro-tabs {
  display: flex;
  gap: 6px;
}

.macro-tab-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-secondary, #94a3b8);
  min-height: 36px;
  padding: 0 10px;
  border-radius: 8px;
  font-size: 0.76rem;
  font-weight: 600;
  cursor: pointer;
}

.macro-tab-btn.active {
  background: var(--accent-soft, rgba(99, 102, 241, 0.15));
  border-color: var(--accent, #6366f1);
  color: var(--accent, #818cf8);
}

.macro-close-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary, #94a3b8);
  width: 36px;
  height: 36px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.macro-content-pane {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.macro-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.macro-row-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-secondary, #94a3b8);
}

.macro-chip-group {
  display: flex;
  gap: 6px;
  overflow-x: auto;
}

.macro-chip-btn {
  background: var(--bg-elevated, rgba(255, 255, 255, 0.08));
  border: 1px solid var(--border, rgba(255, 255, 255, 0.12));
  color: var(--text-primary, #f1f5f9);
  border-radius: 8px;
  min-height: 38px;
  padding: 0 12px;
  font-size: 0.76rem;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.dynamics-grid {
  justify-content: space-around;
  width: 100%;
}

.dynamic-btn {
  font-style: italic;
  font-weight: 700;
  font-size: 0.9rem;
  min-width: 46px;
}

.lyrics-input-row {
  display: flex;
  gap: 8px;
}

.mobile-lyric-field {
  flex: 1;
  background: var(--bg-input, rgba(0, 0, 0, 0.35));
  border: 1px solid var(--border, rgba(255, 255, 255, 0.15));
  border-radius: 8px;
  color: var(--text-primary, #ffffff);
  min-height: 40px;
  padding: 0 12px;
  font-size: 0.9rem;
  outline: none;
}

.mobile-apply-btn {
  background: var(--accent, #6366f1);
  border: none;
  color: #ffffff;
  min-height: 40px;
  padding: 0 16px;
  border-radius: 8px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}

@media (min-width: 769px) {
  .mobile-studio-dock {
    display: none;
  }
}
</style>
