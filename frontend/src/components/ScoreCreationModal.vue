<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { t } from '../i18n'
import {
  X,
  Sparkles,
  FilePlus,
  Clock,
  Compass
} from 'lucide-vue-next'

const props = defineProps<{
  isOpen: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'create', payload: { title: string; composer: string; musicXml: string }): void
}>()

const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && props.isOpen) {
    emit('close')
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})

interface BlankScoreOptions {
  title: string
  composer: string
  clef: 'treble' | 'bass' | 'alto' | 'tenor'
  fifths: number
  beats: number
  beatType: number
  tempo: number
  measureCount: number
}

const title = ref('Untitled Composition')
const composer = ref('')
const selectedTimePreset = ref('4/4')
const customBeats = ref(4)
const customBeatType = ref(4)
const selectedFifths = ref(0)
const selectedClef = ref<'treble' | 'bass' | 'alto' | 'tenor'>('treble')
const measureCount = ref(16)
const tempo = ref(120)

const TIME_PRESETS = [
  { id: '4/4', beats: 4, beatType: 4, label: '4/4', desc: 'Common Time' },
  { id: '3/4', beats: 3, beatType: 4, label: '3/4', desc: 'Waltz Time' },
  { id: '2/4', beats: 2, beatType: 4, label: '2/4', desc: 'March Time' },
  { id: '6/8', beats: 6, beatType: 8, label: '6/8', desc: 'Compound Duple' },
  { id: 'custom', beats: 4, beatType: 4, label: 'Custom', desc: 'User Defined' }
]

const KEY_OPTIONS = [
  { fifths: 0, label: 'C Major / A Minor', accidentals: 'Natural' },
  { fifths: 1, label: 'G Major / E Minor', accidentals: '1 ♯ (F♯)' },
  { fifths: 2, label: 'D Major / B Minor', accidentals: '2 ♯ (F♯, C♯)' },
  { fifths: 3, label: 'A Major / F♯ Minor', accidentals: '3 ♯ (F♯, C♯, G♯)' },
  { fifths: 4, label: 'E Major / C♯ Minor', accidentals: '4 ♯ (F♯, C♯, G♯, D♯)' },
  { fifths: -1, label: 'F Major / D Minor', accidentals: '1 ♭ (B♭)' },
  { fifths: -2, label: 'B♭ Major / G Minor', accidentals: '2 ♭ (B♭, E♭)' },
  { fifths: -3, label: 'E♭ Major / C Minor', accidentals: '3 ♭ (B♭, E♭, A♭)' },
  { fifths: -4, label: 'A♭ Major / F Minor', accidentals: '4 ♭ (B♭, E♭, A♭, D♭)' }
]

const CLEF_OPTIONS = computed<Array<{ id: 'treble' | 'bass' | 'alto' | 'tenor'; label: string; desc: string }>>(() => [
  { id: 'treble', label: t('creationModal.clefs.treble'), desc: t('creationModal.clefs.trebleDesc') },
  { id: 'bass', label: t('creationModal.clefs.bass'), desc: t('creationModal.clefs.bassDesc') },
  { id: 'alto', label: t('creationModal.clefs.alto'), desc: t('creationModal.clefs.altoDesc') },
  { id: 'tenor', label: t('creationModal.clefs.tenor'), desc: t('creationModal.clefs.tenorDesc') }
])

const MEASURE_PRESETS = [4, 8, 16, 32]

function escapeXml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

