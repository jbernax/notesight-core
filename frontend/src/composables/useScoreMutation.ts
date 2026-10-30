import { ref, computed, shallowRef } from 'vue'
import { resolveTrackVoiceTag } from '../audio/scorePlayer'

export interface ParsedNote {
  index: number
  onsetIndex: number
  headIndex: number
  summary: string
  isRest: boolean
  isChord: boolean
  step: string
  octave: number
  alter: number // -2 to +2
  type: string  // 'whole' | 'half' | 'quarter' | 'eighth' | '16th' | '32nd'
  isDotted: boolean
  lyrics: string
  dynamics?: string
  duration: number
  staff: number
  voice?: number
  hasTieStart?: boolean
  hasTieStop?: boolean
}

export interface MeasureAttributes {
  beats: number
  beatType: number
  fifths: number
  clefSign: string
  clefLine: number
}

export interface MutationResult {
  xml: string
  nextMeasureNum: number
  nextNoteIndex: number
  measureCompleted: boolean
}


export function createRestNode(doc: Document, durationDivs: number, divisions: number): Element {
  const restNote = doc.createElement('note')
  const restEl = doc.createElement('rest')
  const durEl = doc.createElement('duration')
  durEl.textContent = String(Math.max(1, Math.round(durationDivs)))
  const typeEl = doc.createElement('type')

  const quarterDivs = divisions
  const wholeDivs = divisions * 4
  const halfDivs = divisions * 2
  const eighthDivs = divisions / 2
  const sixteenthDivs = divisions / 4

  let isDotted = false
  if (durationDivs >= wholeDivs) {
    typeEl.textContent = 'whole'
  } else if (durationDivs >= halfDivs * 1.5) {
    typeEl.textContent = 'half'
    isDotted = true
  } else if (durationDivs >= halfDivs) {
    typeEl.textContent = 'half'
  } else if (durationDivs >= quarterDivs * 1.5) {
    typeEl.textContent = 'quarter'
    isDotted = true
  } else if (durationDivs >= quarterDivs) {
    typeEl.textContent = 'quarter'
  } else if (durationDivs >= eighthDivs * 1.5) {
    typeEl.textContent = 'eighth'
    isDotted = true
  } else if (durationDivs >= eighthDivs) {
    typeEl.textContent = 'eighth'
  } else if (durationDivs >= sixteenthDivs) {
    typeEl.textContent = '16th'
  } else {
    typeEl.textContent = '32nd'
  }

  restNote.appendChild(restEl)
  restNote.appendChild(durEl)
  restNote.appendChild(typeEl)
  if (isDotted) {
    const dotEl = doc.createElement('dot')
    restNote.appendChild(dotEl)
  }
  return restNote
}

export const NOTE_TYPE_DIVISIONS: Record<string, number> = {
  whole: 16,
  half: 8,
  quarter: 4,
  eighth: 2,
  '16th': 1,
  '32nd': 0.5
}

export const NOTE_STEPS = ['C', 'D', 'E', 'F', 'G', 'A', 'B'] as const
export type NoteStep = typeof NOTE_STEPS[number]

export const STEP_SEMITONES: Record<NoteStep, number> = {
  C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11
}

export const SEMITONE_TO_STEP: Array<{ step: NoteStep; alter: number }> = [
  { step: 'C', alter: 0 },
  { step: 'C', alter: 1 },
  { step: 'D', alter: 0 },
  { step: 'D', alter: 1 },
  { step: 'E', alter: 0 },
  { step: 'F', alter: 0 },
  { step: 'F', alter: 1 },
  { step: 'G', alter: 0 },
  { step: 'G', alter: 1 },
  { step: 'A', alter: 0 },
  { step: 'A', alter: 1 },
  { step: 'B', alter: 0 }
]

