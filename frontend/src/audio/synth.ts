/**
 * Web Audio Polyphonic Synthesizer
 * Provides zero-dependency, zero-latency musical synthesis for score playback
 * and offline audio rendering.
 */

export type InstrumentType =
  | 'piano'
  | 'choir'
  | 'guitar'
  | 'strings'
  | 'flute'
  | 'brass'
  | 'rhodes'
  | 'marimba'
  | 'synth'

export interface InstrumentOption {
  id: InstrumentType
  name: string
  description: string
  category: 'soundfont' | 'synth'
}

export const INSTRUMENT_OPTIONS: InstrumentOption[] = [
  { id: 'piano', name: 'Grand Piano', description: 'Harmonic acoustic grand piano with warm resonance', category: 'soundfont' },
  { id: 'choir', name: 'Choir Ensemble', description: 'Warm sustained choral vocal ensemble with natural formants', category: 'soundfont' },
  { id: 'guitar', name: 'Acoustic Guitar', description: 'Nylon string acoustic guitar with expressive pluck', category: 'soundfont' },
  { id: 'strings', name: 'Strings Ensemble', description: 'Sustained orchestral chamber strings', category: 'soundfont' },
  { id: 'flute', name: 'Concert Flute', description: 'Airy woodwind flute with natural breath chiff', category: 'soundfont' },
  { id: 'brass', name: 'Brass Section', description: 'Majestic orchestral brass horns and trumpets', category: 'soundfont' },
  { id: 'rhodes', name: 'Electric Piano', description: 'Mellow bell chime with subtle warmth', category: 'synth' },
  { id: 'marimba', name: 'Marimba', description: 'Crisp percussive wooden bars', category: 'synth' },
  { id: 'synth', name: '8-Bit Synth', description: 'Classic retro synth lead', category: 'synth' },
]

import { SampleBank, freqToMidi, INSTRUMENT_PROFILES } from './sampler'

export interface NoteVoice {
  oscillators: OscillatorNode[]
  bufferSources?: AudioBufferSourceNode[]
  gainNode: GainNode
  filterNode?: BiquadFilterNode
  stopTime: number
}

export interface PolyphonicNote {
  frequency: number
  durationSec: number
  velocity?: number
  instrument?: InstrumentType
  volumeMultiplier?: number
  destinationNode?: AudioNode
  isLegato?: boolean
}

export class WebAudioSynthesizer {
  private ctx: AudioContext | null = null
  private masterGain: GainNode | null = null
  private activeVoices: Set<NoteVoice> = new Set()
  private readonly maxPolyphony: number = 32
  private currentInstrument: InstrumentType = 'piano'
  private volume: number = 0.8
  private isMuted: boolean = false

  /**
   * Register an active voice with voice-stealing polyphony management.
   * If concurrent voices exceed maxPolyphony, the voice with the earliest stopTime
   * is smoothly retired with an anti-click micro-fade.
   */
  private registerVoice(voice: NoteVoice) {
    if (this.activeVoices.size >= this.maxPolyphony) {
      let oldestVoice: NoteVoice | null = null
      let earliestStop = Infinity
      for (const v of this.activeVoices) {
        if (v.stopTime < earliestStop) {
          earliestStop = v.stopTime
          oldestVoice = v
        }
      }
      if (oldestVoice) {
        this.retireVoice(oldestVoice)
      }
    }
    this.activeVoices.add(voice)
  }

  private retireVoice(voice: NoteVoice) {
    if (!this.ctx) return
    const now = this.ctx.currentTime
    try {
      voice.gainNode.gain.cancelScheduledValues(now)
      const cur = Math.max(0.0001, voice.gainNode.gain.value)
      voice.gainNode.gain.setValueAtTime(cur, now)
      voice.gainNode.gain.linearRampToValueAtTime(0.0001, now + 0.008)
      setTimeout(() => {
        voice.oscillators.forEach((osc) => {
          try { osc.stop(); osc.disconnect() } catch {}
        })
        voice.bufferSources?.forEach((src) => {
          try { src.stop(); src.disconnect() } catch {}
        })
        voice.filterNode?.disconnect()
        voice.gainNode.disconnect()
      }, 15)
    } catch {}
    this.activeVoices.delete(voice)
  }

  constructor() {
    // AudioContext will be initialized on first user interaction
  }

