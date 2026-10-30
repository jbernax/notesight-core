<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick, computed } from 'vue'
import type { OpenSheetMusicDisplay } from 'opensheetmusicdisplay'
import { ScorePlaybackController } from '../../audio/scorePlayer'
import { preferences } from '../../composables/useSettings'
import { useScoreMutation, type ParsedNote, type MeasureAttributes } from '../../composables/useScoreMutation'
import { useScoreInteraction } from '../../composables/useScoreInteraction'
import StudioHeader from './StudioHeader.vue'
import StudioRibbon from './StudioRibbon.vue'
import StudioPalette from './StudioPalette.vue'
import StudioStatusBar from './StudioStatusBar.vue'
import ReviewSplitPane from './ReviewSplitPane.vue'
import StudioMixer from './StudioMixer.vue'
import ScoreShareModal from './ScoreShareModal.vue'
import StudioAnnotations from './StudioAnnotations.vue'
import MobileStudioPalette from '../mobile/MobileStudioPalette.vue'
import { AlertTriangle } from 'lucide-vue-next'
import type { PlaybackStateSnapshot } from '../../audio/scorePlayer'
import { showToast } from '../../composables/useToast'
import { userProfile } from '../../composables/useUserProfile'
import { useCollaboration } from '../../composables/useCollaboration'
import { useScoreAnnotations } from '../../composables/useScoreAnnotations'
import { useNativePlatform } from '../../composables/useNativePlatform'
import { useWakeLock } from '../../composables/useWakeLock'
import { usePedalNavigation } from '../../composables/usePedalNavigation'
import { sanitizeMusicXmlLyrics } from '../../utils/musicxmlLyricsSanitizer'
import { midiService, type MidiNoteEvent } from '../../audio/midiService'
import { apiFetch } from '../../services/apiClient'

const props = defineProps<{
  musicXml: string
  jobId?: string
  hasOriginalSource?: boolean
  scoreTitle?: string
  shareToken?: string
}>()

const emit = defineEmits<{
  (e: 'update:musicXml', xml: string): void
  (e: 'saved', jobId: string): void
  (e: 'exitStudio'): void
}>()

const studioContainerRef = ref<HTMLDivElement | null>(null)
const sheetContainerRef = ref<HTMLDivElement | null>(null)
const canvasScrollerRef = ref<HTMLDivElement | null>(null)
const isSaving = ref(false)
const showUnsavedModal = ref(false)
const isSplitReview = ref(false)
const isMixerOpen = ref(false)
const isAnnotationsOpen = ref(false)
const isShareModalOpen = ref(false)
const isFullscreen = ref(false)
const zoomLevel = ref<number>(
  typeof window !== 'undefined' && window.innerWidth <= 768 && (preferences.value.defaultZoom || 100) === 100
    ? 0.82
    : (preferences.value.defaultZoom || 100) / 100
)
const viewMode = ref<'paginated' | 'continuous'>('continuous')
const bpm = ref<number>(preferences.value.defaultBpm || 120)
const isPlaying = ref(false)
const playingNotes = ref<string>('')

const collaboration = useCollaboration(
  () => props.jobId,
  () => props.shareToken || (typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('share_token') || undefined : undefined),
)
const scoreAnnotations = useScoreAnnotations()
const { isMobile } = useNativePlatform()

const scoreMutation = useScoreMutation(props.musicXml)
let osmd: OpenSheetMusicDisplay | null = null
const player = new ScorePlaybackController()
const playbackState = ref<PlaybackStateSnapshot>(player.getSnapshot())
let unsubscribeMeasure: (() => void) | null = null
let unsubscribeState: (() => void) | null = null

const totalMeasures = ref<number>(1)
const currentMeasureAttributes = ref<MeasureAttributes>({
  beats: 4,
  beatType: 4,
  fifths: 0,
  clefSign: 'G',
  clefLine: 2
})
const currentNotes = ref<ParsedNote[]>([])
const selectedNote = ref<ParsedNote | null>(null)
const isMidiConnected = ref(false)
const lastMidiNote = ref<string | null>(null)
let unsubscribeMidi: (() => void) | null = null
let unsubscribeMidiState: (() => void) | null = null

const refreshActiveMeasureData = () => {
  totalMeasures.value = scoreMutation.getTotalMeasures()
  currentMeasureAttributes.value = scoreMutation.getMeasureAttributes(
    interaction.currentMeasureNum.value,
    interaction.currentStaffIndex.value
  )
  currentNotes.value = scoreMutation.getNotesInMeasure(
    interaction.currentMeasureNum.value,
    interaction.currentStaffIndex.value
  )
  const targetNote = currentNotes.value.find(
    n => n.onsetIndex === interaction.currentNoteIndex.value && n.headIndex === interaction.currentHeadIndex.value
  ) || currentNotes.value[interaction.currentNoteIndex.value] || null
  selectedNote.value = targetNote
}

const scoreParts = computed(() => {
  try {
    return scoreMutation.getScoreParts()
  } catch {
    return []
  }
})

const activePart = computed(() => {
  const parts = scoreParts.value
  if (!parts.length) return null
  let staffOffset = 0
  for (const p of parts) {
    if (interaction.currentStaffIndex.value < staffOffset + p.staves) {
      return p
    }
    staffOffset += p.staves
  }
  return parts[0] || null
})

const activeStaffVoice = computed(() => {
  const p = activePart.value
  return p ? { tag: p.tag, name: p.name, id: p.id } : null
})

const activeVoiceNumber = computed(() => {
  return selectedNote.value?.voice || 1
})

const hasMultipleVoices = computed(() => {
  const p = activePart.value
  if (!p) return false
  const voices = scoreMutation.getPartVoices(p.id)
  return voices.length > 1
})

const jumpToMeasure = (measureNum: number) => {
  interaction.currentMeasureNum.value = measureNum
  interaction.currentNoteIndex.value = 0
  interaction.currentHeadIndex.value = 0
  refreshActiveMeasureData()
  interaction.highlightSelectedElement()

  if (sheetContainerRef.value) {
    const matching = sheetContainerRef.value.querySelectorAll(`.vf-measure[id="${measureNum}"]`)
    const targetEl = matching[interaction.currentStaffIndex.value] || matching[0]
    if (targetEl) {
      targetEl.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' })
    }
  }
}

