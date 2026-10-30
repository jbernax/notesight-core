/**
 * Web MIDI Integration Service for NoteSight
 * Provides bi-directional Web MIDI connectivity:
 * 1. Input: Connect external MIDI keyboards to enter notes into the active score measure.
 * 2. Output: Route score playback to external MIDI hardware synthesizers or DAWs.
 */

import { freqToMidi } from './sampler'
import type { PolyphonicNote } from './synth'

export interface MidiPortInfo {
  id: string
  name: string
  manufacturer?: string
  state: string
}

export interface MidiNoteEvent {
  note: number
  velocity: number
  step: string
  octave: number
  alter: number
  frequency: number
  name: string
  raw: Uint8Array
}

export type MidiNoteListener = (event: MidiNoteEvent) => void

const SEMITONE_MAPPING = [
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
  { step: 'B', alter: 0 },
]

export function midiToPitch(midi: number): { step: string; octave: number; alter: number; name: string } {
  const clamped = Math.max(0, Math.min(127, Math.round(midi)))
  const semitone = ((clamped % 12) + 12) % 12
  const octave = Math.floor(clamped / 12) - 1
  const meta = SEMITONE_MAPPING[semitone]
  const accidental = meta.alter === 1 ? '♯' : ''
  return {
    step: meta.step,
    octave,
    alter: meta.alter,
    name: `${meta.step}${accidental}${octave}`,
  }
}

export function pitchToMidi(step: string, octave: number, alter: number = 0): number {
  const STEP_OFFSETS: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }
  const offset = STEP_OFFSETS[step.toUpperCase()] ?? 0
  return (octave + 1) * 12 + offset + alter
}

// Minimal DOM Web MIDI interfaces for TypeScript portability
interface MidiPortLike {
  id: string
  name?: string
  manufacturer?: string
  state?: string
  open?: () => Promise<MidiPortLike>
  close?: () => Promise<MidiPortLike>
}

interface MidiInputLike extends MidiPortLike {
  onmidimessage?: ((e: { data: Uint8Array }) => void) | null
}

interface MidiOutputLike extends MidiPortLike {
  send: (data: number[] | Uint8Array, timestamp?: number) => void
  clear?: () => void
}

interface MidiAccessLike {
  inputs: {
    values: () => IterableIterator<MidiInputLike>
    get: (id: string) => MidiInputLike | undefined
  }
  outputs: {
    values: () => IterableIterator<MidiOutputLike>
    get: (id: string) => MidiOutputLike | undefined
  }
  onstatechange?: ((e: any) => void) | null
}

export class MidiService {
  private midiAccess: MidiAccessLike | null = null
  private activeInput: MidiInputLike | null = null
  private activeOutput: MidiOutputLike | null = null

  private noteOnListeners: Set<MidiNoteListener> = new Set()
  private noteOffListeners: Set<MidiNoteListener> = new Set()
  private stateChangeListeners: Set<() => void> = new Set()

  private initialized = false
  private error: string | null = null
  private outputRoutingEnabled = true
  private recentSentNotes: Map<number, number> = new Map()

  public get isSupported(): boolean {
    return typeof navigator !== 'undefined' && 'requestMIDIAccess' in navigator
  }

  public get isConnected(): boolean {
    return this.midiAccess !== null
  }

  public get isOutputEnabled(): boolean {
    return this.outputRoutingEnabled && this.activeOutput !== null
  }