  /**
   * Ensure AudioContext is initialized and running.
   */
  public async ensureContext(): Promise<AudioContext> {
    if (!this.ctx) {
      const AudioCtxClass = (typeof window !== 'undefined' ? (window.AudioContext || (window as any).webkitAudioContext) : null) || (typeof AudioContext !== 'undefined' ? AudioContext : null)
      if (!AudioCtxClass) {
        throw new Error('AudioContext is not supported in this environment')
      }
      this.ctx = new AudioCtxClass()
      this.masterGain = this.ctx.createGain()
      this.masterGain.gain.setValueAtTime(this.isMuted ? 0 : this.volume, this.ctx.currentTime)
      this.masterGain.connect(this.ctx.destination)
    }

    if (this.ctx && this.ctx.state === 'suspended') {
      try {
        await this.ctx.resume()
      } catch {}
    }

    return this.ctx
  }

  public get audioContext(): AudioContext | null {
    return this.ctx
  }

  public getMasterGain(): GainNode | null {
    return this.masterGain
  }

  public setInstrument(type: InstrumentType) {
    this.currentInstrument = type
  }

  public getInstrument(): InstrumentType {
    return this.currentInstrument
  }

  public setVolume(volPercent: number) {
    this.volume = Math.max(0, Math.min(1, volPercent / 100))
    if (this.masterGain && this.ctx) {
      const targetGain = this.isMuted ? 0 : this.volume
      this.masterGain.gain.setTargetAtTime(targetGain, this.ctx.currentTime, 0.02)
    }
  }

  public setMuted(muted: boolean) {
    this.isMuted = muted
    if (this.masterGain && this.ctx) {
      const targetGain = this.isMuted ? 0 : this.volume
      this.masterGain.gain.setTargetAtTime(targetGain, this.ctx.currentTime, 0.02)
    }
  }

  /**
   * Play a single pitch at frequency (Hz) for a duration in seconds,
   * optionally specifying a distinct instrument and volume multiplier.
   */
  public async playNote(
    frequency: number,
    durationSec: number,
    velocity: number = 0.8,
    startTimeOffsetSec: number = 0,
    instrument?: InstrumentType,
    volumeMultiplier: number = 1.0,
    destinationNode?: AudioNode,
    isLegato: boolean = false
  ): Promise<void> {
    if (!frequency || frequency <= 0 || isNaN(frequency)) return

    const ctx = await this.ensureContext()
    const targetDest = destinationNode || this.masterGain
    if (!targetDest) return

    const now = ctx.currentTime + Math.max(0, startTimeOffsetSec)
    const effectiveDuration = Math.max(0.08, durationSec)
    const effectiveVelocity = Math.max(0, Math.min(1.2, velocity * volumeMultiplier))
    const inst = instrument || this.currentInstrument

    this.renderNoteToContext(ctx, frequency, effectiveDuration, effectiveVelocity, now, inst, targetDest, isLegato)
  }

  /**
   * Play multiple simultaneous notes with individual instruments and volume settings.
   */
  public async playPolyphonicNotes(
    notes: PolyphonicNote[],
    startTimeOffsetSec: number = 0
  ): Promise<void> {
    if (!notes || notes.length === 0) return

    const ctx = await this.ensureContext()
    if (!this.masterGain) return

    const now = ctx.currentTime + Math.max(0, startTimeOffsetSec)

    for (const n of notes) {
      if (!n.frequency || n.frequency <= 0 || isNaN(n.frequency)) continue
      const effectiveDuration = Math.max(0.08, n.durationSec)
      const inst = n.instrument || this.currentInstrument
      const mult = typeof n.volumeMultiplier === 'number' ? n.volumeMultiplier : 1.0
      const effectiveVelocity = Math.max(0, Math.min(1.2, (n.velocity ?? 0.8) * mult))
      const targetDest = n.destinationNode || this.masterGain

      this.renderNoteToContext(ctx, n.frequency, effectiveDuration, effectiveVelocity, now, inst, targetDest, !!n.isLegato)
    }
  }

  /**
   * Play multiple simultaneous notes (chords or polyphonic voices).
   */
  public async playChord(
    notes: { frequency: number; durationSec: number; velocity?: number; instrument?: InstrumentType; volumeMultiplier?: number; isLegato?: boolean }[],
    startTimeOffsetSec: number = 0
  ): Promise<void> {
    if (!notes || notes.length === 0) return
    await this.playPolyphonicNotes(notes, startTimeOffsetSec)
  }

