<script setup lang="ts">
import { ref, computed } from 'vue';
import { X, ChevronLeft, ChevronRight } from 'lucide-vue-next';
import { useNativePlatform } from '../../composables/useNativePlatform';

const props = defineProps<{
  activeDuration?: string;
}>();

const emit = defineEmits<{
  (e: 'close'): void;
  (e: 'noteInput', note: { step: string; octave: number; alter: number }): void;
  (e: 'selectDuration', duration: string): void;
}>();

const { triggerHapticLight } = useNativePlatform();

// Octave offset: default octave 4 (Middle C)
const baseOctave = ref(4);

const DURATIONS = [
  { type: 'quarter', symbol: '𝅘𝅥', label: '1/4' },
  { type: 'eighth', symbol: '𝅘𝅥𝅮', label: '1/8' },
  { type: '16th', symbol: '𝅘𝅥𝅯', label: '1/16' },
  { type: 'half', symbol: '𝅗𝅥', label: '1/2' },
  { type: 'whole', symbol: '𝅝', label: '1/1' },
];

interface PianoKey {
  step: string;
  alter: number;
  label: string;
  isBlack: boolean;
  octaveOffset: number; // 0 for first octave, 1 for second octave
}

// 1-Octave + High C Keyboard Definition (8 white keys = ~48px per key on mobile)
const KEYS: PianoKey[] = [
  // Octave 0 (C to B)
  { step: 'C', alter: 0, label: 'C', isBlack: false, octaveOffset: 0 },
  { step: 'C', alter: 1, label: 'C♯', isBlack: true, octaveOffset: 0 },
  { step: 'D', alter: 0, label: 'D', isBlack: false, octaveOffset: 0 },
  { step: 'D', alter: 1, label: 'D♯', isBlack: true, octaveOffset: 0 },
  { step: 'E', alter: 0, label: 'E', isBlack: false, octaveOffset: 0 },
  { step: 'F', alter: 0, label: 'F', isBlack: false, octaveOffset: 0 },
  { step: 'F', alter: 1, label: 'F♯', isBlack: true, octaveOffset: 0 },
  { step: 'G', alter: 0, label: 'G', isBlack: false, octaveOffset: 0 },
  { step: 'G', alter: 1, label: 'G♯', isBlack: true, octaveOffset: 0 },
  { step: 'A', alter: 0, label: 'A', isBlack: false, octaveOffset: 0 },
  { step: 'A', alter: 1, label: 'A♯', isBlack: true, octaveOffset: 0 },
  { step: 'B', alter: 0, label: 'B', isBlack: false, octaveOffset: 0 },
  // High C of Octave 1
  { step: 'C', alter: 0, label: 'C', isBlack: false, octaveOffset: 1 },
];

const whiteKeys = computed(() =>
  KEYS.filter((k) => !k.isBlack).map((k, index) => ({
    ...k,
    octave: baseOctave.value + k.octaveOffset,
    whiteIndex: index,
  }))
);

const blackKeys = computed(() => {
  const result: (PianoKey & { octave: number; leftPercent: number })[] = [];
  const whiteKeyCount = 8;
  const whiteKeyWidthPercent = 100 / whiteKeyCount;

  KEYS.forEach((k) => {
    if (!k.isBlack) return;
    const oct = baseOctave.value + k.octaveOffset;
    let baseWhite = 0;
    if (k.step === 'C') baseWhite = 0;
    else if (k.step === 'D') baseWhite = 1;
    else if (k.step === 'F') baseWhite = 3;
    else if (k.step === 'G') baseWhite = 4;
    else if (k.step === 'A') baseWhite = 5;

    const totalWhiteIndex = baseWhite + k.octaveOffset * 7;
    const leftPercent = (totalWhiteIndex + 1) * whiteKeyWidthPercent;
    result.push({
      ...k,
      octave: oct,
      leftPercent,
    });
  });
  return result;
});

const activeKeyLabel = ref<string | null>(null);

const handleKeyPress = (key: { step: string; octave: number; alter: number; label: string }) => {
  triggerHapticLight();
  activeKeyLabel.value = `${key.label}${key.octave}`;
  emit('noteInput', {
    step: key.step,
    octave: key.octave,
    alter: key.alter,
  });
  setTimeout(() => {
    if (activeKeyLabel.value === `${key.label}${key.octave}`) {
      activeKeyLabel.value = null;
    }
  }, 200);
};

const shiftOctave = (delta: number) => {
  triggerHapticLight();
  baseOctave.value = Math.max(1, Math.min(7, baseOctave.value + delta));
};
</script>