  public setOutputRoutingEnabled(enabled: boolean) {
    this.outputRoutingEnabled = enabled
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem('notesight_midi_output_enabled', enabled ? 'true' : 'false')
    }
    this.notifyStateChange()
  }

  public get errorMessage(): string | null {
    return this.error
  }

  public get selectedInputId(): string | null {
    return this.activeInput?.id || null
  }

  public get selectedOutputId(): string | null {
    return this.activeOutput?.id || null
  }

  /**
   * Request Web MIDI access from the browser.
   */
  public async init(): Promise<boolean> {
    if (!this.isSupported) {
      this.error = 'Web MIDI is not supported in this browser'
      return false
    }

    if (this.initialized && this.midiAccess) {
      return true
    }

    try {
      const nav = navigator as any
      const access: MidiAccessLike = await nav.requestMIDIAccess({ sysex: false })
      this.midiAccess = access
      this.initialized = true
      this.error = null

      // Restore user output routing preference if previously saved
      if (typeof localStorage !== 'undefined') {
        const savedRouting = localStorage.getItem('notesight_midi_output_enabled')
        if (savedRouting !== null) {
          this.outputRoutingEnabled = savedRouting === 'true'
        }
      }

      access.onstatechange = () => {
        this.notifyStateChange()
      }

      // Auto-select first available input / output or restore from storage
      this.autoSelectPorts()
      return true
    } catch (err: any) {
      this.error = err?.message || 'Access to MIDI devices was denied'
      console.warn('Web MIDI permission request failed:', err)
      return false
    }
  }

  private autoSelectPorts() {
    if (!this.midiAccess) return

    const savedInput = typeof localStorage !== 'undefined' ? localStorage.getItem('notesight_midi_input') : null
    const savedOutput = typeof localStorage !== 'undefined' ? localStorage.getItem('notesight_midi_output') : null

    const inputs = this.getInputs()
    if (savedInput && inputs.some((i) => i.id === savedInput)) {
      this.selectInput(savedInput)
    } else if (inputs.length > 0) {
      this.selectInput(inputs[0].id)
    }

    const outputs = this.getOutputs()
    if (savedOutput && outputs.some((o) => o.id === savedOutput)) {
      this.selectOutput(savedOutput)
    } else if (outputs.length > 0) {
      this.selectOutput(outputs[0].id)
    }
  }

  /**
   * Discovered MIDI Input devices (Keyboards, Pad Controllers).
   */
  public getInputs(): MidiPortInfo[] {
    if (!this.midiAccess) return []
    const list: MidiPortInfo[] = []
    const iterator = this.midiAccess.inputs.values()
    for (const port of iterator) {
      list.push({
        id: port.id,
        name: port.name || `MIDI Input ${port.id}`,
        manufacturer: port.manufacturer,
        state: port.state || 'connected',
      })
    }
    return list
  }

  /**
   * Discovered MIDI Output devices (Hardware Synths, DAWs, Virtual Ports).
   */
  public getOutputs(): MidiPortInfo[] {
    if (!this.midiAccess) return []
    const list: MidiPortInfo[] = []
    const iterator = this.midiAccess.outputs.values()
    for (const port of iterator) {
      list.push({
        id: port.id,
        name: port.name || `MIDI Output ${port.id}`,
        manufacturer: port.manufacturer,
        state: port.state || 'connected',
      })
    }
    return list
  }

  public selectInput(id: string | null) {
    if (this.activeInput) {
      this.activeInput.onmidimessage = null
      this.activeInput = null
    }

    if (!id || !this.midiAccess) {
      if (typeof localStorage !== 'undefined') localStorage.removeItem('notesight_midi_input')
      this.notifyStateChange()
      return
    }

    const port = this.midiAccess.inputs.get(id)
    if (port) {
      this.activeInput = port
      port.onmidimessage = (msg) => this.handleMidiMessage(msg.data)
      if (typeof localStorage !== 'undefined') localStorage.setItem('notesight_midi_input', id)
    }
    this.notifyStateChange()
  }

  public selectOutput(id: string | null) {
    if (!id || !this.midiAccess) {
      this.activeOutput = null
      if (typeof localStorage !== 'undefined') localStorage.removeItem('notesight_midi_output')
      this.notifyStateChange()
      return
    }

    const port = this.midiAccess.outputs.get(id)
    if (port) {
      this.activeOutput = port
      if (typeof localStorage !== 'undefined') localStorage.setItem('notesight_midi_output', id)
    }
    this.notifyStateChange()
  }

  private handleMidiMessage(data: Uint8Array) {
    if (!data || data.length < 3) return
    const status = data[0] & 0xf0
    const note = data[1]
    const rawVelocity = data[2]

    // Suppress loopback echoes from recent score playback output routing
    const now = typeof performance !== 'undefined' ? performance.now() : Date.now()
    const echoExpiry = this.recentSentNotes.get(note)
    if (echoExpiry) {
      if (now < echoExpiry) {
        // Echoed loopback note detected - ignore to protect score from self-mutation
        return
      } else {
        this.recentSentNotes.delete(note)
      }
    }

    // Note On (0x90 with velocity > 0)
    if (status === 0x90 && rawVelocity > 0) {
      const pitch = midiToPitch(note)
      const freq = 440 * Math.pow(2, (note - 69) / 12)
      const event: MidiNoteEvent = {
        note,
        velocity: rawVelocity / 127,
        step: pitch.step,
        octave: pitch.octave,
        alter: pitch.alter,
        frequency: freq,
        name: pitch.name,
        raw: data,
      }
      this.noteOnListeners.forEach((fn) => {
        try {
          fn(event)
        } catch (e) {
          console.warn('Error in MIDI note on listener:', e)
        }
      })
    }
    // Note Off (0x80 or 0x90 with velocity 0)
    else if (status === 0x80 || (status === 0x90 && rawVelocity === 0)) {
      const pitch = midiToPitch(note)
      const freq = 440 * Math.pow(2, (note - 69) / 12)
      const event: MidiNoteEvent = {
        note,
        velocity: 0,
        step: pitch.step,
        octave: pitch.octave,
        alter: pitch.alter,
        frequency: freq,
        name: pitch.name,
        raw: data,
      }
      this.noteOffListeners.forEach((fn) => {
        try {
          fn(event)
        } catch (e) {
          console.warn('Error in MIDI note off listener:', e)
        }
      })
    }
  }

  /**
   * Route score playback notes to connected external MIDI hardware.
   */
  public routeScoreNotes(notes: PolyphonicNote[], offsetSec: number = 0) {
    if (!this.outputRoutingEnabled || !this.activeOutput || notes.length === 0) return

    const now = typeof performance !== 'undefined' ? performance.now() : Date.now()
    const targetTimestamp = now + Math.max(0, offsetSec * 1000)

    for (const n of notes) {
      const midiNote = freqToMidi(n.frequency)
      const velocity = Math.max(1, Math.min(127, Math.round((n.velocity ?? 0.8) * 127)))
      const durationMs = Math.max(50, Math.round(n.durationSec * 1000))

      // Register note in loopback suppression window (playback offset + note duration + 350ms margin)
      this.recentSentNotes.set(midiNote, now + (offsetSec * 1000) + durationMs + 350)

      try {
        // Send Note On
        this.activeOutput.send([0x90, midiNote, velocity], targetTimestamp)
        // Schedule Note Off
        this.activeOutput.send([0x80, midiNote, 0], targetTimestamp + durationMs)
      } catch (err) {
        console.warn('Failed to send MIDI note to output:', err)
      }
    }
  }

  public sendNoteOn(note: number, velocity: number = 0.8, channel: number = 0) {
    if (!this.activeOutput) return
    const ch = Math.max(0, Math.min(15, channel))
    const vel = Math.max(1, Math.min(127, Math.round(velocity * 127)))
    try {
      this.activeOutput.send([0x90 | ch, note, vel])
    } catch (err) {
      console.warn('MIDI output sendNoteOn error:', err)
    }
  }

  public sendNoteOff(note: number, channel: number = 0) {
    if (!this.activeOutput) return
    const ch = Math.max(0, Math.min(15, channel))
    try {
      this.activeOutput.send([0x80 | ch, note, 0])
    } catch (err) {
      console.warn('MIDI output sendNoteOff error:', err)
    }
  }

  public sendAllNotesOff(channel: number = 0) {
    if (!this.activeOutput) return
    const ch = Math.max(0, Math.min(15, channel))
    try {
      // CC 123: All Notes Off
      this.activeOutput.send([0xb0 | ch, 123, 0])
      // CC 120: All Sound Off
      this.activeOutput.send([0xb0 | ch, 120, 0])
    } catch (err) {
      console.warn('MIDI output sendAllNotesOff error:', err)
    }
  }

  public onNoteOn(listener: MidiNoteListener): () => void {
    this.noteOnListeners.add(listener)
    return () => this.noteOnListeners.delete(listener)
  }

  public onNoteOff(listener: MidiNoteListener): () => void {
    this.noteOffListeners.add(listener)
    return () => this.noteOffListeners.delete(listener)
  }

  public onStateChange(listener: () => void): () => void {
    this.stateChangeListeners.add(listener)
    return () => this.stateChangeListeners.delete(listener)
  }

  private notifyStateChange() {
    this.stateChangeListeners.forEach((fn) => {
      try {
        fn()
      } catch (e) {
        console.warn('Error in state change listener:', e)
      }
    })
  }
}

export const midiService = new MidiService()