  /**
   * Core synthesizer engine: routes to the chosen instrument synthesis method
   * on any BaseAudioContext (AudioContext or OfflineAudioContext).
   */
  public renderNoteToContext(
    ctx: BaseAudioContext,
    frequency: number,
    durationSec: number,
    velocity: number,
    startTime: number,
    instrument: InstrumentType,
    destinationNode: AudioNode,
    isLegato: boolean = false
  ): void {
    switch (instrument) {
      case 'piano':
      case 'choir':
      case 'guitar':
      case 'strings':
      case 'flute':
      case 'brass':
        this.synthSampledNote(ctx, instrument, frequency, durationSec, velocity, startTime, destinationNode, isLegato)
        break
      case 'rhodes':
        this.synthRhodesNote(ctx, frequency, durationSec, velocity, startTime, destinationNode, isLegato)
        break
      case 'marimba':
        this.synthMarimbaNote(ctx, frequency, durationSec, velocity, startTime, destinationNode)
        break
      case 'synth':
        this.synthRetroNote(ctx, frequency, durationSec, velocity, startTime, destinationNode, isLegato)
        break
      default:
        this.synthSampledNote(ctx, 'piano', frequency, durationSec, velocity, startTime, destinationNode, isLegato)
    }
  }

  /**
   * Immediately release all currently sounding notes in live playback.
   */
  public stopAll() {
    if (!this.ctx) return
    const now = this.ctx.currentTime
    for (const voice of this.activeVoices) {
      try {
        voice.gainNode.gain.cancelScheduledValues(now)
        const curVal = Math.max(0.0001, voice.gainNode.gain.value)
        voice.gainNode.gain.setValueAtTime(curVal, now)
        voice.gainNode.gain.linearRampToValueAtTime(0.0001, now + 0.015)
        setTimeout(() => {
          voice.oscillators.forEach((osc) => {
            try {
              osc.stop()
              osc.disconnect()
            } catch {}
          })
          if (voice.bufferSources) {
            voice.bufferSources.forEach((src) => {
              try {
                src.stop()
                src.disconnect()
              } catch {}
            })
          }
          if (voice.filterNode) {
            try {
              voice.filterNode.disconnect()
            } catch {}
          }
          voice.gainNode.disconnect()
        }, 30)
      } catch {}
    }
    this.activeVoices.clear()
  }

  /**
   * Synthesize natural acoustic/orchestral instruments using SampleBank AudioBuffers
   */
  private synthSampledNote(
    ctx: BaseAudioContext,
    instrument: string,
    freq: number,
    duration: number,
    velocity: number,
    startTime: number,
    destNode?: AudioNode,
    isLegato: boolean = false
  ) {
    const destination = destNode || this.masterGain
    if (!destination) return

    const midi = freqToMidi(freq)
    const bank = SampleBank.getInstance()
    let buffer: AudioBuffer | null = null
    try {
      buffer = bank.getOrCreateSample(ctx, instrument, midi)
    } catch {
      // Fallback to algorithmic oscillator
      if (instrument === 'strings') {
        this.synthStringsNote(ctx, freq, duration, velocity, startTime, destNode)
      } else {
        this.synthPianoNote(ctx, freq, duration, velocity, startTime, destNode)
      }
      return
    }

    const source = ctx.createBufferSource()
    source.buffer = buffer

    // Enable seamless loop points for sustained instruments (strings, flute, brass)
    const profile = INSTRUMENT_PROFILES[instrument]
    if (profile && profile.sustain > 0 && buffer.duration > 0.6) {
      source.loop = true
      source.loopStart = profile.loopStartSec ?? Math.max(0.1, profile.attack + profile.decay * 0.5)
      source.loopEnd = profile.loopEndSec ?? Math.min(buffer.duration - profile.release, buffer.duration - 0.1)
    }

    const noteGain = ctx.createGain()
    const peak = 0.85 * velocity
    // Micro-legato phrasing: subtle crossfade overlap and smooth attack
    const attackTime = isLegato ? 0.025 : 0.005
    const releaseTime = isLegato ? 0.18 : 0.25
    // Add micro-overlap (15ms - 25ms) so consecutive melody notes don't leave silent gaps
    const effectiveDuration = isLegato ? duration + 0.025 : duration + 0.015
    const noteEndTime = startTime + effectiveDuration

    noteGain.gain.setValueAtTime(0.0001, startTime)
    noteGain.gain.linearRampToValueAtTime(peak, startTime + attackTime)

    // Smooth ADSR envelope without step discontinuities
    if (profile && profile.sustain > 0) {
      // Sustained instruments (choir, strings, flute, brass): hold steady volume until key release
      noteGain.gain.setValueAtTime(peak * 0.95, startTime + attackTime)
      noteGain.gain.setValueAtTime(peak * 0.95, noteEndTime)
      noteGain.gain.exponentialRampToValueAtTime(0.0001, noteEndTime + releaseTime)
    } else {
      // Percussive instruments (grand piano, acoustic guitar):
      // While key is depressed (from startTime to noteEndTime), maintain clear acoustic body resonance (sustain floor),
      // then let damper drop at noteEndTime to cleanly release.
      const decayFloor = Math.max(0.08, peak * 0.72)
      noteGain.gain.exponentialRampToValueAtTime(decayFloor, noteEndTime)
      noteGain.gain.exponentialRampToValueAtTime(0.0001, noteEndTime + releaseTime)
    }

    source.connect(noteGain)
    noteGain.connect(destination)

    const stopTime = noteEndTime + releaseTime + 0.05
    source.start(startTime)
    source.stop(stopTime)

    const isLive = !(typeof OfflineAudioContext !== 'undefined' && ctx instanceof OfflineAudioContext)
    if (isLive) {
      const voice: NoteVoice = {
        oscillators: [],
        bufferSources: [source],
        gainNode: noteGain,
        stopTime,
      }
      this.registerVoice(voice)
      source.onended = () => {
        this.activeVoices.delete(voice)
        source.disconnect()
        noteGain.disconnect()
      }
    }
  }