<template>
  <div class="mobile-virtual-keyboard" role="region" aria-label="Virtual Piano Keyboard">
    <!-- Top Action Bar -->
    <div class="keyboard-toolbar">
      <!-- Octave Shifter -->
      <div class="octave-controls">
        <button
          class="octave-btn"
          :disabled="baseOctave <= 1"
          @click="shiftOctave(-1)"
          aria-label="Lower Octave"
        >
          <ChevronLeft :size="14" />
          <span>-8va</span>
        </button>
        <span class="octave-badge">C{{ baseOctave }}–C{{ baseOctave + 1 }}</span>
        <button
          class="octave-btn"
          :disabled="baseOctave >= 7"
          @click="shiftOctave(1)"
          aria-label="Higher Octave"
        >
          <span>+8va</span>
          <ChevronRight :size="14" />
        </button>
      </div>

      <!-- Quick Duration Selection -->
      <div class="duration-chips">
        <button
          v-for="d in DURATIONS"
          :key="d.type"
          class="duration-chip"
          :class="{ active: activeDuration === d.type }"
          @click="emit('selectDuration', d.type)"
        >
          <span class="dur-sym">{{ d.symbol }}</span>
          <span class="dur-lbl">{{ d.label }}</span>
        </button>
      </div>

      <!-- Close Button -->
      <button class="close-btn" @click="emit('close')" aria-label="Close Keyboard">
        <X :size="16" />
      </button>
    </div>

    <!-- Piano Bed -->
    <div class="piano-bed">
      <!-- White Keys -->
      <div class="white-keys-layer">
        <button
          v-for="k in whiteKeys"
          :key="`w_${k.step}_${k.octave}`"
          class="white-key"
          :class="{ active: activeKeyLabel === `${k.label}${k.octave}` }"
          @pointerdown.prevent="handleKeyPress(k)"
        >
          <span class="white-key-label">{{ k.label }}{{ k.octave }}</span>
        </button>
      </div>

      <!-- Black Keys -->
      <div class="black-keys-layer">
        <button
          v-for="k in blackKeys"
          :key="`b_${k.step}_${k.octave}_${k.alter}`"
          class="black-key"
          :style="{ left: `${k.leftPercent}%` }"
          :class="{ active: activeKeyLabel === `${k.label}${k.octave}` }"
          @pointerdown.prevent="handleKeyPress(k)"
        >
          <span class="black-key-label">{{ k.label }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mobile-virtual-keyboard {
  position: relative;
  width: 100%;
  background: var(--bg-primary, #0f172a);
  border-top: 1px solid var(--border, rgba(99, 102, 241, 0.35));
  user-select: none;
  -webkit-user-select: none;
  touch-action: manipulation;
}

.keyboard-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: var(--bg-card, rgba(30, 41, 59, 0.95));
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  gap: 6px;
}

.octave-controls {
  display: flex;
  align-items: center;
  gap: 4px;
}

.octave-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
  background: var(--bg-elevated, rgba(255, 255, 255, 0.08));
  border: 1px solid var(--border, rgba(255, 255, 255, 0.12));
  color: var(--text-primary, #f1f5f9);
  border-radius: 6px;
  min-height: 36px;
  padding: 0 8px;
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
}

.octave-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.octave-badge {
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--accent, #6366f1);
  padding: 0 4px;
  font-family: ui-monospace, monospace;
}

.duration-chips {
  display: flex;
  align-items: center;
  gap: 4px;
  overflow-x: auto;
}

.duration-chip {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  background: var(--bg-elevated, rgba(255, 255, 255, 0.06));
  border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  color: var(--text-secondary, #94a3b8);
  border-radius: 6px;
  min-height: 36px;
  padding: 0 8px;
  font-size: 0.7rem;
  font-weight: 600;
  cursor: pointer;
}

.duration-chip.active {
  background: var(--accent-soft, rgba(99, 102, 241, 0.25));
  border-color: var(--accent, #6366f1);
  color: var(--text-primary, #ffffff);
}

.dur-sym {
  font-size: 0.95rem;
  line-height: 1;
}

.close-btn {
  background: var(--bg-elevated, transparent);
  border: 1px solid var(--border, transparent);
  color: var(--text-secondary, #94a3b8);
  width: 36px;
  height: 36px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.piano-bed {
  position: relative;
  height: 132px;
  width: 100%;
  overflow: hidden;
  background: #020617;
}

.white-keys-layer {
  display: flex;
  height: 100%;
  width: 100%;
}

.white-key {
  flex: 1;
  height: 100%;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-top: none;
  border-radius: 0 0 6px 6px;
  cursor: pointer;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding-bottom: 8px;
  outline: none;
  transition: background-color 0.08s ease;
}

.white-key.active,
.white-key:active {
  background: #bfdbfe;
}

.white-key-label {
  font-size: 0.75rem;
  font-weight: 700;
  color: #475569;
  pointer-events: none;
}

.black-keys-layer {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 62%;
  pointer-events: none;
}

.black-key {
  position: absolute;
  transform: translateX(-50%);
  width: calc(100% / 8 * 0.62);
  height: 100%;
  background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
  border: 1px solid #020617;
  border-radius: 0 0 5px 5px;
  pointer-events: auto;
  cursor: pointer;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding-bottom: 6px;
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.5);
  outline: none;
  transition: background 0.08s ease;
}

.black-key.active,
.black-key:active {
  background: #4f46e5;
}

.black-key-label {
  font-size: 0.65rem;
  font-weight: 700;
  color: #e2e8f0;
  pointer-events: none;
}
</style>