const { requestWakeLock } = useWakeLock()
usePedalNavigation(
  () => jumpToMeasure(Math.min(totalMeasures.value, interaction.currentMeasureNum.value + 1)),
  () => jumpToMeasure(Math.max(1, interaction.currentMeasureNum.value - 1))
)

const renderScore = async () => {
  if (!sheetContainerRef.value || !scoreMutation.workingXml.value) return

  // Preserve scroll position across renders so note placement does not jump to top
  const savedScrollTop = canvasScrollerRef.value ? canvasScrollerRef.value.scrollTop : 0
  const savedScrollLeft = canvasScrollerRef.value ? canvasScrollerRef.value.scrollLeft : 0

  try {
    let cleanXml = sanitizeMusicXmlLyrics(scoreMutation.workingXml.value.trim())
    if (!cleanXml.startsWith('<?xml')) {
      cleanXml = '<?xml version="1.0" encoding="utf-8"?>\n' + cleanXml
    }

    if (osmd) {
      osmd.clear()
    } else {
      const { OpenSheetMusicDisplay: OSMDClass } = await import('opensheetmusicdisplay')
      osmd = new OSMDClass(sheetContainerRef.value, {
        autoResize: true,
        backend: 'svg',
        drawTitle: true,
        drawSubtitle: true,
        drawComposer: true,
        drawingParameters: 'default',
        pageFormat: viewMode.value === 'paginated' ? 'A4_P' : 'Endless',
        followCursor: false,
        autoBeam: true,
        autoBeamOptions: {
          beam_rests: false,
          beam_middle_rests_only: false,
          maintain_stem_directions: false
        }
      })

      // Anti-collision engraving rules for lyrics & measure spacing
      osmd.EngravingRules.MaximumLyricsElongationFactor = 4.5
      osmd.EngravingRules.HorizontalBetweenLyricsDistance = 0.5
      osmd.EngravingRules.BetweenSyllableMinimumDistance = 0.8
      osmd.EngravingRules.LyricsXPaddingFactorForLongLyrics = 1.3
      osmd.EngravingRules.LyricsUseXPaddingForLongLyrics = true
      osmd.EngravingRules.LyricsXPaddingForLastNoteInMeasure = true
      osmd.EngravingRules.LyricOverlapAllowedIntoNextMeasure = 1.0
      osmd.EngravingRules.VoiceSpacingMultiplierVexflow = 0.95
    }

    await osmd.load(cleanXml)
    osmd.zoom = zoomLevel.value
    osmd.render()

    refreshActiveMeasureData()
    await nextTick()
    interaction.highlightSelectedElement()

    // Restore scroll position
    if (canvasScrollerRef.value) {
      canvasScrollerRef.value.scrollTop = savedScrollTop
      canvasScrollerRef.value.scrollLeft = savedScrollLeft
    }

    // Reload playback
    try {
      player.loadScore(osmd)
    } catch {}
  } catch (err) {
    console.error('Failed to render in Notation Studio:', err)
  }
}

const applyMutation = async (newXml: string | null, shouldAudition: boolean = true) => {
  if (!newXml) return
  const lockedBy = collaboration.lockedMeasures.value.get(interaction.currentMeasureNum.value)
  if (lockedBy) {
    showToast({
      title: 'Measure Locked',
      message: `Measure ${interaction.currentMeasureNum.value} is currently locked by ${lockedBy}.`,
      type: 'warning',
    })
    return
  }
  emit('update:musicXml', newXml)
  if (props.jobId && !props.jobId.startsWith('sample-')) {
    collaboration.broadcastMutation(newXml, `Edited measure ${interaction.currentMeasureNum.value}`)
  }
  await renderScore()
  if (shouldAudition && selectedNote.value) {
    interaction.playNoteAudition(selectedNote.value)
  }
}

const dragPitchInfo = ref<{ visible: boolean; x: number; y: number; text: string } | null>(null)

// Interaction callbacks
const interaction = useScoreInteraction(sheetContainerRef, {
  onSelectNote: (measureNum, noteIndex, staffIndex = 0, headIndex = 0) => {
    interaction.currentMeasureNum.value = measureNum
    interaction.currentStaffIndex.value = staffIndex
    interaction.currentNoteIndex.value = noteIndex
    interaction.currentHeadIndex.value = headIndex
    refreshActiveMeasureData()
    if (selectedNote.value) {
      interaction.playNoteAudition(selectedNote.value)
    }
  },
  onTranspose: (semitones) => {
    const xml = scoreMutation.transposeNote(
      interaction.currentMeasureNum.value,
      interaction.currentNoteIndex.value,
      semitones,
      interaction.currentStaffIndex.value,
      interaction.currentHeadIndex.value
    )
    applyMutation(xml, true)
  },
  onSetNoteType: (type) => {
    handleSetNoteType(type)
  },
  onToggleDot: () => handleToggleDot(),
  onToggleRest: () => handleToggleRest(),
  onToggleTie: () => handleToggleTie(),
  onUndo: () => handleUndo(),
  onRedo: () => handleRedo(),
  onTogglePlay: () => {
    togglePlay()
  },
  getMeasureNotesCount: (measureNum, staffIndex = 0) => {
    return scoreMutation.getNotesInMeasure(measureNum, staffIndex).length
  },
  getTotalMeasures: () => {
    return scoreMutation.getTotalMeasures()
  },
  onDropTool: (measureNum, noteIndex, tool, staffIndex = interaction.currentStaffIndex.value) => {
    const res = scoreMutation.applyDroppedTool(
      measureNum,
      noteIndex,
      tool,
      staffIndex,
      interaction.currentHeadIndex.value
    )
    if (res) {
      interaction.currentMeasureNum.value = res.nextMeasureNum
      interaction.currentStaffIndex.value = staffIndex
      interaction.currentNoteIndex.value = res.nextNoteIndex
      applyMutation(res.xml, true)
    }
  },
  onPitchDragProgress: (_measureNum, noteIndex, diatonicSteps, clientX, clientY, _staffIndex, headIndex = 0) => {
    const note = currentNotes.value.find(
      n => n.onsetIndex === noteIndex && n.headIndex === headIndex
    ) || currentNotes.value[noteIndex]
    if (!note || note.isRest) return
    const stepNames = ['C', 'D', 'E', 'F', 'G', 'A', 'B']
    const stepIndex = stepNames.indexOf(note.step)
    const totalDiatonic = note.octave * 7 + (stepIndex !== -1 ? stepIndex : 0) + diatonicSteps
    const newOctave = Math.max(1, Math.min(8, Math.floor(totalDiatonic / 7)))
    const newStepIndex = ((totalDiatonic % 7) + 7) % 7
    const newStep = stepNames[newStepIndex]

    const accidentalSymbol = note.alter === 1 ? '♯' : note.alter === -1 ? '♭' : note.alter === 2 ? '𝄪' : note.alter === -2 ? '𝄫' : ''
    dragPitchInfo.value = {
      visible: true,
      x: clientX,
      y: clientY,
      text: `${newStep}${accidentalSymbol}${newOctave}`
    }
  },
  onPitchDragEnd: (measureNum, noteIndex, diatonicSteps, staffIndex = interaction.currentStaffIndex.value, headIndex = interaction.currentHeadIndex.value) => {
    dragPitchInfo.value = null
    const xml = scoreMutation.shiftNoteDiatonic(
      measureNum,
      noteIndex,
      diatonicSteps,
      staffIndex,
      headIndex
    )
    applyMutation(xml, true)
  }
})