  /**
   * Alias for stopAll to cancel all active sounding voices immediately.
   */
  public stopAllVoices(): void {
    this.stopAll()
  }

  public close() {
    this.stopAll()
    if (this.ctx && this.ctx.state !== 'closed') {
      this.ctx.close()
    }
    this.ctx = null
    this.masterGain = null
  }

  // --- Instrument Synthesis Engines ---

  private synthPianoNote(
    ctx: BaseAudioContext,
    freq: number,
    duration: number,
    velocity: number,
    startTime: number,
    destNode?: AudioNode
  ) {
    const destination = destNode || this.masterGain
    if (!destination) return

    const osc1 = ctx.createOscillator()
    const osc2 = ctx.createOscillator()
    const noteGain = ctx.createGain()
    const filter = ctx.createBiquadFilter()

    osc1.type = 'triangle'
    osc1.frequency.setValueAtTime(freq, startTime)

    // Second harmonic with slight detune for string body resonance
    osc2.type = 'sine'
    osc2.frequency.setValueAtTime(freq * 2, startTime)

    const osc2Gain = ctx.createGain()
    osc2Gain.gain.setValueAtTime(0.35, startTime)

    filter.type = 'lowpass'
    filter.frequency.setValueAtTime(Math.min(3200, freq * 4), startTime)
    filter.frequency.exponentialRampToValueAtTime(Math.max(250, freq * 1.2), startTime + duration)

    osc1.connect(filter)
    osc2.connect(osc2Gain)
    osc2Gain.connect(filter)
    filter.connect(noteGain)
    noteGain.connect(destination)

    // ADSR Envelope
    const attack = 0.008
    const peakGain = 0.5 * velocity
    const sustainGain = peakGain * 0.25
    const releaseTime = 0.15
    const noteEndTime = startTime + duration

    noteGain.gain.setValueAtTime(0.0001, startTime)
    noteGain.gain.linearRampToValueAtTime(peakGain, startTime + attack)
    noteGain.gain.exponentialRampToValueAtTime(Math.max(0.001, sustainGain), startTime + Math.min(duration * 0.4, 0.4))
    noteGain.gain.setValueAtTime(Math.max(0.001, sustainGain), noteEndTime)
    noteGain.gain.exponentialRampToValueAtTime(0.0001, noteEndTime + releaseTime)

    osc1.start(startTime)
    osc2.start(startTime)
    osc1.stop(noteEndTime + releaseTime)
    osc2.stop(noteEndTime + releaseTime)

    const isLive = !(typeof OfflineAudioContext !== 'undefined' && ctx instanceof OfflineAudioContext)
    if (isLive) {
      const voice: NoteVoice = {
        oscillators: [osc1, osc2],
        gainNode: noteGain,
        filterNode: filter,
        stopTime: noteEndTime + releaseTime,
      }
      this.registerVoice(voice)
      osc1.onended = () => {
        this.activeVoices.delete(voice)
        osc1.disconnect()
        osc2.disconnect()
        osc2Gain.disconnect()
        filter.disconnect()
        noteGain.disconnect()
      }
    }
  }