export function useScoreMutation(initialXml: string) {
  const workingXml = ref<string>(initialXml)
  const savedXml = ref<string>(initialXml)
  const undoStack = shallowRef<string[]>([])
  const redoStack = shallowRef<string[]>([])
  const maxHistory = 30

  const canUndo = computed(() => undoStack.value.length > 0)
  const canRedo = computed(() => redoStack.value.length > 0)
  const isDirty = computed(() => workingXml.value.trim() !== savedXml.value.trim())

  const markSaved = (xml?: string) => {
    savedXml.value = (xml !== undefined ? xml : workingXml.value).trim()
  }

  const resetToSaved = () => {
    workingXml.value = savedXml.value
    undoStack.value = []
    redoStack.value = []
    return workingXml.value
  }

  const pushState = (newXml: string) => {
    if (newXml === workingXml.value) return
    const nextUndo = [...undoStack.value, workingXml.value]
    if (nextUndo.length > maxHistory) {
      nextUndo.shift()
    }
    undoStack.value = nextUndo
    redoStack.value = []
    workingXml.value = newXml
  }

  const undo = () => {
    if (!canUndo.value) return null
    const stack = [...undoStack.value]
    const prev = stack.pop()!
    undoStack.value = stack
    redoStack.value = [...redoStack.value, workingXml.value]
    workingXml.value = prev
    return prev
  }

  const redo = () => {
    if (!canRedo.value) return null
    const stack = [...redoStack.value]
    const next = stack.pop()!
    redoStack.value = stack
    undoStack.value = [...undoStack.value, workingXml.value]
    workingXml.value = next
    return next
  }

  const getDoc = (): Document => {
    const parser = new DOMParser()
    return parser.parseFromString(workingXml.value, 'text/xml')
  }

  const serializeDoc = (doc: Document): string => {
    const serializer = new XMLSerializer()
    return serializer.serializeToString(doc)
  }

  const getMeasureElement = (doc: Document, measureNum: number): Element | null => {
    let elem = doc.querySelector(`part measure[number="${measureNum}"]`)
    if (!elem) {
      const all = doc.querySelectorAll('part measure')
      elem = all[measureNum - 1] || null
    }
    return elem
  }

  const resolveStaffTarget = (
    doc: Document,
    measureNum: number,
    globalStaffIndex: number = 0
  ): {
    part: Element | null
    measure: Element | null
    staffInPart: number
    stavesInPart: number
    notes: Element[]
    onsets: Element[][]
  } => {
    const parts = Array.from(doc.querySelectorAll('score-partwise > part'))
    if (parts.length === 0) {
      return { part: null, measure: null, staffInPart: 1, stavesInPart: 1, notes: [], onsets: [] }
    }

    let currentStaffOffset = 0
    let targetPart: Element | null = null
    let targetMeasure: Element | null = null
    let staffInPart = 1
    let stavesInPart = 1

    for (const part of parts) {
      let measure = part.querySelector(`measure[number="${measureNum}"]`)
      if (!measure) {
        const allMeasures = Array.from(part.querySelectorAll('measure'))
        measure = allMeasures[measureNum - 1] || null
      }

      let partStaves = 1
      const stavesEl = measure?.querySelector('attributes > staves') || part.querySelector('attributes > staves')
      if (stavesEl) {
        const parsed = parseInt(stavesEl.textContent?.trim() || '1', 10)
        if (!isNaN(parsed) && parsed > 0) {
          partStaves = parsed
        }
      }

      if (globalStaffIndex < currentStaffOffset + partStaves) {
        targetPart = part
        targetMeasure = measure
        staffInPart = (globalStaffIndex - currentStaffOffset) + 1
        stavesInPart = partStaves
        break
      }

      currentStaffOffset += partStaves
    }

    if (!targetPart) {
      targetPart = parts[0]
      targetMeasure = targetPart.querySelector(`measure[number="${measureNum}"]`) ||
        targetPart.querySelectorAll('measure')[measureNum - 1] || null
      staffInPart = 1
      stavesInPart = 1
    }

    if (!targetMeasure) {
      return { part: targetPart, measure: null, staffInPart, stavesInPart, notes: [], onsets: [] }
    }

    const allNotesInMeasure = Array.from(targetMeasure.querySelectorAll('note'))
    const filteredNotes = stavesInPart > 1
      ? allNotesInMeasure.filter(n => {
          const sEl = n.querySelector('staff')
          if (sEl) {
            return parseInt(sEl.textContent?.trim() || '1', 10) === staffInPart
          }
          return staffInPart === 1
        })
      : allNotesInMeasure

    const onsets: Element[][] = []
    filteredNotes.forEach(note => {
      const isChord = note.querySelector('chord') !== null
      if (isChord && onsets.length > 0) {
        onsets[onsets.length - 1].push(note)
      } else {
        onsets.push([note])
      }
    })

    return {
      part: targetPart,
      measure: targetMeasure,
      staffInPart,
      stavesInPart,
      notes: filteredNotes,
      onsets
    }
  }

  const resolveTargetNote = (
    doc: Document,
    measureNum: number,
    noteIndex: number,
    staffIndex: number = 0,
    headIndex: number = 0
  ): {
    target: Element | null
    info: ReturnType<typeof resolveStaffTarget>
    actualOnsetIndex: number
    actualHeadIndex: number
  } => {
    const info = resolveStaffTarget(doc, measureNum, staffIndex)
    if (!info.measure || info.notes.length === 0) {
      return { target: null, info, actualOnsetIndex: 0, actualHeadIndex: 0 }
    }

    if (noteIndex >= 0 && noteIndex < info.onsets.length) {
      const onset = info.onsets[noteIndex]
      const hIdx = Math.max(0, Math.min(onset.length - 1, headIndex))
      return {
        target: onset[hIdx] || onset[0] || null,
        info,
        actualOnsetIndex: noteIndex,
        actualHeadIndex: hIdx
      }
    }

    const target = info.notes[noteIndex] || info.notes[0] || null
    return { target, info, actualOnsetIndex: noteIndex, actualHeadIndex: 0 }
  }

  const getTotalMeasures = (doc?: Document): number => {
    const d = doc || getDoc()
    return Math.max(1, d.querySelectorAll('part measure').length)
  }

  const getMeasureAttributes = (measureNum: number, staffIndex: number = 0, doc?: Document): MeasureAttributes => {
    const d = doc || getDoc()
    const info = resolveStaffTarget(d, measureNum, staffIndex)
    const measure = info.measure
    const attr = measure?.querySelector('attributes') || info.part?.querySelector('attributes') || d.querySelector('part measure attributes')

    const beatsEl = attr?.querySelector('time > beats')
    const beatTypeEl = attr?.querySelector('time > beat-type')
    const fifthsEl = attr?.querySelector('key > fifths')

    let clefEl: Element | null = null
    if (attr) {
      if (info.staffInPart > 0) {
        clefEl = attr.querySelector(`clef[number="${info.staffInPart}"]`)
      }
      if (!clefEl) {
        const allClefs = Array.from(attr.querySelectorAll('clef'))
        clefEl = allClefs[info.staffInPart - 1] || allClefs[0] || null
      }
    }

    const clefSignEl = clefEl?.querySelector('sign')
    const clefLineEl = clefEl?.querySelector('line')

    const defaultSign = info.staffInPart === 2 ? 'F' : 'G'
    const defaultLine = info.staffInPart === 2 ? 4 : 2

    return {
      beats: parseInt(beatsEl?.textContent?.trim() || '4', 10),
      beatType: parseInt(beatTypeEl?.textContent?.trim() || '4', 10),
      fifths: parseInt(fifthsEl?.textContent?.trim() || '0', 10),
      clefSign: clefSignEl?.textContent?.trim() || defaultSign,
      clefLine: parseInt(clefLineEl?.textContent?.trim() || String(defaultLine), 10)
    }
  }

  const getNotesInMeasure = (measureNum: number, staffIndex: number = 0, doc?: Document): ParsedNote[] => {
    const d = doc || getDoc()
    const info = resolveStaffTarget(d, measureNum, staffIndex)
    if (!info.measure) return []

    const result: ParsedNote[] = []
    let currentOnsetIndex = -1
    let currentHeadIndex = 0

    info.notes.forEach((note, idx) => {
      const isRest = note.querySelector('rest') !== null
      const isChord = note.querySelector('chord') !== null

      if (isChord) {
        currentHeadIndex++
      } else {
        currentOnsetIndex++
        currentHeadIndex = 0
      }

      const stepElem = note.querySelector('pitch > step')
      const octElem = note.querySelector('pitch > octave')
      const alterElem = note.querySelector('pitch > alter')
      const typeElem = note.querySelector('type')
      const dotElem = note.querySelector('dot')
      const durElem = note.querySelector('duration')
      const lyricElem = note.querySelector('lyric > text')
      const dynElem = note.querySelector('notations > dynamics')
      const hasTieStart = note.querySelector('tie[type="start"], notations > tied[type="start"]') !== null
      const hasTieStop = note.querySelector('tie[type="stop"], notations > tied[type="stop"]') !== null

      let noteDynamics: string | undefined = undefined
      if (dynElem) {
        const dynFirstChild = dynElem.firstElementChild
        if (dynFirstChild) {
          noteDynamics = dynFirstChild.tagName.toLowerCase()
        }
      }

      const step = stepElem?.textContent?.trim() || 'C'
      const octave = octElem ? parseInt(octElem.textContent?.trim() || '4', 10) : 4
      const alter = alterElem ? parseInt(alterElem.textContent?.trim() || '0', 10) : 0
      const type = typeElem?.textContent?.trim() || 'quarter'
      const isDotted = dotElem !== null
      const duration = durElem ? parseInt(durElem.textContent?.trim() || '1', 10) : 1
      const lyrics = lyricElem?.textContent?.trim() || ''

      const accidentalSymbol = alter === 1 ? '♯' : alter === -1 ? '♭' : alter === 2 ? '𝄪' : alter === -2 ? '𝄫' : ''
      const chordPrefix = isChord ? 'Chord: ' : ''
      const dynSuffix = noteDynamics ? ` [${noteDynamics}]` : ''
      const tieSuffix = hasTieStart ? ' ⌒' : ''
      const summary = isRest
        ? `Rest (${type})`
        : `${chordPrefix}${step}${accidentalSymbol}${octave} (${type}${isDotted ? ' dot' : ''})${tieSuffix}${dynSuffix}`

      const vElem = note.querySelector('voice')
      const voiceNum = vElem ? parseInt(vElem.textContent?.trim() || '1', 10) : 1

      result.push({
        index: idx,
        onsetIndex: currentOnsetIndex,
        headIndex: currentHeadIndex,
        summary,
        isRest,
        isChord,
        step,
        octave,
        alter,
        type,
        isDotted,
        lyrics,
        dynamics: noteDynamics,
        duration,
        staff: info.staffInPart,
        voice: voiceNum,
        hasTieStart,
        hasTieStop,
      })
    })

    return result
  }

  const setNotePitch = (
    measureNum: number,
    noteIndex: number,
    step: string,
    octave: number,
    alter: number = 0,
    staffIndex: number = 0,
    headIndex: number = 0
  ) => {
    const doc = getDoc()
    const { target, info } = resolveTargetNote(doc, measureNum, noteIndex, staffIndex, headIndex)
    if (!target) return null

    // Remove rest if present
    const restNode = target.querySelector('rest')
    if (restNode) restNode.remove()

    let pitchNode = target.querySelector('pitch')
    if (!pitchNode) {
      pitchNode = doc.createElement('pitch')
      target.insertBefore(pitchNode, target.firstChild)
    }

    let stepNode = pitchNode.querySelector('step')
    if (!stepNode) {
      stepNode = doc.createElement('step')
      pitchNode.appendChild(stepNode)
    }
    stepNode.textContent = step

    let octNode = pitchNode.querySelector('octave')
    if (!octNode) {
      octNode = doc.createElement('octave')
      pitchNode.appendChild(octNode)
    }
    octNode.textContent = String(octave)

    let alterNode = pitchNode.querySelector('alter')
    if (alter !== 0) {
      if (!alterNode) {
        alterNode = doc.createElement('alter')
        pitchNode.appendChild(alterNode)
      }
      alterNode.textContent = String(alter)
    } else if (alterNode) {
      alterNode.remove()
    }

    if (info.stavesInPart > 1 && !target.querySelector('staff')) {
      const staffEl = doc.createElement('staff')
      staffEl.textContent = String(info.staffInPart)
      target.appendChild(staffEl)
    }

    const xml = serializeDoc(doc)
    pushState(xml)
    return xml
  }

  const setNoteType = (
    measureNum: number,
    noteIndex: number,
    type: string,
    isDotted: boolean = false,
    isRest: boolean = false,
    staffIndex: number = 0,
    headIndex: number = 0
  ) => {
    const doc = getDoc()
    const { target, info } = resolveTargetNote(doc, measureNum, noteIndex, staffIndex, headIndex)
    if (!target) return null

    const divisions = parseInt(doc.querySelector('attributes > divisions')?.textContent || '4', 10) || 4

    // 1. Rest vs Pitch
    const restNode = target.querySelector('rest')
    const pitchNode = target.querySelector('pitch')

    if (isRest) {
      if (pitchNode) pitchNode.remove()
      if (!restNode) {
        const newRest = doc.createElement('rest')
        target.insertBefore(newRest, target.firstChild)
      }
    } else {
      if (restNode) restNode.remove()
      if (!pitchNode) {
        const newPitch = doc.createElement('pitch')
        const s = doc.createElement('step')
        s.textContent = 'C'
        const o = doc.createElement('octave')
        o.textContent = info.staffInPart === 2 ? '3' : '4'
        newPitch.appendChild(s)
        newPitch.appendChild(o)
        target.insertBefore(newPitch, target.firstChild)
      }
    }

    // 2. Type
    let typeNode = target.querySelector('type')
    if (!typeNode) {
      typeNode = doc.createElement('type')
      target.appendChild(typeNode)
    }
    typeNode.textContent = type

    // 3. Dot
    const dotNode = target.querySelector('dot')
    if (isDotted && !dotNode) {
      const newDot = doc.createElement('dot')
      target.appendChild(newDot)
    } else if (!isDotted && dotNode) {
      dotNode.remove()
    }

    // 4. Update duration based on divisions
    let baseDiv = (NOTE_TYPE_DIVISIONS[type] || 4) / 4 * divisions
    if (isDotted) baseDiv = Math.round(baseDiv * 1.5)
    let durNode = target.querySelector('duration')
    if (!durNode) {
      durNode = doc.createElement('duration')
      target.appendChild(durNode)
    }
    durNode.textContent = String(Math.max(1, Math.round(baseDiv)))

    if (info.stavesInPart > 1 && !target.querySelector('staff')) {
      const staffEl = doc.createElement('staff')
      staffEl.textContent = String(info.staffInPart)
      target.appendChild(staffEl)
    }

    const xml = serializeDoc(doc)
    pushState(xml)
    return xml
  }

  const toggleAccidental = (
    measureNum: number,
    noteIndex: number,
    alter: number,
    staffIndex: number = 0,
    headIndex: number = 0
  ) => {
    const doc = getDoc()
    const { target, info } = resolveTargetNote(doc, measureNum, noteIndex, staffIndex, headIndex)
    if (!target) return null

    if (target.querySelector('rest')) {
      target.querySelector('rest')?.remove()
      const pitch = doc.createElement('pitch')
      const step = doc.createElement('step')
      step.textContent = 'C'
      const oct = doc.createElement('octave')
      oct.textContent = info.staffInPart === 2 ? '3' : '4'
      pitch.appendChild(step)
      pitch.appendChild(oct)
      if (alter !== 0) {
        const alt = doc.createElement('alter')
        alt.textContent = String(alter)
        pitch.appendChild(alt)
      }
      target.insertBefore(pitch, target.firstChild)
      if (info.stavesInPart > 1 && !target.querySelector('staff')) {
        const sEl = doc.createElement('staff')
        sEl.textContent = String(info.staffInPart)
        target.appendChild(sEl)
      }
      const xml = serializeDoc(doc)
      pushState(xml)
      return xml
    }

    let pitchNode = target.querySelector('pitch')
    if (!pitchNode) return null

    let alterNode = pitchNode.querySelector('alter')
    const currentAlter = alterNode ? parseInt(alterNode.textContent?.trim() || '0', 10) : 0

    const newAlter = currentAlter === alter ? 0 : alter
    if (newAlter !== 0) {
      if (!alterNode) {
        alterNode = doc.createElement('alter')
        pitchNode.appendChild(alterNode)
      }
      alterNode.textContent = String(newAlter)
    } else if (alterNode) {
      alterNode.remove()
    }

    const xml = serializeDoc(doc)
    pushState(xml)
    return xml
  }

  const toggleDot = (
    measureNum: number,
    noteIndex: number,
    staffIndex: number = 0,
    headIndex: number = 0
  ) => {
    const doc = getDoc()
    const { target } = resolveTargetNote(doc, measureNum, noteIndex, staffIndex, headIndex)
    if (!target) return null

    const dotNode = target.querySelector('dot')
    const isCurrentlyDotted = dotNode !== null
    const type = target.querySelector('type')?.textContent?.trim() || 'quarter'
    return setNoteType(measureNum, noteIndex, type, !isCurrentlyDotted, target.querySelector('rest') !== null, staffIndex, headIndex)
  }

  const toggleRest = (
    measureNum: number,
    noteIndex: number,
    staffIndex: number = 0,
    headIndex: number = 0
  ) => {
    const doc = getDoc()
    const { target } = resolveTargetNote(doc, measureNum, noteIndex, staffIndex, headIndex)
    if (!target) return null

    const isCurrentlyRest = target.querySelector('rest') !== null
    const type = target.querySelector('type')?.textContent?.trim() || 'quarter'
    const isDotted = target.querySelector('dot') !== null
    return setNoteType(measureNum, noteIndex, type, isDotted, !isCurrentlyRest, staffIndex, headIndex)
  }

  const toggleTie = (
    measureNum: number,
    noteIndex: number,
    staffIndex: number = 0,
    headIndex: number = 0
  ) => {
    const doc = getDoc()
    const { target, info } = resolveTargetNote(doc, measureNum, noteIndex, staffIndex, headIndex)
    if (!target || target.querySelector('rest')) return null

    const existingTieStart = target.querySelector('tie[type="start"]')
    const existingTiedStart = target.querySelector('notations > tied[type="start"]')

    if (existingTieStart || existingTiedStart) {
      // Remove tie start from current note
      existingTieStart?.remove()
      existingTiedStart?.remove()

      // Also clean up notations container if empty
      const notations = target.querySelector('notations')
      if (notations && notations.children.length === 0) {
        notations.remove()
      }

      // Try finding the tied destination note to clear stop
      const nextTarget = info.notes[target.parentElement === info.measure ? info.notes.indexOf(target) + 1 : -1]
      if (nextTarget) {
        nextTarget.querySelector('tie[type="stop"]')?.remove()
        nextTarget.querySelector('notations > tied[type="stop"]')?.remove()
        const nextNotations = nextTarget.querySelector('notations')
        if (nextNotations && nextNotations.children.length === 0) {
          nextNotations.remove()
        }
      }
    } else {
      // Add tie start to current note
      const tieStart = doc.createElement('tie')
      tieStart.setAttribute('type', 'start')
      target.appendChild(tieStart)

      let notations = target.querySelector('notations')
      if (!notations) {
        notations = doc.createElement('notations')
        target.appendChild(notations)
      }
      const tiedStart = doc.createElement('tied')
      tiedStart.setAttribute('type', 'start')
      notations.appendChild(tiedStart)

      // Find the next consecutive sounding note to attach tie stop
      const targetIdxInNotes = info.notes.indexOf(target)
      let nextNote: Element | null = null
      if (targetIdxInNotes !== -1 && targetIdxInNotes < info.notes.length - 1) {
        for (let j = targetIdxInNotes + 1; j < info.notes.length; j++) {
          if (!info.notes[j].querySelector('rest')) {
            nextNote = info.notes[j]
            break
          }
        }
      }

      // If next note is in the next measure
      if (!nextNote && info.part) {
        const nextMeasure = info.part.querySelector(`measure[number="${measureNum + 1}"]`)
        if (nextMeasure) {
          const nextMeasureNotes = Array.from(nextMeasure.querySelectorAll('note'))
          for (const cand of nextMeasureNotes) {
            if (!cand.querySelector('rest')) {
              nextNote = cand
              break
            }
          }
        }
      }

      if (nextNote) {
        const tieStop = doc.createElement('tie')
        tieStop.setAttribute('type', 'stop')
        nextNote.appendChild(tieStop)

        let nextNotations = nextNote.querySelector('notations')
        if (!nextNotations) {
          nextNotations = doc.createElement('notations')
          nextNote.appendChild(nextNotations)
        }
        const tiedStop = doc.createElement('tied')
        tiedStop.setAttribute('type', 'stop')
        nextNotations.appendChild(tiedStop)
      }
    }

    const xml = serializeDoc(doc)
    pushState(xml)
    return xml
  }

  const transposeNote = (
    measureNum: number,
    noteIndex: number,
    semitones: number,
    staffIndex: number = 0,
    headIndex: number = 0
  ) => {
    const doc = getDoc()
    const { target } = resolveTargetNote(doc, measureNum, noteIndex, staffIndex, headIndex)
    if (!target || target.querySelector('rest')) return null

    const stepEl = target.querySelector('pitch > step')
    const octEl = target.querySelector('pitch > octave')
    const alterEl = target.querySelector('pitch > alter')

    if (!stepEl || !octEl) return null

    const step = (stepEl.textContent?.trim() || 'C') as NoteStep
    const octave = parseInt(octEl.textContent?.trim() || '4', 10)
    const alter = alterEl ? parseInt(alterEl.textContent?.trim() || '0', 10) : 0

    const currentMidi = 12 + (octave * 12) + (STEP_SEMITONES[step] ?? 0) + alter
    const newMidi = Math.max(21, Math.min(108, currentMidi + semitones)) // Piano 88 keys range

    const newOctave = Math.floor((newMidi - 12) / 12)
    const semitoneInOctave = ((newMidi - 12) % 12 + 12) % 12
    const targetPitch = SEMITONE_TO_STEP[semitoneInOctave]

    return setNotePitch(measureNum, noteIndex, targetPitch.step, newOctave, targetPitch.alter, staffIndex, headIndex)
  }

  const shiftNoteDiatonic = (
    measureNum: number,
    noteIndex: number,
    stepsShift: number,
    staffIndex: number = 0,
    headIndex: number = 0
  ) => {
    const doc = getDoc()
    const { target } = resolveTargetNote(doc, measureNum, noteIndex, staffIndex, headIndex)
    if (!target || target.querySelector('rest')) return null

    const stepEl = target.querySelector('pitch > step')
    const octEl = target.querySelector('pitch > octave')
    const alterEl = target.querySelector('pitch > alter')

    if (!stepEl || !octEl) return null

    const step = (stepEl.textContent?.trim() || 'C') as NoteStep
    const octave = parseInt(octEl.textContent?.trim() || '4', 10)
    const alter = alterEl ? parseInt(alterEl.textContent?.trim() || '0', 10) : 0

    const stepIndex = NOTE_STEPS.indexOf(step)
    const totalDiatonicIndex = octave * 7 + (stepIndex !== -1 ? stepIndex : 0) + stepsShift
    const newOctave = Math.max(1, Math.min(8, Math.floor(totalDiatonicIndex / 7)))
    const newStepIndex = ((totalDiatonicIndex % 7) + 7) % 7
    const newStep = NOTE_STEPS[newStepIndex]

    return setNotePitch(measureNum, noteIndex, newStep, newOctave, alter, staffIndex, headIndex)
  }

  const addMeasure = (afterMeasureNum: number) => {
    const doc = getDoc()
    const part = doc.querySelector('part')
    if (!part) return null

    const measures = Array.from(part.querySelectorAll('measure'))
    const targetIdx = afterMeasureNum - 1
    const refMeasure = measures[targetIdx] || measures[measures.length - 1]

    const attr = getMeasureAttributes(afterMeasureNum, 0, doc)
    const divisions = parseInt(doc.querySelector('attributes > divisions')?.textContent || '4', 10) || 4
    const measureDuration = Math.round(attr.beats * (divisions * 4 / attr.beatType))

    const stavesEl = refMeasure?.querySelector('attributes > staves') || part.querySelector('attributes > staves')
    const stavesCount = stavesEl ? parseInt(stavesEl.textContent?.trim() || '1', 10) : 1

    const newMeasure = doc.createElement('measure')
    const noteTypeStr = attr.beatType === 4 && attr.beats === 4 ? 'whole' : 'quarter'

    if (stavesCount > 1) {
      for (let s = 1; s <= stavesCount; s++) {
        if (s > 1) {
          const backup = doc.createElement('backup')
          const dur = doc.createElement('duration')
          dur.textContent = String(measureDuration)
          backup.appendChild(dur)
          newMeasure.appendChild(backup)
        }
        const note = doc.createElement('note')
        const rest = doc.createElement('rest')
        const dur = doc.createElement('duration')
        dur.textContent = String(measureDuration)
        const type = doc.createElement('type')
        type.textContent = noteTypeStr
        const voice = doc.createElement('voice')
        voice.textContent = String(s)
        const staff = doc.createElement('staff')
        staff.textContent = String(s)

        note.appendChild(rest)
        note.appendChild(dur)
        note.appendChild(type)
        note.appendChild(voice)
        note.appendChild(staff)
        newMeasure.appendChild(note)
      }
    } else {
      const newNote = doc.createElement('note')
      const rest = doc.createElement('rest')
      const dur = doc.createElement('duration')
      dur.textContent = String(measureDuration)
      const type = doc.createElement('type')
      type.textContent = noteTypeStr

      newNote.appendChild(rest)
      newNote.appendChild(dur)
      newNote.appendChild(type)
      newMeasure.appendChild(newNote)
    }

    if (refMeasure && refMeasure.nextSibling) {
      part.insertBefore(newMeasure, refMeasure.nextSibling)
    } else {
      part.appendChild(newMeasure)
    }

    // Re-index all measures
    part.querySelectorAll('measure').forEach((m, idx) => {
      m.setAttribute('number', String(idx + 1))
    })

    const xml = serializeDoc(doc)
    pushState(xml)
    return xml
  }

  const deleteMeasure = (measureNum: number) => {
    const doc = getDoc()
    const parts = Array.from(doc.querySelectorAll('score-partwise > part'))
    if (parts.length === 0) return null

    // Check measure count in first part
    const primaryMeasures = Array.from(parts[0].querySelectorAll('measure'))
    if (primaryMeasures.length <= 1) return null

    for (const part of parts) {
      const measures = Array.from(part.querySelectorAll('measure'))
      const target = measures.find(m => m.getAttribute('number') === String(measureNum)) || measures[measureNum - 1]
      if (target) {
        target.remove()
      }
      part.querySelectorAll('measure').forEach((m, idx) => {
        m.setAttribute('number', String(idx + 1))
      })
    }

    const xml = serializeDoc(doc)
    pushState(xml)
    return xml
  }

  const deletePart = (partId: string) => {
    const doc = getDoc()
    const scoreParts = Array.from(doc.querySelectorAll('score-partwise > part-list > score-part'))
    if (scoreParts.length <= 1) {
      // Must maintain at least one playable musical line/part
      return null
    }

    const targetScorePart = scoreParts.find(sp => sp.getAttribute('id') === partId)
    const targetPart = doc.querySelector(`score-partwise > part[id="${partId}"]`)

    if (!targetScorePart && !targetPart) return null

    if (targetScorePart) {
      targetScorePart.remove()
    }
    if (targetPart) {
      targetPart.remove()
    }

    // Clean up empty part-groups if any
    const partList = doc.querySelector('score-partwise > part-list')
    if (partList) {
      const remainingScoreParts = partList.querySelectorAll('score-part')
      if (remainingScoreParts.length === 0) return null
    }

    const xml = serializeDoc(doc)
    pushState(xml)
    return xml
  }

  const deleteVoice = (partId: string, voiceNumber: number | string) => {
    const doc = getDoc()
    const part = doc.querySelector(`score-partwise > part[id="${partId}"]`) || doc.querySelector('score-partwise > part')
    if (!part) return null

    const targetVoiceStr = String(voiceNumber).trim()
    const measures = Array.from(part.querySelectorAll('measure'))
    let removedAny = false

    measures.forEach(measure => {
      const allNotes = Array.from(measure.querySelectorAll('note'))
      const voiceNotes = allNotes.filter(n => {
        const vEl = n.querySelector('voice')
        const vText = vEl?.textContent?.trim()
        return vText === targetVoiceStr || (!vEl && targetVoiceStr === '1')
      })

      if (voiceNotes.length === 0) return

      // Check if there are other notes belonging to other voices in this measure
      const otherNotes = allNotes.filter(n => !voiceNotes.includes(n))

      if (otherNotes.length > 0) {
        // Safe to remove this polyphonic voice's notes entirely
        voiceNotes.forEach(n => n.remove())
        removedAny = true
      } else {
        // If this was the only voice in the measure, replace with a full-measure rest on voice 1
        // to avoid invalid empty measures.
        const attr = measure.querySelector('attributes') || part.querySelector('attributes') || doc.querySelector('attributes')
        const divisions = parseInt(attr?.querySelector('divisions')?.textContent?.trim() || '4', 10) || 4
        const beats = parseInt(attr?.querySelector('time > beats')?.textContent?.trim() || '4', 10) || 4
        const beatType = parseInt(attr?.querySelector('time > beat-type')?.textContent?.trim() || '4', 10) || 4
        const measureDuration = Math.round((beats * (4 / beatType)) * divisions)

        voiceNotes.forEach(n => n.remove())
        const restNode = createRestNode(doc, measureDuration, divisions)
        const vEl = doc.createElement('voice')
        vEl.textContent = '1'
        restNode.appendChild(vEl)
        measure.appendChild(restNode)
        removedAny = true
      }
    })

    if (!removedAny) return null

    const xml = serializeDoc(doc)
    pushState(xml)
    return xml
  }

  const getPartVoices = (partId?: string): Array<{ partId: string; voiceId: number; noteCount: number }> => {
    const parser = new DOMParser()
    const doc = parser.parseFromString(workingXml.value, 'application/xml')
    const selector = partId ? `score-partwise > part[id="${partId}"]` : 'score-partwise > part'
    const parts = Array.from(doc.querySelectorAll(selector))

    const voiceCounts: Record<string, Record<number, number>> = {}

    parts.forEach(p => {
      const pId = p.getAttribute('id') || 'P1'
      voiceCounts[pId] = voiceCounts[pId] || {}
      p.querySelectorAll('measure note').forEach(n => {
        const vEl = n.querySelector('voice')
        const vId = parseInt(vEl?.textContent?.trim() || '1', 10) || 1
        voiceCounts[pId][vId] = (voiceCounts[pId][vId] || 0) + 1
      })
    })

    const results: Array<{ partId: string; voiceId: number; noteCount: number }> = []
    Object.entries(voiceCounts).forEach(([pId, vMap]) => {
      Object.entries(vMap).forEach(([vIdStr, count]) => {
        results.push({
          partId: pId,
          voiceId: parseInt(vIdStr, 10),
          noteCount: count
        })
      })
    })

    return results
  }

  const setTimeSignature = (measureNum: number, beats: number, beatType: number) => {
    const doc = getDoc()
    const measure = getMeasureElement(doc, measureNum)
    if (!measure) return null

    let attr = measure.querySelector('attributes')
    if (!attr) {
      attr = doc.createElement('attributes')
      measure.insertBefore(attr, measure.firstChild)
    }

    let timeEl = attr.querySelector('time')
    if (!timeEl) {
      timeEl = doc.createElement('time')
      attr.appendChild(timeEl)
    }

    let beatsEl = timeEl.querySelector('beats')
    if (!beatsEl) {
      beatsEl = doc.createElement('beats')
      timeEl.appendChild(beatsEl)
    }
    beatsEl.textContent = String(beats)

    let beatTypeEl = timeEl.querySelector('beat-type')
    if (!beatTypeEl) {
      beatTypeEl = doc.createElement('beat-type')
      timeEl.appendChild(beatTypeEl)
    }
    beatTypeEl.textContent = String(beatType)

    const xml = serializeDoc(doc)
    pushState(xml)
    return xml
  }

  const setKeySignature = (measureNum: number, fifths: number) => {
    const doc = getDoc()
    const measure = getMeasureElement(doc, measureNum)
    if (!measure) return null

    let attr = measure.querySelector('attributes')
    if (!attr) {
      attr = doc.createElement('attributes')
      measure.insertBefore(attr, measure.firstChild)
    }

    let keyEl = attr.querySelector('key')
    if (!keyEl) {
      keyEl = doc.createElement('key')
      attr.appendChild(keyEl)
    }

    let fifthsEl = keyEl.querySelector('fifths')
    if (!fifthsEl) {
      fifthsEl = doc.createElement('fifths')
      keyEl.appendChild(fifthsEl)
    }
    fifthsEl.textContent = String(fifths)

    const xml = serializeDoc(doc)
    pushState(xml)
    return xml
  }

  const setClef = (measureNum: number, sign: string, line: number = 2, staffIndex: number = 0) => {
    const doc = getDoc()
    const info = resolveStaffTarget(doc, measureNum, staffIndex)
    const measure = info.measure
    if (!measure) return null

    let attr = measure.querySelector('attributes')
    if (!attr) {
      attr = doc.createElement('attributes')
      measure.insertBefore(attr, measure.firstChild)
    }

    let clefEl: Element | null = null
    if (info.stavesInPart > 1) {
      clefEl = attr.querySelector(`clef[number="${info.staffInPart}"]`)
      if (!clefEl) {
        clefEl = doc.createElement('clef')
        clefEl.setAttribute('number', String(info.staffInPart))
        attr.appendChild(clefEl)
      }
    } else {
      clefEl = attr.querySelector('clef')
      if (!clefEl) {
        clefEl = doc.createElement('clef')
        attr.appendChild(clefEl)
      }
    }

    let signEl = clefEl.querySelector('sign')
    if (!signEl) {
      signEl = doc.createElement('sign')
      clefEl.appendChild(signEl)
    }
    signEl.textContent = sign

    let lineEl: Element | null = clefEl.querySelector('line')
    if (!lineEl) {
      lineEl = doc.createElement('line')
      clefEl.appendChild(lineEl)
    }
    lineEl.textContent = String(line)

    const xml = serializeDoc(doc)
    pushState(xml)
    return xml
  }

  const setNoteLyrics = (
    measureNum: number,
    noteIndex: number,
    lyrics: string,
    staffIndex: number = 0,
    headIndex: number = 0
  ): { xml: string; nextMeasureNum: number; nextNoteIndex: number } | null => {
    const doc = getDoc()
    const { target, info, actualOnsetIndex } = resolveTargetNote(doc, measureNum, noteIndex, staffIndex, headIndex)
    if (!target) return null

    let lyricNode = target.querySelector('lyric')
    if (lyrics.trim()) {
      if (!lyricNode) {
        lyricNode = doc.createElement('lyric')
        target.appendChild(lyricNode)
      }
      let textNode: Element | null = lyricNode.querySelector('text')
      if (!textNode) {
        textNode = doc.createElement('text')
        lyricNode.appendChild(textNode)
      }
      textNode.textContent = lyrics.trim()
    } else if (lyricNode) {
      lyricNode.remove()
    }

    const totalMeasures = getTotalMeasures(doc)
    let nextNoteIndex = actualOnsetIndex + 1
    let nextMeasureNum = measureNum

    if (nextNoteIndex >= info.onsets.length) {
      if (measureNum < totalMeasures) {
        nextMeasureNum = measureNum + 1
        nextNoteIndex = 0
      } else {
        nextNoteIndex = Math.max(0, info.onsets.length - 1)
      }
    }

    const xml = serializeDoc(doc)
    pushState(xml)
    return { xml, nextMeasureNum, nextNoteIndex }
  }

  const setNoteDynamics = (
    measureNum: number,
    noteIndex: number,
    dynamicType: string,
    staffIndex: number = 0,
    headIndex: number = 0
  ): { xml: string; nextMeasureNum: number; nextNoteIndex: number } | null => {
    const doc = getDoc()
    const { target, info, actualOnsetIndex } = resolveTargetNote(doc, measureNum, noteIndex, staffIndex, headIndex)
    if (!target) return null

    let notationsEl = target.querySelector('notations')
    if (!notationsEl) {
      notationsEl = doc.createElement('notations')
      target.appendChild(notationsEl)
    }

    let dynEl = notationsEl.querySelector('dynamics')
    const cleanDyn = dynamicType.trim().toLowerCase()

    if (cleanDyn) {
      if (!dynEl) {
        dynEl = doc.createElement('dynamics')
        notationsEl.appendChild(dynEl)
      } else {
        dynEl.innerHTML = ''
      }
      const markEl = doc.createElement(cleanDyn)
      dynEl.appendChild(markEl)
    } else if (dynEl) {
      dynEl.remove()
      if (notationsEl.children.length === 0) {
        notationsEl.remove()
      }
    }

    const totalMeasures = getTotalMeasures(doc)
    let nextNoteIndex = actualOnsetIndex + 1
    let nextMeasureNum = measureNum

    if (nextNoteIndex >= info.onsets.length) {
      if (measureNum < totalMeasures) {
        nextMeasureNum = measureNum + 1
        nextNoteIndex = 0
      } else {
        nextNoteIndex = Math.max(0, info.onsets.length - 1)
      }
    }

    const xml = serializeDoc(doc)
    pushState(xml)
    return { xml, nextMeasureNum, nextNoteIndex }
  }

  const splitRestAndInsertNote = (
    measureNum: number,
    noteIndex: number,
    noteType: string,
    isDotted: boolean = false,
    step: string = 'C',
    octave: number = 4,
    alter: number = 0,
    staffIndex: number = 0
  ): MutationResult | null => {
    const doc = getDoc()
    const info = resolveStaffTarget(doc, measureNum, staffIndex)
    if (!info.measure) return null

    const totalMeasures = getTotalMeasures(doc)
    let target: Element | null = null
    let actualIndex = noteIndex

    if (noteIndex >= 0 && noteIndex < info.onsets.length) {
      target = info.onsets[noteIndex][0] || null
    }

    if (!target) {
      const firstRest = info.notes.find((n) => n.querySelector('rest') !== null)
      if (firstRest) {
        target = firstRest
        actualIndex = Math.max(0, info.onsets.findIndex(o => o.includes(firstRest)))
      } else {
        target = info.notes[info.notes.length - 1] || null
        actualIndex = Math.max(0, info.onsets.length - 1)
      }
    }
    if (!target) return null

    const divisions = parseInt(doc.querySelector('attributes > divisions')?.textContent || '4', 10) || 4
    let noteDivs = (NOTE_TYPE_DIVISIONS[noteType] || 4) / 4 * divisions
    if (isDotted) noteDivs = Math.round(noteDivs * 1.5)
    noteDivs = Math.max(1, Math.round(noteDivs))

    const isTargetRest = target.querySelector('rest') !== null
    const targetDur = parseInt(target.querySelector('duration')?.textContent || '0', 10) || noteDivs

    if (isTargetRest) {
      target.querySelector('rest')?.remove()
      let pitchNode = target.querySelector('pitch')
      if (!pitchNode) {
        pitchNode = doc.createElement('pitch')
        target.insertBefore(pitchNode, target.firstChild)
      }
      pitchNode.innerHTML = ''

      const stepNode = doc.createElement('step')
      stepNode.textContent = step
      const octNode = doc.createElement('octave')
      octNode.textContent = String(octave)
      pitchNode.appendChild(stepNode)
      pitchNode.appendChild(octNode)

      if (alter !== 0) {
        const altNode = doc.createElement('alter')
        altNode.textContent = String(alter)
        pitchNode.appendChild(altNode)
      }

      let typeNode = target.querySelector('type')
      if (!typeNode) {
        typeNode = doc.createElement('type')
        target.appendChild(typeNode)
      }
      typeNode.textContent = noteType

      const dotNode = target.querySelector('dot')
      if (isDotted && !dotNode) {
        target.appendChild(doc.createElement('dot'))
      } else if (!isDotted && dotNode) {
        dotNode.remove()
      }

      let durNode = target.querySelector('duration')
      if (!durNode) {
        durNode = doc.createElement('duration')
        target.appendChild(durNode)
      }
      durNode.textContent = String(noteDivs)

      if (info.stavesInPart > 1 && !target.querySelector('staff')) {
        const staffNode = doc.createElement('staff')
        staffNode.textContent = String(info.staffInPart)
        target.appendChild(staffNode)
      }

      const remainingDivs = targetDur - noteDivs
      let nextNoteIndex = actualIndex + 1
      let nextMeasureNum = measureNum
      let measureCompleted = false

      if (remainingDivs > 0) {
        const restNode = createRestNode(doc, remainingDivs, divisions)
        if (info.stavesInPart > 1) {
          const staffNode = doc.createElement('staff')
          staffNode.textContent = String(info.staffInPart)
          restNode.appendChild(staffNode)
        }
        const voiceEl = target.querySelector('voice')
        if (voiceEl) {
          const vNode = doc.createElement('voice')
          vNode.textContent = voiceEl.textContent || '1'
          restNode.insertBefore(vNode, restNode.querySelector('type'))
        }
        if (target.nextSibling) {
          info.measure.insertBefore(restNode, target.nextSibling)
        } else {
          info.measure.appendChild(restNode)
        }
      } else {
        const updatedStaffNotes = resolveStaffTarget(doc, measureNum, staffIndex)
        if (nextNoteIndex >= updatedStaffNotes.onsets.length) {
          measureCompleted = true
          if (measureNum < totalMeasures) {
            nextMeasureNum = measureNum + 1
            nextNoteIndex = 0
          } else {
            nextNoteIndex = Math.max(0, updatedStaffNotes.onsets.length - 1)
          }
        }
      }

      const xml = serializeDoc(doc)
      pushState(xml)
      return {
        xml,
        nextMeasureNum,
        nextNoteIndex,
        measureCompleted
      }
    } else {
      setNoteType(measureNum, actualIndex, noteType, isDotted, false, staffIndex, 0)
      const xml = workingXml.value
      const updatedStaffNotes = resolveStaffTarget(doc, measureNum, staffIndex)
      let nextNoteIndex = actualIndex + 1
      let nextMeasureNum = measureNum
      let measureCompleted = false

      if (nextNoteIndex >= updatedStaffNotes.onsets.length) {
        measureCompleted = true
        if (measureNum < totalMeasures) {
          nextMeasureNum = measureNum + 1
          nextNoteIndex = 0
        } else {
          nextNoteIndex = Math.max(0, updatedStaffNotes.onsets.length - 1)
        }
      }

      return {
        xml,
        nextMeasureNum,
        nextNoteIndex,
        measureCompleted
      }
    }
  }

  const applyDroppedTool = (
    measureNum: number,
    noteIndex: number,
    tool: { type: string; value?: any },
    staffIndex: number = 0,
    headIndex: number = 0
  ): MutationResult | null => {
    if (tool.type === 'duration') {
      const droppedType = tool.value || 'quarter'
      const defaultStep = 'C'
      const defaultOct = staffIndex === 1 ? 3 : 4
      return splitRestAndInsertNote(measureNum, noteIndex, droppedType, false, defaultStep, defaultOct, 0, staffIndex)
    }

    if (tool.type === 'accidental') {
      const xml = toggleAccidental(measureNum, noteIndex, tool.value, staffIndex, headIndex)
      if (!xml) return null
      return {
        xml,
        nextMeasureNum: measureNum,
        nextNoteIndex: noteIndex,
        measureCompleted: false
      }
    }

    if (tool.type === 'dot') {
      const xml = toggleDot(measureNum, noteIndex, staffIndex, headIndex)
      if (!xml) return null
      return {
        xml,
        nextMeasureNum: measureNum,
        nextNoteIndex: noteIndex,
        measureCompleted: false
      }
    }

    if (tool.type === 'tie') {
      const xml = toggleTie(measureNum, noteIndex, staffIndex, headIndex)
      if (!xml) return null
      return {
        xml,
        nextMeasureNum: measureNum,
        nextNoteIndex: noteIndex,
        measureCompleted: false
      }
    }

    if (tool.type === 'rest') {
      const restType = tool.value
      if (restType) {
        setNoteType(measureNum, noteIndex, restType, false, true, staffIndex, headIndex)
        const xml = workingXml.value
        return {
          xml,
          nextMeasureNum: measureNum,
          nextNoteIndex: noteIndex,
          measureCompleted: false
        }
      }
      const xml = toggleRest(measureNum, noteIndex, staffIndex, headIndex)
      if (!xml) return null
      return {
        xml,
        nextMeasureNum: measureNum,
        nextNoteIndex: noteIndex,
        measureCompleted: false
      }
    }

    if (tool.type === 'dynamic') {
      const res = setNoteDynamics(measureNum, noteIndex, tool.value || 'f', staffIndex, headIndex)
      if (!res) return null
      return {
        xml: res.xml,
        nextMeasureNum: res.nextMeasureNum,
        nextNoteIndex: res.nextNoteIndex,
        measureCompleted: false
      }
    }

    return null
  }

  const padMeasuresTo = (targetCount: number) => {
    const doc = getDoc()
    const part = doc.querySelector('part')
    if (!part) return null

    let currentMeasures = Array.from(part.querySelectorAll('measure'))
    if (currentMeasures.length >= targetCount) return null

    const divisions = parseInt(doc.querySelector('attributes > divisions')?.textContent || '4', 10) || 4

    const stavesEl = part.querySelector('attributes > staves')
    const stavesCount = stavesEl ? parseInt(stavesEl.textContent?.trim() || '1', 10) : 1

    while (currentMeasures.length < targetCount) {
      const nextNum = currentMeasures.length + 1
      const attr = getMeasureAttributes(currentMeasures.length, 0, doc)
      const measureDuration = Math.round(attr.beats * (divisions * 4 / attr.beatType))

      const newMeasure = doc.createElement('measure')
      newMeasure.setAttribute('number', String(nextNum))
      const noteTypeStr = attr.beatType === 4 && attr.beats === 4 ? 'whole' : 'quarter'

      if (stavesCount > 1) {
        for (let s = 1; s <= stavesCount; s++) {
          if (s > 1) {
            const backup = doc.createElement('backup')
            const dur = doc.createElement('duration')
            dur.textContent = String(measureDuration)
            backup.appendChild(dur)
            newMeasure.appendChild(backup)
          }
          const note = doc.createElement('note')
          const rest = doc.createElement('rest')
          const dur = doc.createElement('duration')
          dur.textContent = String(measureDuration)
          const type = doc.createElement('type')
          type.textContent = noteTypeStr
          const voice = doc.createElement('voice')
          voice.textContent = String(s)
          const staff = doc.createElement('staff')
          staff.textContent = String(s)

          note.appendChild(rest)
          note.appendChild(dur)
          note.appendChild(type)
          note.appendChild(voice)
          note.appendChild(staff)
          newMeasure.appendChild(note)
        }
      } else {
        const newNote = doc.createElement('note')
        const rest = doc.createElement('rest')
        const dur = doc.createElement('duration')
        dur.textContent = String(measureDuration)
        const type = doc.createElement('type')
        type.textContent = noteTypeStr

        newNote.appendChild(rest)
        newNote.appendChild(dur)
        newNote.appendChild(type)
        newMeasure.appendChild(newNote)
      }

      part.appendChild(newMeasure)
      currentMeasures = Array.from(part.querySelectorAll('measure'))
    }

    const xml = serializeDoc(doc)
    pushState(xml)
    return xml
  }

  const fillLine = (measuresPerLine = 4) => {
    const total = getTotalMeasures()
    const target = Math.ceil(total / measuresPerLine) * measuresPerLine
    const finalTarget = target === total ? total + measuresPerLine : target
    return padMeasuresTo(finalTarget)
  }

  const fillPage = (measuresPerPage = 16) => {
    const total = getTotalMeasures()
    let target = measuresPerPage
    if (total >= measuresPerPage) {
      target = Math.ceil(total / measuresPerPage) * measuresPerPage
      if (target === total) target += measuresPerPage
    }
    return padMeasuresTo(target)
  }

  const getScoreParts = (): Array<{ id: string; name: string; tag: string; staves: number }> => {
    const parser = new DOMParser()
    const doc = parser.parseFromString(workingXml.value, 'application/xml')
    const scoreParts = Array.from(doc.querySelectorAll('score-partwise > part-list > score-part')) as Element[]
    return scoreParts.map((sp, idx) => {
      const id = sp.getAttribute('id') || `P${idx + 1}`
      const name = sp.querySelector('part-name')?.textContent?.trim() || `Part ${idx + 1}`
      const abbr = sp.querySelector('part-abbreviation')?.textContent?.trim() || ''
      const partElem = doc.querySelector(`part[id="${id}"]`)
      const stavesEl = partElem?.querySelector('attributes > staves')
      const staves = stavesEl ? parseInt(stavesEl.textContent?.trim() || '1', 10) : 1
      const autotag = resolveTrackVoiceTag(name, abbr, idx, scoreParts.length, staves)
      return {
        id,
        name: autotag.name,
        tag: autotag.tag,
        staves,
      }
    })
  }

  return {
    workingXml,
    savedXml,
    isDirty,
    markSaved,
    resetToSaved,
    canUndo,
    canRedo,
    pushState,
    undo,
    redo,
    getTotalMeasures,
    getMeasureAttributes,
    getNotesInMeasure,
    getScoreParts,
    setNotePitch,
    setNoteType,
    toggleAccidental,
    toggleDot,
    toggleRest,
    toggleTie,
    transposeNote,
    shiftNoteDiatonic,
    addMeasure,
    deleteMeasure,
    deletePart,
    deleteVoice,
    getPartVoices,
    setTimeSignature,
    setKeySignature,
    setClef,
    setNoteLyrics,
    setNoteDynamics,
    applyDroppedTool,
    splitRestAndInsertNote,
    padMeasuresTo,
    fillLine,
    fillPage
  }
}