const activeMeasureLockedBy = computed(() => {
  return collaboration.lockedMeasures.value.get(interaction.currentMeasureNum.value) || null
})

const handleCreateAnnotation = async (payload: {
  measure_number: number
  annotation_type: 'comment' | 'fingering' | 'rehearsal' | 'technique'
  content: string
  color: string
}) => {
  if (!props.jobId) return
  const created = await scoreAnnotations.addAnnotation(props.jobId, payload)
  if (created) {
    showToast({
      title: 'Annotation Added',
      message: `Added note to Measure ${payload.measure_number}`,
      type: 'success',
    })
  }
}

const handleUpdateAnnotation = async (annotationId: string, update: { is_resolved?: boolean; content?: string }) => {
  if (!props.jobId) return
  await scoreAnnotations.updateAnnotation(props.jobId, annotationId, update)
}

const handleDeleteAnnotation = async (annotationId: string) => {
  if (!props.jobId) return
  await scoreAnnotations.deleteAnnotation(props.jobId, annotationId)
}

const handleUndo = () => {
  const xml = scoreMutation.undo()
  if (xml) applyMutation(xml, false)
}

const handleRedo = () => {
  const xml = scoreMutation.redo()
  if (xml) applyMutation(xml, false)
}

const handleToggleDot = () => {
  const xml = scoreMutation.toggleDot(
    interaction.currentMeasureNum.value,
    interaction.currentNoteIndex.value,
    interaction.currentStaffIndex.value,
    interaction.currentHeadIndex.value
  )
  applyMutation(xml, true)
}

const handleToggleRest = () => {
  const xml = scoreMutation.toggleRest(
    interaction.currentMeasureNum.value,
    interaction.currentNoteIndex.value,
    interaction.currentStaffIndex.value,
    interaction.currentHeadIndex.value
  )
  applyMutation(xml, true)
}

const handleToggleTie = () => {
  const xml = scoreMutation.toggleTie(
    interaction.currentMeasureNum.value,
    interaction.currentNoteIndex.value,
    interaction.currentStaffIndex.value,
    interaction.currentHeadIndex.value
  )
  applyMutation(xml, true)
}

const handleFillLine = () => {
  const xml = scoreMutation.fillLine()
  if (xml) applyMutation(xml, false)
}

const handleFillPage = () => {
  const xml = scoreMutation.fillPage()
  if (xml) applyMutation(xml, false)
}

// Playback handling
const togglePlay = () => {
  if (!osmd) return
  if (isPlaying.value) {
    player.pause()
    isPlaying.value = false
  } else {
    player.play()
    isPlaying.value = true
  }
}

const stopPlay = () => {
  player.stop()
  isPlaying.value = false
}

const updateBpm = (newBpm: number) => {
  bpm.value = Math.max(30, Math.min(300, newBpm))
  player.setBpm(bpm.value)
}

const handleSetNoteType = (type: string) => {
  const isDotted = selectedNote.value?.isDotted || false
  const isRest = selectedNote.value?.isRest || false

  if (isRest) {
    const defaultStep = 'C'
    const defaultOct = interaction.currentStaffIndex.value === 1 ? 3 : 4
    const res = scoreMutation.splitRestAndInsertNote(
      interaction.currentMeasureNum.value,
      interaction.currentNoteIndex.value,
      type,
      isDotted,
      defaultStep,
      defaultOct,
      0,
      interaction.currentStaffIndex.value
    )
    if (res) {
      interaction.currentMeasureNum.value = res.nextMeasureNum
      interaction.currentNoteIndex.value = res.nextNoteIndex
      applyMutation(res.xml, true)
      return
    }
  }

  const xml = scoreMutation.setNoteType(
    interaction.currentMeasureNum.value,
    interaction.currentNoteIndex.value,
    type,
    isDotted,
    isRest,
    interaction.currentStaffIndex.value,
    interaction.currentHeadIndex.value
  )
  applyMutation(xml, true)
}

const handleSetRestType = (type: string) => {
  const isDotted = selectedNote.value?.isDotted || false
  const xml = scoreMutation.setNoteType(
    interaction.currentMeasureNum.value,
    interaction.currentNoteIndex.value,
    type,
    isDotted,
    true,
    interaction.currentStaffIndex.value,
    interaction.currentHeadIndex.value
  )
  applyMutation(xml, true)
}

const handleToggleAccidental = (alter: number) => {
  const xml = scoreMutation.toggleAccidental(
    interaction.currentMeasureNum.value,
    interaction.currentNoteIndex.value,
    alter,
    interaction.currentStaffIndex.value,
    interaction.currentHeadIndex.value
  )
  applyMutation(xml, true)
}