  private synthRhodesNote(
    ctx: BaseAudioContext,
    freq: number,
    duration: number,
    velocity: number,
    startTime: number,
    destNode?: AudioNode,
    isLegato: boolean = false
  ) {
    const destination = destNode || this.masterGain
    if (!destination) return

    const oscFundamental = ctx.createOscillator()
    const oscTine = ctx.createOscillator()
    const noteGain = ctx.createGain()
    const tineGain = ctx.createGain()

    oscFundamental.type = 'sine'
    oscFundamental.frequency.setValueAtTime(freq, startTime)

    // Higher overtone for electric tine chime
    oscTine.type = 'sine'
    oscTine.frequency.setValueAtTime(freq * 3, startTime)

    tineGain.gain.setValueAtTime(0.25 * velocity, startTime)
    tineGain.gain.exponentialRampToValueAtTime(0.001, startTime + 0.3)

    oscFundamental.connect(noteGain)
    oscTine.connect(tineGain)
    tineGain.connect(noteGain)
    noteGain.connect(destination)

    const peakGain = 0.45 * velocity
    const attackTime = isLegato ? 0.025 : 0.01
    const effectiveDuration = isLegato ? duration + 0.025 : duration
    const noteEndTime = startTime + effectiveDuration
    const releaseTime = 0.2

    noteGain.gain.setValueAtTime(0.0001, startTime)
    noteGain.gain.linearRampToValueAtTime(peakGain, startTime + attackTime)
    noteGain.gain.exponentialRampToValueAtTime(Math.max(0.001, peakGain * 0.4), startTime + 0.4)
    noteGain.gain.setValueAtTime(Math.max(0.001, peakGain * 0.3), noteEndTime)
    noteGain.gain.exponentialRampToValueAtTime(0.0001, noteEndTime + releaseTime)

    oscFundamental.start(startTime)
    oscTine.start(startTime)
    oscFundamental.stop(noteEndTime + releaseTime)
    oscTine.stop(noteEndTime + releaseTime)

    const isLive = !(typeof OfflineAudioContext !== 'undefined' && ctx instanceof OfflineAudioContext)
    if (isLive) {
      const voice: NoteVoice = {
        oscillators: [oscFundamental, oscTine],
        gainNode: noteGain,
        stopTime: noteEndTime + releaseTime,
      }
      this.registerVoice(voice)
      oscFundamental.onended = () => {
        this.activeVoices.delete(voice)
        oscFundamental.disconnect()
        oscTine.disconnect()
        tineGain.disconnect()
        noteGain.disconnect()
      }
    }
  }

  private synthMarimbaNote(
    ctx: BaseAudioContext,
    freq: number,
    duration: number,
    velocity: number,
    startTime: number,
    destNode?: AudioNode
  ) {
    const destination = destNode || this.masterGain
    if (!destination) return

    const osc = ctx.createOscillator()
    const strikeOsc = ctx.createOscillator()
    const noteGain = ctx.createGain()
    const strikeGain = ctx.createGain()

    osc.type = 'sine'
    osc.frequency.setValueAtTime(freq, startTime)

    // Perceptual wooden mallet strike transient
    strikeOsc.type = 'triangle'
    strikeOsc.frequency.setValueAtTime(freq * 3.8, startTime)

    strikeGain.gain.setValueAtTime(0.4 * velocity, startTime)
    strikeGain.gain.exponentialRampToValueAtTime(0.0001, startTime + 0.04)

    osc.connect(noteGain)
    strikeOsc.connect(strikeGain)
    strikeGain.connect(noteGain)
    noteGain.connect(destination)

    const peak = 0.5 * velocity
    const decayDuration = Math.min(duration, 0.6)
    const endTime = startTime + decayDuration

    noteGain.gain.setValueAtTime(0.0001, startTime)
    noteGain.gain.linearRampToValueAtTime(peak, startTime + 0.004)
    noteGain.gain.exponentialRampToValueAtTime(0.0001, endTime)

    osc.start(startTime)
    strikeOsc.start(startTime)
    osc.stop(endTime)
    strikeOsc.stop(startTime + 0.05)

    const isLive = !(typeof OfflineAudioContext !== 'undefined' && ctx instanceof OfflineAudioContext)
    if (isLive) {
      const voice: NoteVoice = {
        oscillators: [osc, strikeOsc],
        gainNode: noteGain,
        stopTime: endTime,
      }
      this.registerVoice(voice)
      osc.onended = () => {
        this.activeVoices.delete(voice)
        osc.disconnect()
        strikeOsc.disconnect()
        strikeGain.disconnect()
        noteGain.disconnect()
      }
    }
  }