function generateBlankMusicXml(opts: BlankScoreOptions): string {
  const safeTitle = escapeXml(opts.title.trim() || 'Untitled Composition')
  const safeComposer = escapeXml(opts.composer.trim() || 'Anonymous')
  const divisions = 4
  const durationPerQuarter = divisions
  const measureDuration = Math.round(opts.beats * (durationPerQuarter * 4 / opts.beatType))

  const clefDef = {
    treble: { sign: 'G', line: 2 },
    bass: { sign: 'F', line: 4 },
    alto: { sign: 'C', line: 3 },
    tenor: { sign: 'C', line: 4 }
  }[opts.clef] || { sign: 'G', line: 2 }

  let xml = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
  <work>
    <work-title>${safeTitle}</work-title>
  </work>
  <identification>
    <creator type="composer">${safeComposer}</creator>
  </identification>
  <part-list>
    <score-part id="P1">
      <part-name>Piano</part-name>
      <part-abbreviation>Pno</part-abbreviation>
      <score-instrument id="P1-I1">
        <instrument-name>Piano</instrument-name>
      </score-instrument>
      <midi-instrument id="P1-I1">
        <midi-program>1</midi-program>
      </midi-instrument>
    </score-part>
  </part-list>
  <part id="P1">
`

  for (let m = 1; m <= opts.measureCount; m++) {
    xml += `    <measure number="${m}">\n`
    if (m === 1) {
      xml += `      <attributes>
        <divisions>${divisions}</divisions>
        <key>
          <fifths>${opts.fifths}</fifths>
        </key>
        <time>
          <beats>${opts.beats}</beats>
          <beat-type>${opts.beatType}</beat-type>
        </time>
        <clef>
          <sign>${clefDef.sign}</sign>
          <line>${clefDef.line}</line>
        </clef>
      </attributes>
      <direction placement="above">
        <direction-type>
          <words font-weight="bold">${opts.tempo} BPM</words>
        </direction-type>
        <sound tempo="${opts.tempo}"/>
      </direction>\n`
    }

    xml += `      <note>
        <rest/>
        <duration>${measureDuration}</duration>
      </note>
    </measure>\n`
  }

  xml += `  </part>
</score-partwise>`
  return xml
}

const handleCreate = () => {
  let beats = customBeats.value
  let beatType = customBeatType.value
  const preset = TIME_PRESETS.find(p => p.id === selectedTimePreset.value)
  if (preset && preset.id !== 'custom') {
    beats = preset.beats
    beatType = preset.beatType
  }

  const generatedXml = generateBlankMusicXml({
    title: title.value,
    composer: composer.value,
    clef: selectedClef.value,
    fifths: selectedFifths.value,
    beats,
    beatType,
    tempo: tempo.value,
    measureCount: measureCount.value
  })

  emit('create', {
    title: title.value.trim() || 'Untitled Composition',
    composer: composer.value.trim() || 'Anonymous',
    musicXml: generatedXml
  })
}
</script>

<template>
  <div v-if="isOpen" class="modal-backdrop" @click="emit('close')">
    <div class="modal-card" @click.stop role="dialog" aria-modal="true" aria-labelledby="creation-modal-title">
      <!-- Header -->
      <div class="modal-header">
        <div class="header-title-group">
          <div class="header-icon-wrapper">
            <FilePlus class="header-icon" :size="22" />
          </div>
          <div>
            <h3 id="creation-modal-title" class="modal-title">{{ $t('creationModal.title') }}</h3>
            <p class="modal-subtitle">{{ $t('creationModal.subtitle') }}</p>
          </div>
        </div>
        <button class="close-btn" @click="emit('close')" :aria-label="$t('common.close')">
          <X :size="18" />
        </button>
      </div>

      <!-- Body Form -->
      <div class="modal-body">
        <!-- Title & Composer -->
        <div class="form-row two-col">
          <div class="form-group">
            <label class="form-label">{{ $t('creationModal.scoreTitle') }}</label>
            <input
              type="text"
              v-model="title"
              :placeholder="$t('creationModal.scoreTitlePlaceholder')"
              class="form-input"
              autofocus
            />
          </div>
          <div class="form-group">
            <label class="form-label">{{ $t('creationModal.composer') }}</label>
            <input
              type="text"
              v-model="composer"
              :placeholder="$t('creationModal.composerPlaceholder')"
              class="form-input"
            />
          </div>
        </div>

        <!-- Clef Selection -->
        <div class="form-group">
          <label class="form-label">{{ $t('creationModal.startingClef') }}</label>
          <div class="options-grid clef-grid">
            <button
              v-for="c in CLEF_OPTIONS"
              :key="c.id"
              type="button"
              class="option-card"
              :class="{ active: selectedClef === c.id }"
              @click="selectedClef = c.id"
            >
              <span class="option-title">{{ c.label }}</span>
              <span class="option-desc">{{ c.desc }}</span>
            </button>
          </div>
        </div>

        <!-- Time Signature -->
        <div class="form-group">
          <div class="label-with-icon">
            <Clock :size="14" />
            <label class="form-label">{{ $t('creationModal.timeSignature') }}</label>
          </div>
          <div class="options-grid time-grid">
            <button
              v-for="t in TIME_PRESETS"
              :key="t.id"
              type="button"
              class="option-card time-card"
              :class="{ active: selectedTimePreset === t.id }"
              @click="selectedTimePreset = t.id"
            >
              <span class="time-large">{{ t.label }}</span>
              <span class="option-desc">{{ t.desc }}</span>
            </button>
          </div>

          <div v-if="selectedTimePreset === 'custom'" class="custom-time-row">
            <div class="time-input-group">
              <label>{{ $t('creationModal.beatsTop') }}</label>
              <input type="number" min="1" max="32" v-model.number="customBeats" class="number-input" />
            </div>
            <div class="time-input-group">
              <label>{{ $t('creationModal.beatTypeBottom') }}</label>
              <select v-model.number="customBeatType" class="select-input">
                <option :value="2">{{ $t('creationModal.beatHalf') }}</option>
                <option :value="4">{{ $t('creationModal.beatQuarter') }}</option>
                <option :value="8">{{ $t('creationModal.beatEighth') }}</option>
                <option :value="16">{{ $t('creationModal.beatSixteenth') }}</option>
              </select>
            </div>
          </div>
        </div>

        <!-- Key Signature -->
        <div class="form-group">
          <div class="label-with-icon">
            <Compass :size="14" />
            <label class="form-label">{{ $t('creationModal.keySignature') }}</label>
          </div>
          <select v-model.number="selectedFifths" class="select-input full-width">
            <option v-for="k in KEY_OPTIONS" :key="k.fifths" :value="k.fifths">
              {{ k.label }} — {{ k.accidentals }}
            </option>
          </select>
        </div>

        <!-- Measures & Tempo -->
        <div class="form-row two-col">
          <div class="form-group">
            <label class="form-label">{{ $t('creationModal.measuresLabel') }}</label>
            <div class="preset-pill-row">
              <button
                v-for="m in MEASURE_PRESETS"
                :key="m"
                type="button"
                class="pill-btn"
                :class="{ active: measureCount === m }"
                @click="measureCount = m"
              >
                {{ m }}
              </button>
              <input
                type="number"
                min="1"
                max="128"
                v-model.number="measureCount"
                class="pill-input"
                title="Custom measure count"
              />
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">{{ $t('creationModal.tempoLabel') }}</label>
            <div class="tempo-row">
              <input
                type="range"
                min="40"
                max="240"
                step="4"
                v-model.number="tempo"
                class="tempo-slider"
              />
              <span class="tempo-display">{{ tempo }} BPM</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="modal-footer">
        <button type="button" class="btn cancel-btn" @click="emit('close')">
          {{ $t('creationModal.cancel') }}
        </button>
        <button type="button" class="btn create-btn" @click="handleCreate">
          <Sparkles :size="16" />
          <span>{{ $t('creationModal.createScoreBtn') }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.72);
  backdrop-filter: blur(5px);
  z-index: 1050;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal-card {
  background: var(--bg-card, #131926);
  border: 1px solid var(--border, #26334d);
  border-radius: 16px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.6);
  width: 100%;
  max-width: 680px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: var(--text-main, #f1f5f9);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid var(--border, #26334d);
  background: var(--bg-subtle, #0f1420);
}

.header-title-group {
  display: flex;
  align-items: center;
  gap: 14px;
}

.header-icon-wrapper {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(168, 85, 247, 0.2));
  border: 1px solid rgba(139, 92, 246, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #a78bfa;
}

.modal-title {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
  color: #fff;
}

.modal-subtitle {
  margin: 3px 0 0 0;
  font-size: 0.82rem;
  color: #94a3b8;
}

.close-btn {
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 8px;
  border-radius: 8px;
  transition: all 0.2s ease;
}

.close-btn:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.08);
}

.modal-body {
  padding: 24px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-row.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.label-with-icon {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #a78bfa;
}

.form-label {
  font-size: 0.82rem;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #cbd5e1;
}

.form-input, .select-input {
  background: rgba(15, 20, 32, 0.8);
  border: 1px solid var(--border, #26334d);
  color: #fff;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 0.95rem;
  outline: none;
  transition: border-color 0.2s;
}

.form-input:focus, .select-input:focus {
  border-color: #8b5cf6;
}

.options-grid {
  display: grid;
  gap: 10px;
}

.clef-grid {
  grid-template-columns: repeat(2, 1fr);
}

.time-grid {
  grid-template-columns: repeat(5, 1fr);
}

.option-card {
  background: rgba(15, 20, 32, 0.6);
  border: 1px solid var(--border, #26334d);
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
  color: inherit;
}

.option-card:hover {
  background: rgba(30, 41, 59, 0.7);
  border-color: rgba(139, 92, 246, 0.4);
}

.option-card.active {
  background: rgba(99, 102, 241, 0.15);
  border-color: #8b5cf6;
  box-shadow: 0 0 12px rgba(139, 92, 246, 0.2);
}

.time-card {
  align-items: center;
  text-align: center;
  padding: 8px;
}

.time-large {
  font-size: 1.1rem;
  font-weight: 700;
  color: #fff;
}

.option-title {
  font-weight: 600;
  font-size: 0.9rem;
  color: #fff;
}

.option-desc {
  font-size: 0.72rem;
  color: #94a3b8;
  margin-top: 2px;
}

.custom-time-row {
  display: flex;
  gap: 16px;
  margin-top: 6px;
  padding: 10px 14px;
  background: rgba(15, 20, 32, 0.5);
  border-radius: 8px;
}

.time-input-group {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
  color: #cbd5e1;
}

.number-input {
  width: 70px;
  background: #0f1420;
  border: 1px solid #26334d;
  color: #fff;
  border-radius: 6px;
  padding: 6px 10px;
}

.preset-pill-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.pill-btn {
  flex: 1;
  background: rgba(15, 20, 32, 0.7);
  border: 1px solid #26334d;
  color: #cbd5e1;
  border-radius: 8px;
  padding: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.pill-btn:hover {
  border-color: #8b5cf6;
}

.pill-btn.active {
  background: #8b5cf6;
  color: #fff;
  border-color: #8b5cf6;
}

.pill-input {
  width: 70px;
  background: rgba(15, 20, 32, 0.7);
  border: 1px solid #26334d;
  color: #fff;
  border-radius: 8px;
  padding: 8px;
  text-align: center;
}

.tempo-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.tempo-slider {
  flex: 1;
  accent-color: #8b5cf6;
}

.tempo-display {
  font-weight: 600;
  font-size: 0.9rem;
  min-width: 75px;
  color: #a78bfa;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 18px 24px;
  border-top: 1px solid var(--border, #26334d);
  background: var(--bg-subtle, #0f1420);
}

.btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: 10px;
  font-size: 0.92rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.cancel-btn {
  background: transparent;
  border: 1px solid #26334d;
  color: #94a3b8;
}

.cancel-btn:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.05);
}

.create-btn {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border: none;
  color: #fff;
  box-shadow: 0 4px 15px rgba(99, 102, 241, 0.35);
}

.create-btn:hover {
  background: linear-gradient(135deg, #4f46e5, #7c3aed);
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.5);
  transform: translateY(-1px);
}

@media (max-width: 768px) {
  .modal-backdrop {
    align-items: flex-end;
    padding: 0;
  }

  .modal-card {
    max-width: 100%;
    max-height: 92vh;
    border-radius: 20px 20px 0 0;
    padding-bottom: var(--sab);
  }

  .modal-header {
    padding: 16px 18px;
  }

  .modal-body {
    padding: 16px 18px;
    gap: 16px;
  }

  .form-row.two-col {
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .template-grid {
    grid-template-columns: 1fr;
  }

  .modal-footer {
    padding: 14px 18px;
    padding-bottom: calc(14px + var(--sab));
  }

  .btn {
    flex: 1;
    justify-content: center;
  }
}
</style>