const handleTranspose = (semitones: number) => {
  const xml = scoreMutation.transposeNote(
    interaction.currentMeasureNum.value,
    interaction.currentNoteIndex.value,
    semitones,
    interaction.currentStaffIndex.value,
    interaction.currentHeadIndex.value
  )
  applyMutation(xml, true)
}

const handleSetNotePitch = (pitch: { step: string; octave: number; alter: number }) => {
  const xml = scoreMutation.setNotePitch(
    interaction.currentMeasureNum.value,
    interaction.currentNoteIndex.value,
    pitch.step,
    pitch.octave,
    pitch.alter,
    interaction.currentStaffIndex.value,
    interaction.currentHeadIndex.value
  )
  applyMutation(xml, true)
}

const handleAddMeasure = () => {
  const xml = scoreMutation.addMeasure(interaction.currentMeasureNum.value)
  if (xml) {
    interaction.currentMeasureNum.value += 1
    interaction.currentNoteIndex.value = 0
    interaction.currentHeadIndex.value = 0
    applyMutation(xml, false)
  }
}

const deleteTarget = ref<{
  type: 'part' | 'voice'
  partId: string
  name: string
  voiceNumber?: number
} | null>(null)

const confirmDeleteTarget = () => {
  if (!deleteTarget.value) return
  const target = deleteTarget.value
  deleteTarget.value = null

  if (target.type === 'part') {
    const xml = scoreMutation.deletePart(target.partId)
    if (xml) {
      interaction.currentStaffIndex.value = 0
      interaction.currentNoteIndex.value = 0
      interaction.currentHeadIndex.value = 0
      applyMutation(xml, false)
      showToast({
        title: 'Line Deleted',
        message: `Line "${target.name}" deleted. Press Ctrl+Z to undo.`,
        type: 'info'
      })
    } else {
      showToast({
        title: 'Cannot Delete Line',
        message: 'The score must retain at least one musical line.',
        type: 'error'
      })
    }
  } else if (target.type === 'voice' && target.voiceNumber) {
    const xml = scoreMutation.deleteVoice(target.partId, target.voiceNumber)
    if (xml) {
      interaction.currentNoteIndex.value = 0
      interaction.currentHeadIndex.value = 0
      applyMutation(xml, false)
      showToast({
        title: 'Voice Deleted',
        message: `Voice ${target.voiceNumber} deleted from "${target.name}". Press Ctrl+Z to undo.`,
        type: 'info'
      })
    } else {
      showToast({
        title: 'Delete Voice Failed',
        message: 'No notes found for this voice to delete.',
        type: 'warning'
      })
    }
  }
}

const handleDeletePart = (partId: string) => {
  const p = scoreParts.value.find(part => part.id === partId) || activePart.value
  const name = p ? p.name : 'Selected Line'
  deleteTarget.value = {
    type: 'part',
    partId,
    name
  }
}

const handleDeleteVoice = (payload: { partId: string; voiceNumber: number }) => {
  const p = scoreParts.value.find(part => part.id === payload.partId) || activePart.value
  const name = p ? p.name : 'Selected Line'
  deleteTarget.value = {
    type: 'voice',
    partId: payload.partId,
    voiceNumber: payload.voiceNumber,
    name
  }
}

const handleDeleteTrack = (track: { partId: string; name: string }) => {
  deleteTarget.value = {
    type: 'part',
    partId: track.partId,
    name: track.name
  }
}

const handleDeleteMeasure = () => {
  const xml = scoreMutation.deleteMeasure(interaction.currentMeasureNum.value)
  if (xml) {
    interaction.currentMeasureNum.value = Math.max(1, interaction.currentMeasureNum.value - 1)
    interaction.currentNoteIndex.value = 0
    interaction.currentHeadIndex.value = 0
    applyMutation(xml, false)
  }
}

const handleSetTimeSignature = (beats: number, beatType: number) => {
  const xml = scoreMutation.setTimeSignature(interaction.currentMeasureNum.value, beats, beatType)
  applyMutation(xml, false)
}

const handleSetKeySignature = (fifths: number) => {
  const xml = scoreMutation.setKeySignature(interaction.currentMeasureNum.value, fifths)
  applyMutation(xml, false)
}

const handleSetClef = (sign: string, line: number) => {
  const xml = scoreMutation.setClef(
    interaction.currentMeasureNum.value,
    sign,
    line,
    interaction.currentStaffIndex.value
  )
  applyMutation(xml, false)
}

const handleSetLyrics = (lyrics: string) => {
  const res = scoreMutation.setNoteLyrics(
    interaction.currentMeasureNum.value,
    interaction.currentNoteIndex.value,
    lyrics,
    interaction.currentStaffIndex.value,
    interaction.currentHeadIndex.value
  )
  if (res) {
    interaction.currentMeasureNum.value = res.nextMeasureNum
    interaction.currentNoteIndex.value = res.nextNoteIndex
    applyMutation(res.xml, false)
  }
}

const handleSetDynamics = (dynamic: string) => {
  const res = scoreMutation.setNoteDynamics(
    interaction.currentMeasureNum.value,
    interaction.currentNoteIndex.value,
    dynamic,
    interaction.currentStaffIndex.value,
    interaction.currentHeadIndex.value
  )
  if (res) {
    interaction.currentMeasureNum.value = res.nextMeasureNum
    interaction.currentNoteIndex.value = res.nextNoteIndex
    applyMutation(res.xml, true)
  }
}

// Zoom & View
const setZoom = (factor: number) => {
  zoomLevel.value = Math.max(0.5, Math.min(2.0, Math.round(factor * 10) / 10))
  if (osmd) {
    osmd.zoom = zoomLevel.value
    osmd.render()
    interaction.highlightSelectedElement()
  }
}

const toggleViewMode = () => {
  viewMode.value = viewMode.value === 'paginated' ? 'continuous' : 'paginated'
  if (osmd) {
    osmd.setOptions({
      pageFormat: viewMode.value === 'paginated' ? 'A4_P' : 'Endless',
      followCursor: false
    })
    osmd.render()
    interaction.highlightSelectedElement()
  }
}