  private synthStringsNote(
    ctx: BaseAudioContext,
    freq: number,
    duration: number,
    velocity: number,
    startTime: number,
    destNode?: AudioNode
  ) {
    const destination = destNode || this.masterGain
    if (!destination) return

    const osc1 = ctx.createOscillator()
    const osc2 = ctx.createOscillator()
    const noteGain = ctx.createGain()
    const filter = ctx.createBiquadFilter()

    osc1.type = 'sawtooth'
    osc1.frequency.setValueAtTime(freq, startTime)

    // Slight chorus detune
    osc2.type = 'sawtooth'
    osc2.frequency.setValueAtTime(freq * 1.004, startTime)

    filter.type = 'lowpass'
    filter.frequency.setValueAtTime(Math.min(1400, freq * 3), startTime)

    osc1.connect(filter)
    osc2.connect(filter)
    filter.connect(noteGain)
    noteGain.connect(destination)

    // Gentle string bow attack
    const attack = 0.08
    const peakGain = 0.28 * velocity
    const noteEndTime = startTime + duration
    const releaseTime = 0.25

    noteGain.gain.setValueAtTime(0.0001, startTime)
    noteGain.gain.linearRampToValueAtTime(peakGain, startTime + attack)
    noteGain.gain.setValueAtTime(peakGain * 0.85, noteEndTime)
    noteGain.gain.exponentialRampToValueAtTime(0.0001, noteEndTime + releaseTime)

    osc1.start(startTime)
    osc2.start(startTime)
    osc1.stop(noteEndTime + releaseTime)
    osc2.stop(noteEndTime + releaseTime)

    const isLive = !(typeof OfflineAudioContext !== 'undefined' && ctx instanceof OfflineAudioContext)
    if (isLive) {
      const voice: NoteVoice = {
        oscillators: [osc1, osc2],
        gainNode: noteGain,
        filterNode: filter,
        stopTime: noteEndTime + releaseTime,
      }
      this.registerVoice(voice)
      osc1.onended = () => {
        this.activeVoices.delete(voice)
        osc1.disconnect()
        osc2.disconnect()
        filter.disconnect()
        noteGain.disconnect()
      }
    }
  }

  private synthRetroNote(
    ctx: BaseAudioContext,
    freq: number,
    duration: number,
    velocity: number,
    startTime: number,
    destNode?: AudioNode,
    isLegato: boolean = false
  ) {
    const destination = destNode || this.masterGain
    if (!destination) return

    const osc = ctx.createOscillator()
    const noteGain = ctx.createGain()

    osc.type = 'square'
    osc.frequency.setValueAtTime(freq, startTime)

    osc.connect(noteGain)
    noteGain.connect(destination)

    const peak = 0.25 * velocity
    const attackTime = isLegato ? 0.02 : 0.003
    const effectiveDuration = isLegato ? duration + 0.02 : duration
    const noteEndTime = startTime + effectiveDuration

    noteGain.gain.setValueAtTime(0.0001, startTime)
    noteGain.gain.linearRampToValueAtTime(peak, startTime + attackTime)
    noteGain.gain.setValueAtTime(peak * 0.7, noteEndTime)
    noteGain.gain.linearRampToValueAtTime(0.0001, noteEndTime + 0.04)

    osc.start(startTime)
    osc.stop(noteEndTime + 0.04)

    const isLive = !(typeof OfflineAudioContext !== 'undefined' && ctx instanceof OfflineAudioContext)
    if (isLive) {
      const voice: NoteVoice = {
        oscillators: [osc],
        gainNode: noteGain,
        stopTime: noteEndTime + 0.04,
      }
      this.registerVoice(voice)
      osc.onended = () => {
        this.activeVoices.delete(voice)
        osc.disconnect()
        noteGain.disconnect()
      }
    }
  }
}
