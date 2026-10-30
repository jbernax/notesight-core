import { ref, onMounted, onUnmounted } from 'vue'
import { WebAudioSynthesizer } from '../audio/synth'
import type { ParsedNote } from './useScoreMutation'

export interface DragToolState {
  visible: boolean
  x: number
  y: number
  type: string
  value?: any
  label: string
  symbol: string
}

export const activeDraggingTool = ref<{
  type: string
  value?: any
  label: string
  symbol: string
} | null>(null)

export function useScoreInteraction(
  containerRef: { value: HTMLElement | null },
  callbacks: {
    onSelectNote: (measureNum: number, noteIndex: number, staffIndex?: number, headIndex?: number) => void
    onTranspose: (semitones: number) => void
    onSetNoteType: (type: string) => void
    onToggleDot: () => void
    onToggleRest: () => void
    onToggleTie?: () => void
    onUndo: () => void
    onRedo: () => void
    onTogglePlay: () => void
    getMeasureNotesCount?: (measureNum: number, staffIndex?: number) => number
    getTotalMeasures?: () => number
    onDropTool?: (measureNum: number, noteIndex: number, tool: { type: string; value?: any }, staffIndex?: number) => void
    onPitchDragProgress?: (measureNum: number, noteIndex: number, diatonicSteps: number, clientX: number, clientY: number, staffIndex?: number, headIndex?: number) => void
    onPitchDragEnd?: (measureNum: number, noteIndex: number, diatonicSteps: number, staffIndex?: number, headIndex?: number) => void
  }
) {
  const currentMeasureNum = ref<number>(1)
  const currentStaffIndex = ref<number>(0)
  const currentNoteIndex = ref<number>(0)
  const currentHeadIndex = ref<number>(0)
  const synth = new WebAudioSynthesizer()

  const dragToolState = ref<DragToolState>({
    visible: false,
    x: 0,
    y: 0,
    type: '',
    label: '',
    symbol: ''
  })

  let isPitchDragging = false
  let dragStartY = 0
  let dragMeasureNum = 1
  let dragStaffIndex = 0
  let dragNoteIndex = 0
  let dragHeadIndex = 0
  let currentPitchShift = 0
  let draggedPitchNoteEl: HTMLElement | null = null

  const getNotesCount = (measureNum: number, staffIndex: number): number => {
    if (callbacks.getMeasureNotesCount) {
      return callbacks.getMeasureNotesCount(measureNum, staffIndex)
    }
    if (containerRef.value) {
      const matching = Array.from(containerRef.value.querySelectorAll(`.vf-measure[id="${measureNum}"]`))
      const mEl = matching[staffIndex] || matching[0] || containerRef.value.querySelectorAll('.vf-measure')[measureNum - 1]
      if (mEl) {
        return mEl.querySelectorAll('.vf-stavenote').length
      }
    }
    return 0
  }

  const getTotalMeasuresCount = (): number => {
    if (callbacks.getTotalMeasures) {
      return callbacks.getTotalMeasures()
    }
    if (containerRef.value) {
      return Math.max(1, containerRef.value.querySelectorAll('.vf-measure').length)
    }
    return 1
  }

  const playNoteAudition = async (note: ParsedNote | null) => {
    if (!note || note.isRest) return
    try {
      await synth.ensureContext()
      const midiMap: Record<string, number> = {
        C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11
      }
      const baseMidi = 12 + (note.octave * 12) + (midiMap[note.step] || 0) + note.alter
      const freq = 440 * Math.pow(2, (baseMidi - 69) / 12)
      synth.playNote(freq, 0.35, 0.8)
    } catch (err) {
      console.warn('Audio audition error:', err)
    }
  }

  const highlightSelectedElement = () => {
    if (!containerRef.value) return

    // Remove previous active highlights
    containerRef.value.querySelectorAll('.ns-active-note').forEach((el) => {
      el.classList.remove('ns-active-note')
    })
    containerRef.value.querySelectorAll('.ns-active-measure').forEach((el) => {
      el.classList.remove('ns-active-measure')
    })

    // Find measure element matching currentMeasureNum and currentStaffIndex
    const matchingMeasures = Array.from(
      containerRef.value.querySelectorAll(`.vf-measure[id="${currentMeasureNum.value}"]`)
    )
    let measureEl: Element | null = null
    if (matchingMeasures.length > 0) {
      measureEl = matchingMeasures[currentStaffIndex.value] || matchingMeasures[0]
    } else {
      const allMeasures = containerRef.value.querySelectorAll('.vf-measure')
      measureEl = allMeasures[currentMeasureNum.value - 1] || null
    }

    if (measureEl) {
      measureEl.classList.add('ns-active-measure')
      const notes = measureEl.querySelectorAll('.vf-stavenote')
      if (notes.length > 0 && notes[currentNoteIndex.value]) {
        notes[currentNoteIndex.value].classList.add('ns-active-note')
      }
    }
  }

  const handleContainerClick = (event: MouseEvent) => {
    const target = event.target as Element | null
    if (!target || !containerRef.value) return

    // 1. Check if a note or notehead was directly clicked
    const noteEl = target.closest('.vf-stavenote')
    const measureEl = target.closest('.vf-measure')

    if (measureEl) {
      const measureId = parseInt(measureEl.id || '', 10)
      let mNum = isNaN(measureId) ? 1 : measureId

      // Find staff index within this measure slot
      const sameIdMeasures = Array.from(
        containerRef.value.querySelectorAll(`.vf-measure[id="${measureEl.id}"]`)
      )
      let sIdx = sameIdMeasures.indexOf(measureEl)
      if (sIdx === -1) {
        if (isNaN(measureId)) {
          const allMeasures = Array.from(containerRef.value.querySelectorAll('.vf-measure'))
          const idx = allMeasures.indexOf(measureEl)
          if (idx !== -1) mNum = idx + 1
        }
        sIdx = 0
      }

      if (noteEl) {
        const allNotesInMeasure = Array.from(measureEl.querySelectorAll('.vf-stavenote'))
        const nIdx = Math.max(0, allNotesInMeasure.indexOf(noteEl))

        // Check chord head index if clicked directly on a notehead
        const noteheads = Array.from(noteEl.querySelectorAll('.vf-notehead'))
        const clickedHead = target.closest('.vf-notehead')
        const hIdx = (clickedHead && noteheads.length > 1) ? Math.max(0, noteheads.indexOf(clickedHead)) : 0

        currentMeasureNum.value = mNum
        currentStaffIndex.value = sIdx
        currentNoteIndex.value = nIdx
        currentHeadIndex.value = hIdx
        callbacks.onSelectNote(mNum, nIdx, sIdx, hIdx)
        highlightSelectedElement()
        return
      }

      // 2. Measure background clicked
      currentMeasureNum.value = mNum
      currentStaffIndex.value = sIdx
      currentNoteIndex.value = 0
      currentHeadIndex.value = 0
      callbacks.onSelectNote(mNum, 0, sIdx, 0)
      highlightSelectedElement()
    }
  }

  // Pitch Dragging Listeners (Mouse & Touch/Stylus Pointer Events)
  const handleMouseDown = (event: MouseEvent | PointerEvent) => {
    if ('button' in event && event.button !== 0 && event.button !== -1) return
    if (!containerRef.value) return
    const target = event.target as Element | null
    if (!target) return

    const noteEl = target.closest('.vf-stavenote')
    const measureEl = target.closest('.vf-measure')

    if (noteEl && measureEl) {
      isPitchDragging = true
      draggedPitchNoteEl = noteEl as HTMLElement
      dragStartY = event.clientY
      currentPitchShift = 0

      // Measure exact staff step size from rendered staff lines in SVG (1 step = distance / 2)
      let measuredStep = 5.0
      try {
        const paths = Array.from(measureEl.querySelectorAll('path'))
        const staffLines: number[] = []
        paths.forEach((p) => {
          const d = p.getAttribute('d') || ''
          const m = d.match(/^M\s*([\d\.]+)\s+([\d\.]+)\s*L\s*([\d\.]+)\s+([\d\.]+)/)
          if (m && Math.abs(parseFloat(m[2]) - parseFloat(m[4])) < 0.1) {
            const svgY = parseFloat(m[2])
            if (!staffLines.some((y) => Math.abs(y - svgY) < 1)) {
              staffLines.push(p.getBoundingClientRect().y)
            }
          }
        })
        staffLines.sort((a, b) => a - b)
        if (staffLines.length >= 2) {
          const lineDistance = staffLines[1] - staffLines[0]
          if (lineDistance > 4 && lineDistance < 30) {
            measuredStep = lineDistance / 2
          }
        }
      } catch {}
      currentStepSize = measuredStep

      // Hide stranded ledger lines during drag
      const ledgersEl = measureEl.querySelector('.vf-ledgers') as HTMLElement | null
      if (ledgersEl) {
        draggedLedgersEl = ledgersEl
        draggedLedgersEl.style.opacity = '0'
      }

      const measureId = parseInt(measureEl.id || '', 10)
      dragMeasureNum = isNaN(measureId) ? 1 : measureId

      const sameIdMeasures = Array.from(
        containerRef.value.querySelectorAll(`.vf-measure[id="${measureEl.id}"]`)
      )
      dragStaffIndex = sameIdMeasures.indexOf(measureEl)
      if (dragStaffIndex === -1) {
        if (isNaN(measureId)) {
          const allMeasures = Array.from(containerRef.value.querySelectorAll('.vf-measure'))
          const idx = allMeasures.indexOf(measureEl)
          if (idx !== -1) dragMeasureNum = idx + 1
        }
        dragStaffIndex = 0
      }

      const allNotes = Array.from(measureEl.querySelectorAll('.vf-stavenote'))
      dragNoteIndex = Math.max(0, allNotes.indexOf(noteEl))

      const noteheads = Array.from(noteEl.querySelectorAll('.vf-notehead'))
      const clickedHead = target.closest('.vf-notehead')
      dragHeadIndex = (clickedHead && noteheads.length > 1) ? Math.max(0, noteheads.indexOf(clickedHead)) : 0

      currentMeasureNum.value = dragMeasureNum
      currentStaffIndex.value = dragStaffIndex
      currentNoteIndex.value = dragNoteIndex
      currentHeadIndex.value = dragHeadIndex
      callbacks.onSelectNote(dragMeasureNum, dragNoteIndex, dragStaffIndex, dragHeadIndex)
      highlightSelectedElement()
    }
  }

  let currentStepSize = 5.0
  let draggedLedgersEl: HTMLElement | null = null

  const handleMouseMove = (event: MouseEvent | PointerEvent) => {
    if (!isPitchDragging) return
    const deltaY = dragStartY - event.clientY // Moving up is positive shift
    const diatonicSteps = Math.round(deltaY / currentStepSize)

    // Snap the visual notehead to the exact staff line / space
    if (draggedPitchNoteEl) {
      const snappedY = -(diatonicSteps * currentStepSize)
      draggedPitchNoteEl.style.transform = `translateY(${snappedY}px)`
      draggedPitchNoteEl.style.transition = 'none'
    }

    if (diatonicSteps !== currentPitchShift) {
      currentPitchShift = diatonicSteps
      callbacks.onPitchDragProgress?.(
        dragMeasureNum,
        dragNoteIndex,
        diatonicSteps,
        event.clientX,
        event.clientY,
        dragStaffIndex,
        dragHeadIndex
      )
    }
  }

  const handleMouseUp = () => {
    if (draggedPitchNoteEl) {
      draggedPitchNoteEl.style.transform = ''
      draggedPitchNoteEl.style.transition = ''
      draggedPitchNoteEl = null
    }
    if (draggedLedgersEl) {
      draggedLedgersEl.style.opacity = ''
      draggedLedgersEl = null
    }
    if (!isPitchDragging) return
    isPitchDragging = false
    if (currentPitchShift !== 0) {
      callbacks.onPitchDragEnd?.(
        dragMeasureNum,
        dragNoteIndex,
        currentPitchShift,
        dragStaffIndex,
        dragHeadIndex
      )
    }
    currentPitchShift = 0
  }

  // HTML5 Drag and Drop Handlers (from palette onto score)
  const handleDragOver = (event: DragEvent) => {
    if (!event.dataTransfer || !containerRef.value) return
    if (!event.dataTransfer.types.includes('application/notesight-tool')) return

    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'

    if (activeDraggingTool.value) {
      dragToolState.value = {
        visible: true,
        x: event.clientX,
        y: event.clientY,
        type: activeDraggingTool.value.type,
        value: activeDraggingTool.value.value,
        label: activeDraggingTool.value.label,
        symbol: activeDraggingTool.value.symbol
      }
    }

    const target = event.target as Element | null
    if (!target) return
    const measureEl = target.closest('.vf-measure')
    const noteEl = target.closest('.vf-stavenote')

    containerRef.value.querySelectorAll('.ns-drop-target').forEach((el) => {
      if (el !== measureEl) el.classList.remove('ns-drop-target')
    })
    containerRef.value.querySelectorAll('.ns-drop-slot-ghost').forEach((el) => {
      if (el !== noteEl) el.classList.remove('ns-drop-slot-ghost')
    })

    if (measureEl) {
      measureEl.classList.add('ns-drop-target')
      if (noteEl) {
        noteEl.classList.add('ns-drop-slot-ghost')
      } else {
        const allNotes = Array.from(measureEl.querySelectorAll('.vf-stavenote'))
        const targetNote = allNotes[currentNoteIndex.value] || allNotes[0]
        if (targetNote) {
          targetNote.classList.add('ns-drop-slot-ghost')
        }
      }
    }
  }

  const handleDragLeave = (event: DragEvent) => {
    if (!containerRef.value) return
    const related = event.relatedTarget as Node | null
    if (!related || !containerRef.value.contains(related)) {
      dragToolState.value.visible = false
      containerRef.value.querySelectorAll('.ns-drop-target').forEach((el) => {
        el.classList.remove('ns-drop-target')
      })
      containerRef.value.querySelectorAll('.ns-drop-slot-ghost').forEach((el) => {
        el.classList.remove('ns-drop-slot-ghost')
      })
    }
  }

  const handleDrop = (event: DragEvent) => {
    dragToolState.value.visible = false
    if (!containerRef.value) return
    containerRef.value.querySelectorAll('.ns-drop-target').forEach((el) => {
      el.classList.remove('ns-drop-target')
    })
    containerRef.value.querySelectorAll('.ns-drop-slot-ghost').forEach((el) => {
      el.classList.remove('ns-drop-slot-ghost')
    })

    const rawData = event.dataTransfer?.getData('application/notesight-tool')
    if (!rawData) return

    event.preventDefault()
    try {
      const tool = JSON.parse(rawData)
      const target = event.target as Element | null
      if (!target) return

      const measureEl = target.closest('.vf-measure')
      const noteEl = target.closest('.vf-stavenote')

      if (measureEl) {
        const measureId = parseInt(measureEl.id || '', 10)
        let mNum = isNaN(measureId) ? 1 : measureId
        const sameIdMeasures = Array.from(
          containerRef.value.querySelectorAll(`.vf-measure[id="${measureEl.id}"]`)
        )
        let sIdx = sameIdMeasures.indexOf(measureEl)
        if (sIdx === -1) {
          if (isNaN(measureId)) {
            const allMeasures = Array.from(containerRef.value.querySelectorAll('.vf-measure'))
            const idx = allMeasures.indexOf(measureEl)
            if (idx !== -1) mNum = idx + 1
          }
          sIdx = 0
        }

        const allNotes = Array.from(measureEl.querySelectorAll('.vf-stavenote'))
        let nIdx = 0
        if (noteEl) {
          nIdx = Math.max(0, allNotes.indexOf(noteEl))
        } else {
          if (mNum === currentMeasureNum.value && sIdx === currentStaffIndex.value && currentNoteIndex.value < allNotes.length) {
            nIdx = currentNoteIndex.value
          } else {
            nIdx = 0
          }
        }

        currentMeasureNum.value = mNum
        currentStaffIndex.value = sIdx
        currentNoteIndex.value = nIdx
        currentHeadIndex.value = 0
        callbacks.onDropTool?.(mNum, nIdx, tool, sIdx)
        highlightSelectedElement()
      }
    } catch (err) {
      console.warn('Failed to handle dropped tool:', err)
    }
  }

  const handleKeyDown = (e: KeyboardEvent) => {
    const target = e.target as HTMLElement
    const tag = target?.tagName?.toLowerCase()
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || target?.isContentEditable) return

    // Guard if modal dialog is open or focused element is interactive
    const isModalOpen = typeof document !== 'undefined' && Boolean(document.querySelector('[role="dialog"], .modal-backdrop'))
    if (isModalOpen || tag === 'button' || tag === 'a') {
      if (e.code === 'Space') return
    }

    // Undo / Redo
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
      e.preventDefault()
      if (e.shiftKey) {
        callbacks.onRedo()
      } else {
        callbacks.onUndo()
      }
      return
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
      e.preventDefault()
      callbacks.onRedo()
      return
    }

    // Playback toggle
    if (e.code === 'Space') {
      e.preventDefault()
      callbacks.onTogglePlay()
      return
    }

    // Switch staff: Alt + ArrowUp / Alt + ArrowDown
    if (e.altKey && e.key === 'ArrowDown') {
      e.preventDefault()
      currentStaffIndex.value += 1
      currentNoteIndex.value = 0
      currentHeadIndex.value = 0
      callbacks.onSelectNote(currentMeasureNum.value, 0, currentStaffIndex.value, 0)
      highlightSelectedElement()
      return
    }
    if (e.altKey && e.key === 'ArrowUp') {
      e.preventDefault()
      currentStaffIndex.value = Math.max(0, currentStaffIndex.value - 1)
      currentNoteIndex.value = 0
      currentHeadIndex.value = 0
      callbacks.onSelectNote(currentMeasureNum.value, 0, currentStaffIndex.value, 0)
      highlightSelectedElement()
      return
    }

    // Step navigation
    if (e.key === 'ArrowLeft') {
      e.preventDefault()
      if (currentNoteIndex.value > 0) {
        currentNoteIndex.value -= 1
      } else if (currentMeasureNum.value > 1) {
        currentMeasureNum.value -= 1
        const prevCount = getNotesCount(currentMeasureNum.value, currentStaffIndex.value)
        currentNoteIndex.value = Math.max(0, prevCount - 1)
      }
      currentHeadIndex.value = 0
      callbacks.onSelectNote(currentMeasureNum.value, currentNoteIndex.value, currentStaffIndex.value, 0)
      highlightSelectedElement()
      return
    }
    if (e.key === 'ArrowRight') {
      e.preventDefault()
      const currentCount = getNotesCount(currentMeasureNum.value, currentStaffIndex.value)
      if (currentNoteIndex.value + 1 < currentCount) {
        currentNoteIndex.value += 1
      } else {
        const total = getTotalMeasuresCount()
        if (currentMeasureNum.value < total) {
          currentMeasureNum.value += 1
          currentNoteIndex.value = 0
        }
      }
      currentHeadIndex.value = 0
      callbacks.onSelectNote(currentMeasureNum.value, currentNoteIndex.value, currentStaffIndex.value, 0)
      highlightSelectedElement()
      return
    }

    // Transpose
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      callbacks.onTranspose(e.shiftKey ? 12 : 1)
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      callbacks.onTranspose(e.shiftKey ? -12 : -1)
      return
    }

    // Duration shortcuts: 1-6
    const durationMap: Record<string, string> = {
      '1': 'whole',
      '2': 'half',
      '3': 'quarter',
      '4': 'eighth',
      '5': '16th',
      '6': '32nd'
    }
    if (durationMap[e.key]) {
      e.preventDefault()
      callbacks.onSetNoteType(durationMap[e.key])
      return
    }

    // Dot shortcut
    if (e.key === '.') {
      e.preventDefault()
      callbacks.onToggleDot()
      return
    }

    // Rest shortcut
    if (e.key.toLowerCase() === 'r' || e.key === 'Backspace' || e.key === 'Delete') {
      e.preventDefault()
      callbacks.onToggleRest()
      return
    }

    // Tie shortcut: 't'
    if (e.key.toLowerCase() === 't') {
      e.preventDefault()
      callbacks.onToggleTie?.()
      return
    }
  }

  const handleWindowDragEnd = () => {
    dragToolState.value.visible = false
    if (containerRef.value) {
      containerRef.value.querySelectorAll('.ns-drop-target').forEach((el) => {
        el.classList.remove('ns-drop-target')
      })
      containerRef.value.querySelectorAll('.ns-drop-slot-ghost').forEach((el) => {
        el.classList.remove('ns-drop-slot-ghost')
      })
    }
  }

  const stepForwardSelection = () => {
    const count = callbacks.getMeasureNotesCount?.(currentMeasureNum.value, currentStaffIndex.value) ?? 1
    const total = callbacks.getTotalMeasures?.() ?? 1
    if (currentNoteIndex.value + 1 < count) {
      currentNoteIndex.value += 1
      currentHeadIndex.value = 0
    } else if (currentMeasureNum.value < total) {
      currentMeasureNum.value += 1
      currentNoteIndex.value = 0
      currentHeadIndex.value = 0
    }
    callbacks.onSelectNote(
      currentMeasureNum.value,
      currentNoteIndex.value,
      currentStaffIndex.value,
      currentHeadIndex.value
    )
    highlightSelectedElement()
  }

  onMounted(() => {
    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    window.addEventListener('pointermove', handleMouseMove)
    window.addEventListener('pointerup', handleMouseUp)
    window.addEventListener('pointercancel', handleMouseUp)
    window.addEventListener('dragend', handleWindowDragEnd)
  })

  onUnmounted(() => {
    window.removeEventListener('keydown', handleKeyDown)
    window.removeEventListener('mousemove', handleMouseMove)
    window.removeEventListener('mouseup', handleMouseUp)
    window.removeEventListener('pointermove', handleMouseMove)
    window.removeEventListener('pointerup', handleMouseUp)
    window.removeEventListener('pointercancel', handleMouseUp)
    window.removeEventListener('dragend', handleWindowDragEnd)
    synth.close()
  })

  return {
    currentMeasureNum,
    currentStaffIndex,
    currentNoteIndex,
    currentHeadIndex,
    dragToolState,
    handleContainerClick,
    handleMouseDown,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    highlightSelectedElement,
    stepForwardSelection,
    playNoteAudition,
    destroy: () => synth.close()
  }
}