const toggleFullscreen = async () => {
  if (!studioContainerRef.value) return
  if (!document.fullscreenElement) {
    await studioContainerRef.value.requestFullscreen()
    isFullscreen.value = true
  } else {
    await document.exitFullscreen()
    isFullscreen.value = false
  }
}

// Save Score to Backend
const saveScore = async (): Promise<boolean> => {
  if (!props.jobId || props.jobId.startsWith('sample-')) {
    scoreMutation.markSaved()
    showToast({
      title: 'Sample Score',
      message: 'Modifications are active in your browser session.',
      type: 'info',
    })
    return true
  }

  isSaving.value = true

  try {
    const res = await apiFetch(`/api/jobs/${props.jobId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ musicxml: scoreMutation.workingXml.value })
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Save failed')
    }

    scoreMutation.markSaved()
    emit('saved', props.jobId)

    if (userProfile.value?.allow_omr_telemetry) {
      showToast({
        title: 'Score Saved',
        message: 'Changes saved • Ground-truth training triplet contributed to OMR accuracy.',
        type: 'success',
        duration: 3500
      })
    } else {
      showToast({
        title: 'Score Saved',
        message: 'Your score modifications were saved successfully.',
        type: 'success',
        duration: 2500
      })
    }
    return true
  } catch (err: any) {
    showToast({
      title: 'Save Failed',
      message: err.message || 'Could not save score modifications.',
      type: 'error'
    })
    return false
  } finally {
    isSaving.value = false
  }
}

const handleExitStudioRequest = () => {
  if (scoreMutation.isDirty.value) {
    showUnsavedModal.value = true
  } else {
    emit('exitStudio')
  }
}

const handleConfirmSaveAndExit = async () => {
  const success = await saveScore()
  if (success) {
    showUnsavedModal.value = false
    emit('exitStudio')
  }
}

const handleDiscardAndExit = () => {
  scoreMutation.resetToSaved()
  showUnsavedModal.value = false
  emit('exitStudio')
}

const handleCancelExit = () => {
  showUnsavedModal.value = false
}

const handleBeforeUnload = (e: BeforeUnloadEvent) => {
  if (scoreMutation.isDirty.value) {
    e.preventDefault()
    e.returnValue = ''
  }
}

watch(() => props.musicXml, (newXml) => {
  if (newXml && newXml !== scoreMutation.workingXml.value) {
    scoreMutation.workingXml.value = newXml
    scoreMutation.markSaved(newXml)
    renderScore()
  }
})

onMounted(() => {
  window.addEventListener('beforeunload', handleBeforeUnload)
  renderScore()
  player.setBpm(bpm.value)
  requestWakeLock()
  player.setScoreMetadata(props.scoreTitle || 'NoteSight Studio')

  if (props.jobId && !props.jobId.startsWith('sample-')) {
    collaboration.connect()
    scoreAnnotations.fetchAnnotations(props.jobId)

    collaboration.onScoreDelta(async ({ musicxml, author, description }) => {
      scoreMutation.pushState(musicxml)
      emit('update:musicXml', musicxml)
      await renderScore()
      showToast({
        title: 'Remote Collaboration Update',
        message: `${author}: ${description}`,
        type: 'info',
      })
    })
  }

  unsubscribeState = player.onStateChange((state) => {
    playbackState.value = state
    isPlaying.value = state.status === 'playing'
    playingNotes.value = state.status === 'playing' ? state.currentNotesPlaying : ''
  })

  unsubscribeMeasure = player.onMeasureChange((measureNumber) => {
    interaction.currentMeasureNum.value = measureNumber
    interaction.currentNoteIndex.value = 0
    refreshActiveMeasureData()
    interaction.highlightSelectedElement()
  })

  if (midiService.isSupported) {
    midiService.init().then((ok) => {
      isMidiConnected.value = ok && (midiService.getInputs().length > 0 || midiService.getOutputs().length > 0)
    })

    unsubscribeMidiState = midiService.onStateChange(() => {
      const inputs = midiService.getInputs()
      const outputs = midiService.getOutputs()
      isMidiConnected.value = inputs.length > 0 || outputs.length > 0
    })

    unsubscribeMidi = midiService.onNoteOn((event: MidiNoteEvent) => {
      // Guard: Never mutate score or audition notes from MIDI events while playback is running
      if (isPlaying.value || player.getSnapshot().status === 'playing') {
        return
      }

      lastMidiNote.value = event.name
      player.previewNote(event.frequency, 0.4, 'piano', 0.8)

      const measureNum = interaction.currentMeasureNum.value
      const noteIndex = interaction.currentNoteIndex.value
      const staffIndex = interaction.currentStaffIndex.value
      const headIndex = interaction.currentHeadIndex.value

      if (measureNum > 0) {
        const xml = scoreMutation.setNotePitch(
          measureNum,
          noteIndex,
          event.step,
          event.octave,
          event.alter,
          staffIndex,
          headIndex
        )
        if (xml) {
          applyMutation(xml, true)
        }
      }
    })
  }
})

watch(
  () => interaction.currentMeasureNum.value,
  async (newMeasure, oldMeasure) => {
    collaboration.broadcastPresence(newMeasure, interaction.currentStaffIndex.value, 'select')
    if (props.jobId && !props.jobId.startsWith('sample-')) {
      if (oldMeasure && oldMeasure !== newMeasure) {
        collaboration.releaseMeasureLock(oldMeasure)
      }
      if (newMeasure) {
        await collaboration.requestMeasureLock(newMeasure)
      }
    }
  }
)

watch(
  () => collaboration.isConnected.value,
  async (connected) => {
    if (connected && props.jobId && !props.jobId.startsWith('sample-') && interaction.currentMeasureNum.value) {
      await collaboration.requestMeasureLock(interaction.currentMeasureNum.value)
    }
  }
)

onUnmounted(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
  if (props.jobId && !props.jobId.startsWith('sample-') && interaction.currentMeasureNum.value) {
    collaboration.releaseMeasureLock(interaction.currentMeasureNum.value)
  }
  collaboration.disconnect()
  player.destroy()
  interaction.destroy()
  if (unsubscribeMeasure) unsubscribeMeasure()
  if (unsubscribeState) unsubscribeState()
  if (unsubscribeMidi) unsubscribeMidi()
  if (unsubscribeMidiState) unsubscribeMidiState()
})
</script>

<template>
  <div ref="studioContainerRef" class="notation-studio" aria-label="Notation Studio Workbench">
    <!-- Top Studio Header -->
    <StudioHeader
      :can-undo="scoreMutation.canUndo.value"
      :can-redo="scoreMutation.canRedo.value"
      :is-playing="isPlaying"
      :bpm="bpm"
      :zoom-level="zoomLevel"
      :view-mode="viewMode"
      :is-fullscreen="isFullscreen"
      :is-split-review="isSplitReview"
      :is-mixer-open="isMixerOpen"
      :is-annotations-open="isAnnotationsOpen"
      :has-original-source="!!hasOriginalSource"
      :is-saving="isSaving"
      :score-title="scoreTitle"
      :collaborators="collaboration.peerList.value"
      :annotation-count="scoreAnnotations.unresolvedCount.value"
      @undo="handleUndo"
      @redo="handleRedo"
      @toggle-play="togglePlay"
      @stop="stopPlay"
      @update:bpm="updateBpm"
      @zoom-in="setZoom(zoomLevel + 0.1)"
      @zoom-out="setZoom(zoomLevel - 0.1)"
      @reset-zoom="setZoom(1.0)"
      @toggle-view-mode="toggleViewMode"
      @toggle-fullscreen="toggleFullscreen"
      @toggle-split-review="isSplitReview = !isSplitReview"
      @toggle-mixer="isMixerOpen = !isMixerOpen"
      @toggle-annotations="isAnnotationsOpen = !isAnnotationsOpen"
      @open-share="isShareModalOpen = true"
      @save="saveScore"
      @exit-studio="handleExitStudioRequest"
    />

    <!-- Categorized Ribbon (Desktop / Tablet Landscape) -->
    <StudioRibbon
      v-if="!isMobile"
      :selected-note="selectedNote"
      :measure-attributes="currentMeasureAttributes"
      :current-measure-num="interaction.currentMeasureNum.value"
      :total-measures="totalMeasures"
      :active-part-id="activePart?.id"
      :active-part-name="activePart?.name"
      :total-parts="scoreParts.length"
      :active-voice-number="activeVoiceNumber"
      :has-multiple-voices="hasMultipleVoices"
      @transpose="handleTranspose"
      @add-measure="handleAddMeasure"
      @delete-measure="handleDeleteMeasure"
      @fill-line="handleFillLine"
      @fill-page="handleFillPage"
      @delete-part="handleDeletePart"
      @delete-voice="handleDeleteVoice"
      @set-time-signature="handleSetTimeSignature"
      @set-key-signature="handleSetKeySignature"
      @set-clef="handleSetClef"
      @set-lyrics="handleSetLyrics"
      @set-dynamics="handleSetDynamics"
    />

    <!-- Main Workspace with Left Palette & Canvas -->
    <div class="studio-workspace">
      <!-- Left Quick Palette -->
      <StudioPalette
        :selected-note="selectedNote"
        @set-note-type="handleSetNoteType"
        @set-rest-type="handleSetRestType"
        @toggle-dot="handleToggleDot"
        @toggle-rest="handleToggleRest"
        @toggle-tie="handleToggleTie"
        @toggle-accidental="handleToggleAccidental"
      />

      <!-- Optional Split Review Pane (Original Document) -->
      <ReviewSplitPane
        v-if="isSplitReview && hasOriginalSource"
        :job-id="jobId"
        @close="isSplitReview = false"
      />

      <!-- Score Canvas Area -->
      <div
        ref="canvasScrollerRef"
        class="score-canvas-scroller"
        @click="interaction.handleContainerClick"
        @pointerdown="interaction.handleMouseDown"
        @dragover="interaction.handleDragOver"
        @dragleave="interaction.handleDragLeave"
        @drop="interaction.handleDrop"
      >

        <!-- Measure Lock Notice for Collaborators -->
        <div v-if="activeMeasureLockedBy" class="measure-lock-pill" role="status">
          <span>🔒 Measure {{ interaction.currentMeasureNum.value }} is currently being edited by {{ activeMeasureLockedBy }}</span>
        </div>

        <div ref="sheetContainerRef" class="sheet-music-stage"></div>
      </div>

      <!-- Teacher / Student Annotations Drawer -->
      <StudioAnnotations
        :is-open="isAnnotationsOpen"
        :job-id="jobId || ''"
        :current-measure-num="interaction.currentMeasureNum.value"
        :annotations="scoreAnnotations.annotations.value"
        :is-loading="scoreAnnotations.isLoading.value"
        @close="isAnnotationsOpen = false"
        @select-measure="jumpToMeasure"
        @create="handleCreateAnnotation"
        @update="handleUpdateAnnotation"
        @delete="handleDeleteAnnotation"
      />
    </div>

    <!-- Floating Tool Drag Follower Avatar -->
    <div
      v-if="interaction.dragToolState.value.visible"
      class="ns-drag-tool-avatar"
      :style="{ left: `${interaction.dragToolState.value.x + 16}px`, top: `${interaction.dragToolState.value.y + 16}px` }"
    >
      <span class="avatar-sym">{{ interaction.dragToolState.value.symbol }}</span>
      <span class="avatar-label">{{ interaction.dragToolState.value.label }}</span>
    </div>

    <!-- Floating Pitch Drag Badge -->
    <div
      v-if="dragPitchInfo?.visible"
      class="ns-pitch-drag-badge"
      :style="{ left: `${dragPitchInfo.x + 14}px`, top: `${dragPitchInfo.y - 14}px` }"
    >
      {{ dragPitchInfo.text }}
    </div>

    <!-- Collapsible Studio Audio Mixer Drawer -->
    <StudioMixer
      v-if="isMixerOpen"
      :player="player"
      :playback-state="playbackState"
      @close="isMixerOpen = false"
      @delete-track="handleDeleteTrack"
    />

    <!-- Bottom Status Bar -->
    <StudioStatusBar
      :current-measure-num="interaction.currentMeasureNum.value"
      :total-measures="totalMeasures"
      :selected-note="selectedNote"
      :measure-attributes="currentMeasureAttributes"
      :voice-tag="activeStaffVoice?.tag"
      :part-name="activeStaffVoice?.name"
      :is-playing="isPlaying"
      :playing-notes="playingNotes"
      :is-midi-connected="isMidiConnected"
      :last-midi-note="lastMidiNote"
    />

    <!-- Delete Complete Line / Voice Guard Confirmation Modal -->
    <div v-if="deleteTarget" class="unsaved-modal-backdrop" @click="deleteTarget = null">
      <div class="unsaved-modal-card" @click.stop role="dialog" aria-modal="true" aria-labelledby="delete-target-title">
        <div class="unsaved-header">
          <div class="unsaved-icon-wrap" style="background: rgba(239, 68, 68, 0.15); color: #ef4444;">
            <AlertTriangle :size="22" class="warn-icon" />
          </div>
          <div>
            <h3 id="delete-target-title" class="unsaved-title">
              {{ deleteTarget.type === 'part' ? $t('studio.guards.deleteLineTitle') : $t('studio.guards.deleteVoiceTitle', { voice: deleteTarget.voiceNumber ?? '' }) }}
            </h3>
            <p class="unsaved-subtitle">
              {{ deleteTarget.type === 'part' ? `Target: ${deleteTarget.name} (${deleteTarget.partId})` : `Target: Voice ${deleteTarget.voiceNumber} on ${deleteTarget.name}` }}
            </p>
          </div>
        </div>
        <div class="unsaved-body">
          <p v-if="deleteTarget.type === 'part'">
            {{ $t('studio.guards.deleteLinePrompt', { name: deleteTarget.name }) }}
          </p>
          <p v-else>
            {{ $t('studio.guards.deleteVoicePrompt', { voice: deleteTarget.voiceNumber ?? '', name: deleteTarget.name }) }}
          </p>
          <p class="text-muted" style="margin-top: 8px; font-size: 0.8rem; color: #94a3b8;">
            {{ $t('studio.guards.undoHint') }}
          </p>
        </div>
        <div class="unsaved-actions">
          <button type="button" class="btn-cancel" @click="deleteTarget = null">
            {{ $t('common.cancel') }}
          </button>
          <button type="button" class="btn-discard" style="background: #ef4444; border-color: #ef4444; color: white;" @click="confirmDeleteTarget">
            {{ deleteTarget.type === 'part' ? $t('studio.guards.deleteLineTitle') : $t('studio.guards.deleteVoiceTitle', { voice: deleteTarget.voiceNumber ?? '' }) }}
          </button>
        </div>
      </div>
    </div>

    <!-- Unsaved Changes Guard Confirmation Modal -->
    <div v-if="showUnsavedModal" class="unsaved-modal-backdrop" @click="handleCancelExit">
      <div class="unsaved-modal-card" @click.stop role="dialog" aria-modal="true" aria-labelledby="unsaved-title">
        <div class="unsaved-header">
          <div class="unsaved-icon-wrap">
            <AlertTriangle :size="22" class="warn-icon" />
          </div>
          <div>
            <h3 id="unsaved-title" class="unsaved-title">{{ $t('studio.guards.unsavedTitle') }}</h3>
            <p class="unsaved-subtitle">{{ $t('studio.guards.unsavedSubtitle') }}</p>
          </div>
        </div>
        <div class="unsaved-body">
          <p>{{ $t('studio.guards.unsavedBody') }}</p>
        </div>
        <div class="unsaved-actions">
          <button type="button" class="btn-cancel" @click="handleCancelExit">
            {{ $t('studio.guards.keepEditing') }}
          </button>
          <button type="button" class="btn-discard" @click="handleDiscardAndExit">
            {{ $t('studio.guards.discardChanges') }}
          </button>
          <button type="button" class="btn-save-exit" :disabled="isSaving" @click="handleConfirmSaveAndExit">
            <span v-if="isSaving">{{ $t('studio.header.saving') }}</span>
            <span v-else>{{ $t('studio.guards.saveAndExit') }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Score Share & Embed Modal -->
    <ScoreShareModal
      :is-open="isShareModalOpen"
      :job-id="jobId || ''"
      :score-title="scoreTitle"
      @close="isShareModalOpen = false"
    />

    <!-- Mobile Bottom Studio Palette (Ergonomic Touch Editing on Mobile) -->
    <MobileStudioPalette
      v-if="isMobile"
      :selected-note="selectedNote"
      :can-undo="scoreMutation.canUndo.value"
      :can-redo="scoreMutation.canRedo.value"
      :current-measure-num="interaction.currentMeasureNum.value"
      :total-measures="totalMeasures"
      @set-note-type="handleSetNoteType"
      @set-rest-type="handleSetRestType"
      @toggle-dot="handleToggleDot"
      @toggle-rest="handleToggleRest"
      @toggle-tie="handleToggleTie"
      @toggle-accidental="handleToggleAccidental"
      @transpose="handleTranspose"
      @set-pitch="handleSetNotePitch"
      @add-measure="handleAddMeasure"
      @delete-measure="handleDeleteMeasure"
      @fill-line="handleFillLine"
      @fill-page="handleFillPage"
      @undo="handleUndo"
      @redo="handleRedo"
      @toggle-mixer="isMixerOpen = !isMixerOpen"
      @toggle-annotations="isAnnotationsOpen = !isAnnotationsOpen"
      @set-time-signature="handleSetTimeSignature"
      @set-key-signature="handleSetKeySignature"
      @set-clef="handleSetClef"
      @set-lyrics="handleSetLyrics"
      @set-dynamics="handleSetDynamics"
    />
  </div>
</template>

<style scoped>
.notation-studio {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: calc(100vh - 74px);
  min-height: 580px;
  background: var(--bg-primary, #0c1017);
  border: 1px solid var(--border, #242f48);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.3);
}

.studio-workspace {
  display: flex;
  flex: 1;
  overflow: hidden;
  position: relative;
}

.score-canvas-scroller {
  flex: 1;
  overflow: auto;
  padding: 12px 16px 16px 16px;
  background: var(--bg-canvas, #111622);
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
}

.measure-lock-pill {
  position: sticky;
  top: 10px;
  z-index: 20;
  display: inline-flex;
  align-items: center;
  align-self: center;
  gap: 8px;
  background: rgba(239, 68, 68, 0.9);
  color: #ffffff;
  padding: 6px 14px;
  border-radius: 9999px;
  font-size: 0.82rem;
  font-weight: 600;
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.35);
  margin-bottom: 12px;
  pointer-events: none;
  animation: fadeInDown 0.2s ease-out;
}

@keyframes fadeInDown {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.sheet-music-stage {
  background: var(--score-paper-bg, #ffffff);
  border: 1px solid var(--score-paper-border, transparent);
  padding: 18px 24px;
  border-radius: 6px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.25);
  min-width: 0;
  width: 100%;
  max-width: 960px;
  margin: 0 auto;
  box-sizing: border-box;
}


/* On-Staff Note Selection Outline & Glow */
:deep(.vf-stavenote) {
  cursor: pointer;
  transition: transform 0.1s ease;
}

:deep(.vf-stavenote:hover) path,
:deep(.vf-stavenote:hover) rect {
  fill: #818cf8 !important;
}

:deep(.vf-stavenote.ns-active-note) path,
:deep(.vf-stavenote.ns-active-note) rect {
  fill: #6366f1 !important;
  stroke: #4f46e5 !important;
  stroke-width: 1.5px;
  filter: drop-shadow(0 0 6px rgba(99, 102, 241, 0.9));
}

:deep(.vf-measure) {
  cursor: pointer;
}

:deep(.vf-measure.ns-active-measure) {
  outline: 1.5px dashed rgba(99, 102, 241, 0.5);
  outline-offset: 4px;
  border-radius: 4px;
}


/* Drag & Drop Target Highlight */
:deep(.vf-measure.ns-drop-target) {
  outline: 2.5px dashed #6366f1 !important;
  outline-offset: 6px;
  background-color: rgba(99, 102, 241, 0.08) !important;
  border-radius: 8px;
  transition: all 0.15s ease;
}

/* Drag & Drop On-Staff Slot Ghost Highlight */
:deep(.vf-stavenote.ns-drop-slot-ghost) path,
:deep(.vf-stavenote.ns-drop-slot-ghost) rect {
  fill: #818cf8 !important;
  stroke: #4f46e5 !important;
  stroke-width: 2px !important;
  filter: drop-shadow(0 0 10px rgba(129, 140, 248, 0.95)) !important;
  animation: pulseSlotGhost 0.8s ease-in-out infinite alternate;
}

@keyframes pulseSlotGhost {
  0% { opacity: 0.6; transform: scale(0.96); }
  100% { opacity: 1; transform: scale(1.04); }
}

.ns-drag-tool-avatar {
  position: fixed;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(79, 70, 229, 0.95);
  backdrop-filter: blur(8px);
  color: #ffffff;
  padding: 6px 14px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.25);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  pointer-events: none;
  z-index: 10000;
  font-family: inherit;
  user-select: none;
}

.avatar-sym {
  font-size: 1.4rem;
  line-height: 1;
  font-weight: 700;
}

.avatar-label {
  font-size: 0.82rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.ns-pitch-drag-badge {
  position: fixed;
  background: #6366f1;
  color: #ffffff;
  font-weight: 700;
  font-size: 0.85rem;
  padding: 3px 10px;
  border-radius: 6px;
  pointer-events: none;
  z-index: 9999;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.45);
  transform: translateY(-50%);
}

/* Unsaved Changes Guard Modal */
.unsaved-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(4px);
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  animation: fadeIn 0.15s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.unsaved-modal-card {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #242f48);
  border-radius: 12px;
  width: 100%;
  max-width: 460px;
  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.6);
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.unsaved-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.unsaved-icon-wrap {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  background: rgba(245, 158, 11, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: #fbbf24;
}

.unsaved-title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text-primary, #ffffff);
}

.unsaved-subtitle {
  margin: 2px 0 0 0;
  font-size: 0.8rem;
  color: var(--text-secondary, #94a3b8);
}

.unsaved-body {
  font-size: 0.85rem;
  line-height: 1.5;
  color: var(--text-secondary, #cbd5e1);
}

.unsaved-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}

.btn-cancel {
  padding: 8px 14px;
  border-radius: 6px;
  font-size: 0.82rem;
  font-weight: 500;
  background: transparent;
  border: 1px solid var(--border, #242f48);
  color: var(--text-secondary, #94a3b8);
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-cancel:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary, #ffffff);
}

.btn-discard {
  padding: 8px 14px;
  border-radius: 6px;
  font-size: 0.82rem;
  font-weight: 600;
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.4);
  color: #f87171;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-discard:hover {
  background: rgba(239, 68, 68, 0.25);
  border-color: #ef4444;
  color: #ffffff;
}

.btn-save-exit {
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 0.82rem;
  font-weight: 600;
  background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%);
  border: none;
  color: #ffffff;
  cursor: pointer;
  transition: all 0.15s ease;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.35);
}

.btn-save-exit:hover:not(:disabled) {
  opacity: 0.95;
  transform: translateY(-1px);
}

.btn-save-exit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 1024px) {
  .score-canvas-scroller {
    padding: 10px 12px;
  }
  .sheet-music-stage {
    min-width: 0;
    width: 100%;
    padding: 16px 14px;
  }
}

@media (max-width: 768px) {
  .notation-studio {
    height: 100vh;
    min-height: 100vh;
    border-radius: 0;
    border: none;
  }
  .studio-palette {
    display: none !important;
  }
  .studio-workspace {
    flex-direction: column;
  }
  .score-canvas-scroller {
    padding: 8px 6px calc(136px + max(var(--sab, 0px), 8px)) 6px;
  }
  .sheet-music-stage {
    min-width: 0;
    width: 100%;
    max-width: 100%;
    padding: 12px 6px;
    box-sizing: border-box;
    overflow-x: hidden;
  }
}
</style>
