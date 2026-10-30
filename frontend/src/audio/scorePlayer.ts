/**
 * Score Playback Controller
 * Coordinates OpenSheetMusicDisplay cursor tracking with WebAudioSynthesizer.
 * Supports multi-track melodic line extraction (e.g. Soprano, Alto, Tenor, Bass),
 * per-track solo/mute, individual instruments & volumes, and offline audio (.wav) export.
 */

import type { OpenSheetMusicDisplay } from 'opensheetmusicdisplay'
import JSZip from 'jszip'
import { WebAudioSynthesizer, type InstrumentType, type PolyphonicNote } from './synth'
import { SampleBank, freqToMidi, INSTRUMENT_PROFILES } from './sampler'
import { encodeAudioBufferToWav, downloadAudioBlob } from './wavEncoder'
import { encodeAudioBufferToMp3 } from './mp3Encoder'
import { EffectsBusManager, type ReverbPreset, type TrackBusNodes } from './effectsBus'
import { midiService, midiToPitch } from './midiService'

export type PlaybackStatus = 'stopped' | 'playing' | 'paused'
export type AudioExportFormat = 'mp3' | 'wav'

export interface RehearsalTrackOptions {
  leadTrackId: string
  leadVolume?: number // default 100%
  leadInstrument?: InstrumentType | 'original' // default 'piano'
  backgroundVolume?: number // default 10%
  backgroundInstrument?: InstrumentType | 'original' | 'muted' // default 'flute'
  tempoBpm?: number
  reverbPreset?: ReverbPreset
  scoreTitle?: string
  customFilename?: string
  audioFormat?: AudioExportFormat // default 'mp3'
  mp3Bitrate?: number // default 128
}

export interface RehearsalBatchOptions {
  selectedTrackIds?: string[]
  leadVolume?: number // default 100
  leadInstrument?: InstrumentType | 'original' // default 'piano'
  backgroundVolume?: number // default 10
  backgroundInstrument?: InstrumentType | 'original' | 'muted' // default 'flute'
  tempoBpm?: number
  reverbPreset?: ReverbPreset
  scoreTitle?: string
  downloadAsZip?: boolean // default true
  downloadDirect?: boolean // default true
  audioFormat?: AudioExportFormat // default 'mp3'
  mp3Bitrate?: number // default 128
  onProgress?: (progress: RehearsalProgress) => void
}

export interface RehearsalProgress {
  currentTrackIndex: number
  totalTracks: number
  currentTrackName: string
  percent: number
  status: 'rendering' | 'zipping' | 'completed' | 'error'
  errorMessage?: string
}

export interface RehearsalRenderResult {
  trackId: string
  trackName: string
  voiceTag?: string
  filename: string
  blob: Blob
  format?: AudioExportFormat
}

export interface TrackConfig {
  id: string              // e.g. "P1_v1"
  name: string            // e.g. "Soprano", "Alto", "Tenor", "Bass", "Piano"
  partId: string          // e.g. "P1"
  voiceId: number         // e.g. 1
  instrument: InstrumentType
  isCustomInstrument?: boolean
  volume: number          // 0 - 100 percentage
  pan: number             // -1.0 (left) to 1.0 (right), default 0.0 (center)
  reverbSend: number      // 0.0 (dry) to 1.0 (wet), default 0.25
  isMuted: boolean
  isSolo: boolean
  voiceTag?: string       // e.g. "S", "A", "T", "B", "Pno", "Bar", "MS", "Org"
  voiceFamily?: 'vocal' | 'keyboard' | 'instrumental'
  displayName?: string    // e.g. "S - Soprano", "A - Alto", "T - Tenor", "B - Bass", "Pno - Piano"
}

export interface AutotaggedVoice {
  tag: string
  name: string
  displayName: string
  family: 'vocal' | 'keyboard' | 'instrumental'
  defaultInstrument?: InstrumentType
}

/**
 * Autotag voices (Soprano, Alto, Tenor, Bass, Piano, etc.) from abbreviations and score structure.
 */
export function resolveTrackVoiceTag(
  rawName: string,
  rawAbbr?: string | null,
  partIndex: number = 0,
  totalParts: number = 1,
  stavesCount: number = 1
): AutotaggedVoice {
  const clean = (s: string) => s.replace(/[^\w\s]/g, '').trim().toLowerCase()
  const candidate = clean(rawAbbr || '') || clean(rawName)

  const VOICE_MAP: Record<string, { tag: string; name: string; family: 'vocal' | 'keyboard' | 'instrumental'; sound?: InstrumentType }> = {
    // Soprano
    s: { tag: 'S', name: 'Soprano', family: 'vocal', sound: 'choir' },
    sop: { tag: 'S', name: 'Soprano', family: 'vocal', sound: 'choir' },
    soprano: { tag: 'S', name: 'Soprano', family: 'vocal', sound: 'choir' },
    sopranos: { tag: 'S', name: 'Soprano', family: 'vocal', sound: 'choir' },
    canto: { tag: 'S', name: 'Soprano', family: 'vocal', sound: 'choir' },
    treble: { tag: 'S', name: 'Soprano', family: 'vocal', sound: 'choir' },
    // Alto
    a: { tag: 'A', name: 'Alto', family: 'vocal', sound: 'choir' },
    alt: { tag: 'A', name: 'Alto', family: 'vocal', sound: 'choir' },
    alto: { tag: 'A', name: 'Alto', family: 'vocal', sound: 'choir' },
    altos: { tag: 'A', name: 'Alto', family: 'vocal', sound: 'choir' },
    contralto: { tag: 'A', name: 'Alto', family: 'vocal', sound: 'choir' },
    // Tenor
    t: { tag: 'T', name: 'Tenor', family: 'vocal', sound: 'choir' },
    ten: { tag: 'T', name: 'Tenor', family: 'vocal', sound: 'choir' },
    tenor: { tag: 'T', name: 'Tenor', family: 'vocal', sound: 'choir' },
    tenors: { tag: 'T', name: 'Tenor', family: 'vocal', sound: 'choir' },
    tenore: { tag: 'T', name: 'Tenor', family: 'vocal', sound: 'choir' },
    // Bass
    b: { tag: 'B', name: 'Bass', family: 'vocal', sound: 'choir' },
    bas: { tag: 'B', name: 'Bass', family: 'vocal', sound: 'choir' },
    bass: { tag: 'B', name: 'Bass', family: 'vocal', sound: 'choir' },
    basses: { tag: 'B', name: 'Bass', family: 'vocal', sound: 'choir' },
    basso: { tag: 'B', name: 'Bass', family: 'vocal', sound: 'choir' },
    bajo: { tag: 'B', name: 'Bass', family: 'vocal', sound: 'choir' },
    // Baritone
    bar: { tag: 'Bar', name: 'Baritone', family: 'vocal', sound: 'choir' },
    barit: { tag: 'Bar', name: 'Baritone', family: 'vocal', sound: 'choir' },
    baritone: { tag: 'Bar', name: 'Baritone', family: 'vocal', sound: 'choir' },
    barítono: { tag: 'Bar', name: 'Baritone', family: 'vocal', sound: 'choir' },
    baritono: { tag: 'Bar', name: 'Baritone', family: 'vocal', sound: 'choir' },
    // Mezzo-Soprano
    ms: { tag: 'MS', name: 'Mezzo-Soprano', family: 'vocal', sound: 'choir' },
    mz: { tag: 'MS', name: 'Mezzo-Soprano', family: 'vocal', sound: 'choir' },
    mezzo: { tag: 'MS', name: 'Mezzo-Soprano', family: 'vocal', sound: 'choir' },
    mezzosoprano: { tag: 'MS', name: 'Mezzo-Soprano', family: 'vocal', sound: 'choir' },
    // General Voice / Solo / Descant
    solo: { tag: 'Solo', name: 'Solo', family: 'vocal', sound: 'choir' },
    sol: { tag: 'Solo', name: 'Solo', family: 'vocal', sound: 'choir' },
    lead: { tag: 'Solo', name: 'Solo', family: 'vocal', sound: 'choir' },
    desc: { tag: 'Desc', name: 'Descant', family: 'vocal', sound: 'choir' },
    descant: { tag: 'Desc', name: 'Descant', family: 'vocal', sound: 'choir' },
    discant: { tag: 'Desc', name: 'Descant', family: 'vocal', sound: 'choir' },
    v: { tag: 'V', name: 'Voice', family: 'vocal', sound: 'choir' },
    voc: { tag: 'V', name: 'Voice', family: 'vocal', sound: 'choir' },
    vocal: { tag: 'V', name: 'Voice', family: 'vocal', sound: 'choir' },
    voice: { tag: 'V', name: 'Voice', family: 'vocal', sound: 'choir' },
    // Choir / SATB
    satb: { tag: 'SATB', name: 'Choir', family: 'vocal', sound: 'choir' },
    choir: { tag: 'SATB', name: 'Choir', family: 'vocal', sound: 'choir' },
    chorus: { tag: 'SATB', name: 'Choir', family: 'vocal', sound: 'choir' },
    choral: { tag: 'SATB', name: 'Choir', family: 'vocal', sound: 'choir' },
    // Piano
    p: { tag: 'Pno', name: 'Piano', family: 'keyboard', sound: 'piano' },
    pno: { tag: 'Pno', name: 'Piano', family: 'keyboard', sound: 'piano' },
    pf: { tag: 'Pno', name: 'Piano', family: 'keyboard', sound: 'piano' },
    piano: { tag: 'Pno', name: 'Piano', family: 'keyboard', sound: 'piano' },
    pianos: { tag: 'Pno', name: 'Piano', family: 'keyboard', sound: 'piano' },
    pianoforte: { tag: 'Pno', name: 'Piano', family: 'keyboard', sound: 'piano' },
    kbd: { tag: 'Pno', name: 'Piano', family: 'keyboard', sound: 'piano' },
    keyboard: { tag: 'Pno', name: 'Piano', family: 'keyboard', sound: 'piano' },
    klavier: { tag: 'Pno', name: 'Piano', family: 'keyboard', sound: 'piano' },
    acc: { tag: 'Pno', name: 'Piano', family: 'keyboard', sound: 'piano' },
    accomp: { tag: 'Pno', name: 'Piano', family: 'keyboard', sound: 'piano' },
    // Organ
    org: { tag: 'Org', name: 'Organ', family: 'keyboard', sound: 'synth' },
    organ: { tag: 'Org', name: 'Organ', family: 'keyboard', sound: 'synth' },
    // Instruments
    vln: { tag: 'Vln', name: 'Violin', family: 'instrumental', sound: 'strings' },
    violin: { tag: 'Vln', name: 'Violin', family: 'instrumental', sound: 'strings' },
    vc: { tag: 'Vc', name: 'Cello', family: 'instrumental', sound: 'strings' },
    cello: { tag: 'Vc', name: 'Cello', family: 'instrumental', sound: 'strings' },
    gtr: { tag: 'Gtr', name: 'Guitar', family: 'instrumental', sound: 'guitar' },
    guitar: { tag: 'Gtr', name: 'Guitar', family: 'instrumental', sound: 'guitar' },
    fl: { tag: 'Fl', name: 'Flute', family: 'instrumental', sound: 'flute' },
    flute: { tag: 'Fl', name: 'Flute', family: 'instrumental', sound: 'flute' },
    tpt: { tag: 'Tpt', name: 'Trumpet', family: 'instrumental', sound: 'brass' },
    trumpet: { tag: 'Tpt', name: 'Trumpet', family: 'instrumental', sound: 'brass' },
    hn: { tag: 'Hn', name: 'Horn', family: 'instrumental', sound: 'brass' },
    horn: { tag: 'Hn', name: 'Horn', family: 'instrumental', sound: 'brass' },
    trb: { tag: 'Trb', name: 'Trombone', family: 'instrumental', sound: 'brass' },
    trombone: { tag: 'Trb', name: 'Trombone', family: 'instrumental', sound: 'brass' },
    brass: { tag: 'Brs', name: 'Brass', family: 'instrumental', sound: 'brass' },
  }

  // 1. Direct candidate lookup
  if (candidate && VOICE_MAP[candidate]) {
    const m = VOICE_MAP[candidate]
    return {
      tag: m.tag,
      name: m.name,
      displayName: `${m.tag} - ${m.name}`,
      family: m.family,
      defaultInstrument: m.sound,
    }
  }

  // 2. Numbered voice variant (e.g. "s1", "soprano 2", "tenor 1", "b 2")
  const numberedMatch = candidate.match(/^([a-z]+)\s*(\d+|i|ii|iii|iv)$/)
  if (numberedMatch) {
    const base = numberedMatch[1]
    const num = numberedMatch[2].toUpperCase().replace('I', '1').replace('II', '2').replace('III', '3').replace('IV', '4')
    if (VOICE_MAP[base]) {
      const m = VOICE_MAP[base]
      const tag = `${m.tag}${num}`
      const name = `${m.name} ${num}`
      return {
        tag,
        name,
        displayName: `${tag} - ${name}`,
        family: m.family,
        defaultInstrument: m.sound,
      }
    }
  }

  // 3. Keyword search in rawName
  const lowerName = rawName.toLowerCase()
  if (lowerName.includes('choir') || lowerName.includes('satb') || lowerName.includes('chorus') || lowerName.includes('choral')) {
    return { tag: 'SATB', name: 'Choir', displayName: 'SATB - Choir', family: 'vocal', defaultInstrument: 'choir' }
  }
  if (lowerName.includes('piano') || lowerName.includes('keyboard') || lowerName.includes('klavier')) {
    return { tag: 'Pno', name: 'Piano', displayName: 'Pno - Piano', family: 'keyboard', defaultInstrument: 'piano' }
  }
  if (lowerName.includes('solo')) {
    return { tag: 'Solo', name: 'Solo', displayName: 'Solo - Solo', family: 'vocal', defaultInstrument: 'choir' }
  }
  if (lowerName.includes('descant') || lowerName.includes('discant')) {
    return { tag: 'Desc', name: 'Descant', displayName: 'Desc - Descant', family: 'vocal', defaultInstrument: 'choir' }
  }
  if (lowerName.includes('soprano')) {
    return { tag: 'S', name: 'Soprano', displayName: 'S - Soprano', family: 'vocal', defaultInstrument: 'choir' }
  }
  if (lowerName.includes('contralto') || lowerName.includes('alto')) {
    return { tag: 'A', name: 'Alto', displayName: 'A - Alto', family: 'vocal', defaultInstrument: 'choir' }
  }
  if (lowerName.includes('tenor')) {
    return { tag: 'T', name: 'Tenor', displayName: 'T - Tenor', family: 'vocal', defaultInstrument: 'choir' }
  }
  if (lowerName.includes('baritone') || lowerName.includes('barítono')) {
    return { tag: 'Bar', name: 'Baritone', displayName: 'Bar - Baritone', family: 'vocal', defaultInstrument: 'choir' }
  }
  if (lowerName.includes('bass') || lowerName.includes('basso') || lowerName.includes('bajo')) {
    return { tag: 'B', name: 'Bass', displayName: 'B - Bass', family: 'vocal', defaultInstrument: 'choir' }
  }

  // 4. Ensemble heuristic fallback:
  if (totalParts === 4) {
    const satb = [
      { tag: 'S', name: 'Soprano', displayName: 'S - Soprano', family: 'vocal' as const, defaultInstrument: 'choir' as const },
      { tag: 'A', name: 'Alto', displayName: 'A - Alto', family: 'vocal' as const, defaultInstrument: 'choir' as const },
      { tag: 'T', name: 'Tenor', displayName: 'T - Tenor', family: 'vocal' as const, defaultInstrument: 'choir' as const },
      { tag: 'B', name: 'Bass', displayName: 'B - Bass', family: 'vocal' as const, defaultInstrument: 'choir' as const },
    ]
    return (satb[partIndex] as AutotaggedVoice) || { tag: `P${partIndex + 1}`, name: rawName, displayName: rawName, family: 'vocal', defaultInstrument: 'choir' }
  }

  if (totalParts === 5) {
    if (partIndex === 4 && stavesCount >= 2) {
      return { tag: 'Pno', name: 'Piano', displayName: 'Pno - Piano', family: 'keyboard', defaultInstrument: 'piano' }
    }
    const ssatb = [
      { tag: 'S1', name: 'Soprano 1', displayName: 'S1 - Soprano 1', family: 'vocal' as const, defaultInstrument: 'choir' as const },
      { tag: 'S2', name: 'Soprano 2', displayName: 'S2 - Soprano 2', family: 'vocal' as const, defaultInstrument: 'choir' as const },
      { tag: 'A', name: 'Alto', displayName: 'A - Alto', family: 'vocal' as const, defaultInstrument: 'choir' as const },
      { tag: 'T', name: 'Tenor', displayName: 'T - Tenor', family: 'vocal' as const, defaultInstrument: 'choir' as const },
      { tag: 'B', name: 'Bass', displayName: 'B - Bass', family: 'vocal' as const, defaultInstrument: 'choir' as const },
    ]
    return (ssatb[partIndex] as AutotaggedVoice) || { tag: `P${partIndex + 1}`, name: rawName, displayName: rawName, family: 'vocal', defaultInstrument: 'choir' }
  }

  if (totalParts === 1 && stavesCount >= 2) {
    return { tag: 'Pno', name: 'Piano', displayName: 'Pno - Piano', family: 'keyboard', defaultInstrument: 'piano' }
  }

  if (totalParts === 2) {
    if (partIndex === 1 && stavesCount >= 2) {
      return { tag: 'Pno', name: 'Piano', displayName: 'Pno - Piano', family: 'keyboard', defaultInstrument: 'piano' }
    }
    const duet = [
      { tag: 'S', name: 'Soprano', displayName: 'S - Soprano', family: 'vocal' as const },
      { tag: 'A', name: 'Alto', displayName: 'A - Alto', family: 'vocal' as const },
    ]
    return (duet[partIndex] as AutotaggedVoice) || { tag: `P${partIndex + 1}`, name: rawName, displayName: rawName, family: 'vocal' }
  }

  const fallbackTag = rawName.length <= 4 ? rawName : `P${partIndex + 1}`
  return {
    tag: fallbackTag,
    name: rawName,
    displayName: rawName,
    family: 'instrumental',
  }
}

export interface PlaybackNote {
  frequency: number
  midi: number
  durationWholeNotes: number
  isRest: boolean
  trackId: string
  pitchText?: string
  isTieStart?: boolean
  isTieContinuation?: boolean
  tieTotalDurationWholeNotes?: number
  tieEndTimestampWholeNotes?: number
  isSlurStart?: boolean
  isSlurContinuation?: boolean
  isSlurEnd?: boolean
  isUnison?: boolean
  unisonPartId?: string
}

export interface PlaybackStep {
  stepIndex: number
  measureNumber: number
  timestampWholeNotes: number
  sourceTimestampWholeNotes?: number
  stepDurationWholeNotes: number
  notes: PlaybackNote[]
  pitchSummary?: string
}

export interface PlaybackStateSnapshot {
  status: PlaybackStatus
  currentTime: number
  totalDuration: number
  currentMeasure: number
  totalMeasures: number
  currentStepIndex: number
  totalSteps: number
  progress: number
  bpm: number
  volume: number
  isMuted: boolean
  isLooping: boolean
  instrument: InstrumentType
  reverbPreset: ReverbPreset
  cursorVisible: boolean
  autoScrollEnabled: boolean
  autoScrollSuspended: boolean
  tracks: TrackConfig[]
  hasSolo: boolean
  currentNotesPlaying: string
  title: string
  voicingMode: 'auto' | 'choral' | 'keyboard'
  maxSimultaneousPitches: number
}

export type StateChangeCallback = (state: PlaybackStateSnapshot) => void

export class ScorePlaybackController {
  private osmd: OpenSheetMusicDisplay | null = null
  private synth: WebAudioSynthesizer
  private effectsBus: EffectsBusManager | null = null
  private trackBusMap: Map<string, TrackBusNodes> = new Map()
  private reverbPreset: ReverbPreset = 'hall'
  private status: PlaybackStatus = 'stopped'
  private steps: PlaybackStep[] = []
  private tracks: TrackConfig[] = []
  private userExplicitInstrument: InstrumentType | null = null
  private scoreTitle: string = 'score'
  private composer: string = ''
  private voicingModeOverride: 'auto' | 'choral' | 'keyboard' = 'auto'
  private maxSimultaneousPitches: number = 1
  private currentStepIndex: number = 0
  private osmdCursorIndex: number = -1
  private bpm: number = 100
  private defaultBpm: number = 100
  private totalWholeNotes: number = 0
  private totalMeasures: number = 0
  private isLooping: boolean = false
  private isMuted: boolean = false
  private volume: number = 80
  private cursorVisible: boolean = true
  private autoScrollEnabled: boolean = true
  private isUserScrollSuspended: boolean = false
  private isProgrammaticScrolling: boolean = false
  private programmaticScrollTimer: any = null
  private pauseAutoScrollUntil: number = 0
  private lastScrollTime: number = 0
  private lastScrolledMeasure: number = 0
  private lastNotifiedMeasure: number = 0
  // High-Precision Dual-Clock Lookahead Scheduler
  private schedulerTimer: number | null = null
  private animationFrameId: number | null = null
  private scheduleAheadTimeSec: number = 0.25 // 250ms lookahead window for dense score resilience
  private lookaheadIntervalMs: number = 25     // 25ms tick rate
  private scheduledStepIndex: number = 0
  private nextStepAudioTime: number = 0
  private scheduledTimelineQueue: { stepIndex: number; audioTime: number; measureNumber: number }[] = []

  private stateChangeCallbacks: Set<StateChangeCallback> = new Set()
  private measureChangeCallbacks: Set<(measureNumber: number) => void> = new Set()

  constructor(synth?: WebAudioSynthesizer) {
    this.synth = synth ?? new WebAudioSynthesizer()
    this.synth.setVolume(this.volume)
    if (typeof window !== 'undefined') {
      ;(window as any).__scorePlayer = this
    }
  }

  public getSynthesizer(): WebAudioSynthesizer {
    return this.synth
  }

  public async previewNote(
    frequency: number,
    durationSec: number = 0.4,
    instrument?: InstrumentType,
    velocity: number = 0.8
  ): Promise<void> {
    const targetInst = instrument || this.synth.getInstrument()
    await this.synth.playNote(frequency, durationSec, velocity, 0, targetInst)
  }

  public onStateChange(callback: StateChangeCallback): () => void {
    this.stateChangeCallbacks.add(callback)
    callback(this.getSnapshot())
    return () => this.stateChangeCallbacks.delete(callback)
  }

  public onMeasureChange(callback: (measureNumber: number) => void): () => void {
    this.measureChangeCallbacks.add(callback)
    const currentMeasure = this.steps[this.currentStepIndex]?.measureNumber || 1
    callback(currentMeasure)
    return () => this.measureChangeCallbacks.delete(callback)
  }

  public setAutoScroll(enabled: boolean) {
    this.autoScrollEnabled = enabled
    if (!enabled) {
      this.isUserScrollSuspended = false
    }
    this.notify()
  }

  public toggleAutoScroll() {
    this.setAutoScroll(!this.autoScrollEnabled)
  }

  public suspendAutoScrollByUser(): void {
    if (!this.autoScrollEnabled || this.status !== 'playing' || this.isUserScrollSuspended) return
    this.isUserScrollSuspended = true
    this.notify()
  }

  public resumeAutoScroll(): void {
    this.isUserScrollSuspended = false
    this.pauseAutoScrollUntil = 0
    this.scrollCursorIntoView(true)
    this.notify()
  }

  public isAutoScrollSuspended(): boolean {
    return this.isUserScrollSuspended
  }

  public isCurrentlyProgrammaticScrolling(): boolean {
    return this.isProgrammaticScrolling
  }

  public setProgrammaticScrolling(durationMs: number = 700) {
    this.isProgrammaticScrolling = true
    if (this.programmaticScrollTimer) {
      clearTimeout(this.programmaticScrollTimer)
    }
    this.programmaticScrollTimer = setTimeout(() => {
      this.isProgrammaticScrolling = false
      this.programmaticScrollTimer = null
    }, durationMs)
  }

  public pauseAutoScrollFor(durationMs: number = 3000) {
    this.pauseAutoScrollUntil = Date.now() + durationMs
  }

  public setScoreMetadata(title: string, composer?: string): void {
    if (title && title.trim().length > 0 && title !== 'NoteSight Score') {
      this.scoreTitle = title.trim()
    } else if (!this.scoreTitle || this.scoreTitle === 'score') {
      if (title && title.trim().length > 0) {
        this.scoreTitle = title.trim()
      }
    }
    if (composer) this.composer = composer
    this.updateMediaSession()
  }

  public getScoreTitle(): string {
    return this.scoreTitle || 'score'
  }

  private updateMediaSession(): void {
    if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) return
    try {
      const ms = navigator.mediaSession
      if (typeof MediaMetadata !== 'undefined') {
        ms.metadata = new MediaMetadata({
          title: this.scoreTitle || 'NoteSight Sheet Music',
          artist: this.composer || 'NoteSight Studio',
          album: 'NoteSight Rehearsal',
          artwork: [
            { src: '/favicon.svg', sizes: '96x96', type: 'image/svg+xml' },
            { src: '/favicon.svg', sizes: '192x192', type: 'image/svg+xml' },
            { src: '/favicon.svg', sizes: '512x512', type: 'image/svg+xml' }
          ]
        })
      }
      ms.playbackState = this.status === 'playing' ? 'playing' : (this.status === 'paused' ? 'paused' : 'none')

      // Bind media session controls
      ms.setActionHandler('play', () => { this.play() })
      ms.setActionHandler('pause', () => { this.pause() })
      ms.setActionHandler('previoustrack', () => { this.jumpMeasures(-1) })
      ms.setActionHandler('nexttrack', () => { this.jumpMeasures(1) })
      ms.setActionHandler('seekto', (details) => {
        if (typeof details.seekTime === 'number') {
          const totalSec = this.totalWholeNotes * (240 / this.bpm)
          const ratio = Math.max(0, Math.min(1, details.seekTime / (totalSec || 1)))
          this.seekToStep(Math.floor(ratio * (this.steps.length - 1)))
        }
      })
    } catch {
      // Graceful fallback for web environments with partial MediaSession support
    }
  }

  private notify() {
    this.updateMediaSession()
    const snapshot = this.getSnapshot()
    for (const cb of this.stateChangeCallbacks) {
      try {
        cb(snapshot)
      } catch (err) {
        console.error('Error in playback state callback:', err)
      }
    }
  }

  public getSnapshot(): PlaybackStateSnapshot {
    const totalDuration = this.getTotalDurationSeconds()
    const currentTime = this.getCurrentTimeSeconds()
    const currentMeasure = this.steps[this.currentStepIndex]?.measureNumber || 1
    const hasSolo = this.tracks.some((t) => t.isSolo)

    const currentStep = this.steps[this.currentStepIndex]
    let currentNotesPlaying = ''
    if (this.status !== 'stopped' && currentStep) {
      if (currentStep.pitchSummary) {
        currentNotesPlaying = currentStep.pitchSummary
      } else if (currentStep.notes.length > 0) {
        currentNotesPlaying = currentStep.notes.map((n) => n.pitchText).filter(Boolean).join(', ')
      }
    }

    return {
      status: this.status,
      currentTime,
      totalDuration,
      currentMeasure,
      totalMeasures: this.totalMeasures,
      currentStepIndex: this.currentStepIndex,
      totalSteps: this.steps.length,
      progress: totalDuration > 0 ? Math.min(1, Math.max(0, currentTime / totalDuration)) : 0,
      bpm: this.bpm,
      volume: this.volume,
      isMuted: this.isMuted,
      isLooping: this.isLooping,
      instrument: this.synth.getInstrument(),
      reverbPreset: this.reverbPreset,
      cursorVisible: this.cursorVisible,
      autoScrollEnabled: this.autoScrollEnabled,
      autoScrollSuspended: this.isUserScrollSuspended,
      tracks: this.tracks.map((t) => ({ ...t })),
      hasSolo,
      currentNotesPlaying,
      title: this.scoreTitle || 'score',
      voicingMode: this.voicingModeOverride,
      maxSimultaneousPitches: this.maxSimultaneousPitches,
    }
  }

  // --- Track / Melodic Line Controls ---

  public getSteps(): PlaybackStep[] {
    return [...this.steps]
  }

  public getTracks(): TrackConfig[] {
    return this.tracks.map((t) => ({ ...t }))
  }

  public isTrackAudible(trackId: string): boolean {
    const anySolo = this.tracks.some((t) => t.isSolo)
    const track = this.tracks.find((t) => t.id === trackId)
    if (!track) return true
    if (anySolo) {
      return track.isSolo && !track.isMuted
    }
    return !track.isMuted
  }

  public toggleTrackSolo(trackId: string) {
    const track = this.tracks.find((t) => t.id === trackId)
    if (track) {
      track.isSolo = !track.isSolo
      this.notify()
    }
  }

  /**
   * Isolate a single melodic line (e.g. only soprano) with 1 click.
   */
  public soloOnlyTrack(trackId: string) {
    for (const t of this.tracks) {
      t.isSolo = t.id === trackId
      if (t.id === trackId) {
        t.isMuted = false
      }
    }
    this.notify()
  }

  public clearAllSolo() {
    for (const t of this.tracks) {
      t.isSolo = false
    }
    this.notify()
  }

  public getVoicingMode(): 'auto' | 'choral' | 'keyboard' {
    return this.voicingModeOverride
  }

  public setVoicingMode(mode: 'auto' | 'choral' | 'keyboard') {
    if (this.voicingModeOverride === mode) return
    this.voicingModeOverride = mode
    if (this.osmd) {
      const curStep = this.currentStepIndex
      const wasPlaying = this.status === 'playing'
      this.loadScore(this.osmd)
      if (curStep > 0 && curStep < this.steps.length) {
        this.seekToStep(curStep)
      }
      if (wasPlaying) {
        this.play()
      }
    }
    this.notify()
  }

  public canSplitChoralVoices(): boolean {
    return this.maxSimultaneousPitches >= 2 || this.tracks.length > 1
  }

  public getMaxSimultaneousPitches(): number {
    return this.maxSimultaneousPitches
  }

  public toggleTrackMute(trackId: string) {
    const track = this.tracks.find((t) => t.id === trackId)
    if (track) {
      track.isMuted = !track.isMuted
      this.notify()
    }
  }

  public setTrackMuted(trackId: string, muted: boolean) {
    const track = this.tracks.find((t) => t.id === trackId)
    if (track && track.isMuted !== muted) {
      track.isMuted = muted
      this.notify()
    }
  }

  public setTrackInstrument(trackId: string, inst: InstrumentType) {
    const track = this.tracks.find((t) => t.id === trackId)
    if (track) {
      track.instrument = inst
      track.isCustomInstrument = true
      this.prewarmScoreSamples().catch(() => {})
      this.notify()
    }
  }

  public setTrackVolume(trackId: string, volumePercent: number) {
    const track = this.tracks.find((t) => t.id === trackId)
    if (track) {
      track.volume = Math.max(0, Math.min(100, Math.round(volumePercent)))
      this.notify()
    }
  }

  public setTrackPan(trackId: string, panValue: number) {
    const track = this.tracks.find((t) => t.id === trackId)
    if (track) {
      track.pan = Math.max(-1, Math.min(1, panValue))
      const bus = this.trackBusMap.get(trackId)
      if (bus && 'pan' in bus.panner) {
        try {
          (bus.panner as StereoPannerNode).pan.setValueAtTime(track.pan, (bus.panner.context as BaseAudioContext).currentTime)
        } catch {}
      }
      this.notify()
    }
  }

  public setTrackReverbSend(trackId: string, reverbSendRatio: number) {
    const track = this.tracks.find((t) => t.id === trackId)
    if (track) {
      track.reverbSend = Math.max(0, Math.min(1, reverbSendRatio))
      const bus = this.trackBusMap.get(trackId)
      if (bus) {
        try {
          bus.reverbSendGain.gain.setValueAtTime(track.reverbSend, (bus.reverbSendGain.context as BaseAudioContext).currentTime)
        } catch {}
      }
      this.notify()
    }
  }

  public setReverbPreset(preset: ReverbPreset) {
    this.reverbPreset = preset
    if (this.effectsBus) {
      this.effectsBus.setPreset(preset)
    }
    this.notify()
  }

  public getReverbPreset(): ReverbPreset {
    return this.reverbPreset
  }

  public resetTrackMix() {
    const currentInst = this.synth.getInstrument()
    for (const t of this.tracks) {
      t.isSolo = false
      t.isMuted = false
      t.volume = 80
      t.pan = 0.0
      t.reverbSend = 0.25
      t.instrument = currentInst
      t.isCustomInstrument = false
    }
    this.rebuildTrackBuses()
    this.prewarmScoreSamples().catch(() => {})
    this.notify()
  }

  /**
   * Rebuild or wire Web Audio track effects buses when context is ready.
   */
  public async ensureEffectsBus(): Promise<EffectsBusManager | null> {
    const ctx = await this.synth.ensureContext()
    const masterGain = this.synth.getMasterGain()
    if (!masterGain) return null

    if (!this.effectsBus) {
      this.effectsBus = new EffectsBusManager(ctx, masterGain, this.reverbPreset)
    }

    this.rebuildTrackBuses()
    return this.effectsBus
  }

  private rebuildTrackBuses() {
    if (!this.effectsBus) return
    for (const bus of this.trackBusMap.values()) {
      this.effectsBus.disconnectTrackBus(bus)
    }
    this.trackBusMap.clear()
    for (const track of this.tracks) {
      const bus = this.effectsBus.createTrackBus(track.pan, track.reverbSend)
      this.trackBusMap.set(track.id, bus)
    }
  }

  /**
   * Scan and extract all musical steps and melodic lines from an initialized OpenSheetMusicDisplay instance.
   */
  public loadScore(osmd: OpenSheetMusicDisplay) {
    this.stop()
    this.osmd = osmd
    this.steps = []
    this.tracks = []
    this.totalWholeNotes = 0
    this.totalMeasures = 0

    if (!osmd || !osmd.cursor) {
      this.notify()
      return
    }

    // Extract title for export naming
    try {
      const sheet = (osmd as any).sheet
      const osmdTitle =
        sheet?.TitleString ||
        sheet?.work?.workTitle ||
        sheet?.movementTitle ||
        sheet?.title?.text ||
        sheet?.source?.title
      if (osmdTitle && typeof osmdTitle === 'string' && osmdTitle.trim().length > 0) {
        this.scoreTitle = osmdTitle.trim()
      } else if (!this.scoreTitle || this.scoreTitle === 'score') {
        this.scoreTitle = 'score'
      }
    } catch {
      if (!this.scoreTitle) this.scoreTitle = 'score'
    }

    // Try to extract initial BPM from score
    try {
      const sheetBpm = (osmd as any).sheet?.DefaultStartTempoInBpm || (osmd as any).sheet?.userStartTempoInBPM
      if (sheetBpm && typeof sheetBpm === 'number' && sheetBpm >= 30 && sheetBpm <= 300) {
        this.bpm = Math.round(sheetBpm)
        this.defaultBpm = this.bpm
      } else {
        this.bpm = 100
        this.defaultBpm = 100
      }
    } catch {
      this.bpm = 100
      this.defaultBpm = 100
    }

    // Pre-scan OSMD cursor iterator to detect maximum simultaneous sounding pitches per instrument part
    const partMaxSimultaneous = new Map<string, number>()
    let globalMaxSimultaneous = 1
    const MAX_PRESCAN_STEPS = 50000
    let preScanGuard = 0
    try {
      osmd.cursor.reset()
      while (!osmd.cursor.iterator.EndReached && ++preScanGuard < MAX_PRESCAN_STEPS) {
        const notesUnderCursor = osmd.cursor.NotesUnderCursor() || []
        const pitchedByPart = new Map<string, Set<number>>()
        for (const n of notesUnderCursor) {
          if (n && !n.isRest() && n.Pitch) {
            const freq = n.Pitch.Frequency
            if (freq && freq > 0) {
              const voiceEntry = n.ParentVoiceEntry
              const voice = voiceEntry ? voiceEntry.ParentVoice : null
              const inst = voice ? voice.Parent : (n.ParentStaff ? n.ParentStaff.ParentInstrument : null)
              const partId = inst ? (inst.IdString || `P${inst.Id + 1}`) : 'P1'
              const midi = typeof n.Pitch.getHalfTone === 'function' ? n.Pitch.getHalfTone() : Math.round(freq)
              if (!pitchedByPart.has(partId)) {
                pitchedByPart.set(partId, new Set())
              }
              pitchedByPart.get(partId)!.add(midi)
            }
          }
        }
        for (const [partId, midiSet] of pitchedByPart.entries()) {
          const prevMax = partMaxSimultaneous.get(partId) || 1
          if (midiSet.size > prevMax) {
            partMaxSimultaneous.set(partId, midiSet.size)
          }
          if (midiSet.size > globalMaxSimultaneous) {
            globalMaxSimultaneous = midiSet.size
          }
        }
        if (typeof (osmd.cursor.iterator as any).moveToNext === 'function') {
          (osmd.cursor.iterator as any).moveToNext()
        } else {
          osmd.cursor.next()
        }
      }
      osmd.cursor.reset()
    } catch (err) {
      console.warn('Could not pre-scan cursor for divisi:', err)
    }
    this.maxSimultaneousPitches = globalMaxSimultaneous

    // Discover parts and voices from OSMD Instruments with full voice/piano autotagging and divisi detection
    const discoveredTracks: Map<string, TrackConfig> = new Map()
    const partVoiceCountMap = new Map<string, number>()
    const cleanStr = (val?: any) => (typeof val === 'string' && val.trim().length > 0 ? val.trim() : null)

    try {
      const instruments = (osmd as any).sheet?.Instruments || []
      const totalParts = instruments.length
      for (let i = 0; i < totalParts; i++) {
        const inst = instruments[i]
        const partId = inst.IdString || `P${i + 1}`
        const rawAbbr = cleanStr(inst.PartAbbreviation)
        const rawName =
          cleanStr(inst.Name) ||
          rawAbbr ||
          cleanStr(inst.NameLabel?.text) ||
          `Part ${i + 1}`
        const voices = inst.Voices || []
        const stavesCount = inst.Staves?.length || 1

        const autotag = resolveTrackVoiceTag(rawName, rawAbbr, i, totalParts, stavesCount)
        const maxSimultaneous = partMaxSimultaneous.get(partId) || 1

        const isChoralMode = this.voicingModeOverride === 'choral' ||
          (this.voicingModeOverride !== 'keyboard' && (autotag.family === 'vocal' || autotag.tag === 'SATB'))

        const defaultInst = autotag.defaultInstrument || (isChoralMode ? 'choir' : autotag.family === 'vocal' ? 'choir' : autotag.family === 'keyboard' ? 'piano' : this.synth.getInstrument())

        // For keyboard instruments (Piano, Organ) and Solo/Descant staves, do NOT split into separate singer tracks
        // UNLESS choral mode is explicitly engaged or autotagged
        let voiceCount = 1
        if (this.voicingModeOverride === 'keyboard') {
          voiceCount = 1
        } else if (!isChoralMode && (autotag.family === 'keyboard' || autotag.tag === 'Solo' || autotag.tag === 'Desc')) {
          voiceCount = 1
        } else {
          voiceCount = Math.max(voices.length, maxSimultaneous)
        }
        partVoiceCountMap.set(partId, voiceCount)

        if (voiceCount > 1) {
          const SATB_MAPPINGS = [
            { tag: 'S', name: 'Soprano', displayName: 'S - Soprano' },
            { tag: 'A', name: 'Alto', displayName: 'A - Alto' },
            { tag: 'T', name: 'Tenor', displayName: 'T - Tenor' },
            { tag: 'B', name: 'Bass', displayName: 'B - Bass' },
          ]
          const DUET_MAPPINGS = [
            { tag: 'S', name: 'Soprano', displayName: 'S - Soprano' },
            { tag: 'A', name: 'Alto', displayName: 'A - Alto' },
          ]
          const TRIO_MAPPINGS = [
            { tag: 'S', name: 'Soprano', displayName: 'S - Soprano' },
            { tag: 'A', name: 'Alto', displayName: 'A - Alto' },
            { tag: 'B', name: 'Bass', displayName: 'B - Bass' },
          ]

          for (let vIdx = 0; vIdx < voiceCount; vIdx++) {
            const voiceId = vIdx + 1
            const trackId = `${partId}_v${voiceId}`

            let trackVoiceTag = `${autotag.tag}${voiceId}`
            let voiceName = `${autotag.name} ${voiceId}`
            let displayName = `${trackVoiceTag} - ${voiceName}`

            if (isChoralMode && (totalParts === 1 || autotag.tag === 'SATB' || autotag.family === 'keyboard')) {
              if (voiceCount === 4) {
                const m = SATB_MAPPINGS[vIdx]
                trackVoiceTag = m.tag
                voiceName = m.name
                displayName = m.displayName
              } else if (voiceCount === 2) {
                const m = DUET_MAPPINGS[vIdx]
                trackVoiceTag = m.tag
                voiceName = m.name
                displayName = m.displayName
              } else if (voiceCount === 3) {
                const m = TRIO_MAPPINGS[vIdx]
                trackVoiceTag = m.tag
                voiceName = m.name
                displayName = m.displayName
              }
            }

            discoveredTracks.set(trackId, {
              id: trackId,
              name: voiceName,
              displayName,
              voiceTag: trackVoiceTag,
              voiceFamily: isChoralMode ? 'vocal' : autotag.family,
              partId,
              voiceId,
              instrument: isChoralMode ? (defaultInst === 'piano' ? 'choir' : defaultInst) : defaultInst,
              isCustomInstrument: false,
              volume: 80,
              pan: 0.0,
              reverbSend: 0.25,
              isMuted: false,
              isSolo: false,
            })
          }
        } else {
          const voiceId = voices[0]?.VoiceId ?? 1
          const trackId = `${partId}_v${voiceId}`
          discoveredTracks.set(trackId, {
            id: trackId,
            name: autotag.name,
            displayName: autotag.displayName,
            voiceTag: autotag.tag,
            voiceFamily: autotag.family,
            partId,
            voiceId,
            instrument: defaultInst,
            isCustomInstrument: false,
            volume: 80,
            pan: 0.0,
            reverbSend: 0.25,
            isMuted: false,
            isSolo: false,
          })
        }
      }

      // Disambiguate duplicate display names / tags across distinct parts (e.g. Bass 1 & Bass 2 in SATBB)
      const nameCountMap = new Map<string, number>()
      for (const track of discoveredTracks.values()) {
        const baseName = track.name
        nameCountMap.set(baseName, (nameCountMap.get(baseName) || 0) + 1)
      }

      const nameOccurrenceMap = new Map<string, number>()
      for (const track of discoveredTracks.values()) {
        const baseName = track.name
        const totalOccurrences = nameCountMap.get(baseName) || 0
        if (totalOccurrences > 1) {
          const occ = (nameOccurrenceMap.get(baseName) || 0) + 1
          nameOccurrenceMap.set(baseName, occ)
          track.name = `${baseName} ${occ}`
          track.voiceTag = `${track.voiceTag}${occ}`
          track.displayName = `${track.voiceTag} - ${track.name}`
        }
      }
    } catch (err) {
      console.warn('Could not inspect score instruments:', err)
    }

    // Extract score steps by scanning through the cursor iterator
    try {
      try {
        osmd.cursor.reset()
      } catch (cursorResetErr) {
        console.warn('Initial cursor reset before timeline extraction warned:', cursorResetErr)
      }

      let stepIndex = 0
      let maxMeasure = 1
      const activeTieEndByTrack = new Map<string, number>()
      const activePseudoTieByTrack = new Map<string, { endNote: any; tieEndTimestamp: number }>()
      const activeSlursByTrack = new Map<string, any>()
      const MAX_EXTRACTION_STEPS = 50000
      let extractionGuard = 0

      while (!osmd.cursor.iterator.EndReached && ++extractionGuard < MAX_EXTRACTION_STEPS) {
        const enrolledTs = (osmd.cursor.iterator as any).CurrentEnrolledTimestamp
        const curTimestamp =
          enrolledTs && typeof enrolledTs.RealValue === 'number'
            ? enrolledTs.RealValue
            : (osmd.cursor.iterator.currentTimeStamp?.RealValue ?? 0)
        const sourceTimestamp = osmd.cursor.iterator.currentTimeStamp?.RealValue ?? curTimestamp
        const curMeasure = osmd.cursor.iterator.CurrentMeasureIndex + 1
        if (curMeasure > maxMeasure) maxMeasure = curMeasure

        if ((osmd.cursor.iterator as any).JumpOccurred) {
          activePseudoTieByTrack.clear()
          activeSlursByTrack.clear()
        }

        const notesUnderCursor = osmd.cursor.NotesUnderCursor() || []
        const stepNotes: PlaybackNote[] = []

        const processNoteForTrack = (
          n: any,
          trackId: string,
          isUnison: boolean = false,
          unisonPartId?: string
        ): PlaybackNote | null => {
          if (!n || n.isRest() || !n.Pitch) return null
          const freq = n.Pitch.Frequency
          const duration = n.Length ? n.Length.RealValue : 0.25
          if (!freq || freq <= 0) return null

          const noteMidi = freqToMidi(freq)
          let pitchText = ''
          try {
            pitchText = midiToPitch(noteMidi).name
          } catch {
            pitchText = ''
          }

          let effectiveDuration = duration
          let isTieStart = false
          let isTieContinuation = false
          let tieTotalDurationWholeNotes: number | undefined = undefined
          let tieEndTimestampWholeNotes: number | undefined = undefined

          const noteSlurs = (n as any).slurs || (n as any).Slurs || []
          const closedStartingSlur = noteSlurs.find(
            (s: any) => s && s.StartNote === n && s.EndNote && s.EndNote !== n
          )
          const pendingPseudoTie = activePseudoTieByTrack.get(trackId)
          let consumedSlurAsTie = false

          if (n.NoteTie) {
            const isStart = n.NoteTie.StartNote === n
            if (isStart) {
              isTieStart = true
              const fullDur = n.NoteTie.Duration?.RealValue
              if (typeof fullDur === 'number' && fullDur > 0) {
                effectiveDuration = fullDur
                tieTotalDurationWholeNotes = fullDur
                const endTs = curTimestamp + fullDur
                tieEndTimestampWholeNotes = endTs
                activeTieEndByTrack.set(trackId, endTs)
              }
            } else {
              isTieContinuation = true
              tieEndTimestampWholeNotes = activeTieEndByTrack.get(trackId)
            }
          } else if (pendingPseudoTie && pendingPseudoTie.endNote === n) {
            isTieContinuation = true
            tieEndTimestampWholeNotes = pendingPseudoTie.tieEndTimestamp
            activePseudoTieByTrack.delete(trackId)
            consumedSlurAsTie = true
          } else if (closedStartingSlur) {
            const endNote = closedStartingSlur.EndNote
            const endMidi =
              endNote?.Pitch && typeof endNote.Pitch.getHalfTone === 'function'
                ? endNote.Pitch.getHalfTone()
                : null
            let endAbsTs: number | undefined
            if (typeof endNote?.getAbsoluteTimestamp === 'function') {
              try {
                endAbsTs = endNote.getAbsoluteTimestamp()?.RealValue
              } catch {
                endAbsTs = undefined
              }
            }
            const isAdjacent =
              typeof endAbsTs === 'number'
                ? Math.abs(endAbsTs - (curTimestamp + duration)) < 1e-4
                : true

            if (endMidi !== null && endMidi === noteMidi && isAdjacent) {
              const endDur = endNote.Length ? endNote.Length.RealValue : duration
              const fullDur = duration + endDur
              const endTs = curTimestamp + fullDur
              isTieStart = true
              effectiveDuration = fullDur
              tieTotalDurationWholeNotes = fullDur
              tieEndTimestampWholeNotes = endTs
              activePseudoTieByTrack.set(trackId, {
                endNote,
                tieEndTimestamp: endTs,
              })
              consumedSlurAsTie = true
            }
          }

          // Slur detection for phrasing & legato
          let isSlurStart = false
          let isSlurContinuation = false
          let isSlurEnd = false

          if (!consumedSlurAsTie) {
            const activeSlur = activeSlursByTrack.get(trackId)
            const endingSlur =
              noteSlurs.find((s: any) => s && s.EndNote === n && s.StartNote && s.StartNote !== n) ||
              (activeSlur && activeSlur.EndNote === n ? activeSlur : null)

            if (closedStartingSlur) {
              isSlurStart = true
              activeSlursByTrack.set(trackId, closedStartingSlur)
            } else if (activeSlur) {
              isSlurContinuation = true
            }

            if (endingSlur) {
              isSlurEnd = true
              activeSlursByTrack.delete(trackId)
            }
          }

          return {
            frequency: freq,
            midi: noteMidi,
            durationWholeNotes: effectiveDuration,
            isRest: false,
            trackId,
            pitchText,
            isTieStart,
            isTieContinuation,
            tieTotalDurationWholeNotes,
            tieEndTimestampWholeNotes,
            isSlurStart,
            isSlurContinuation,
            isSlurEnd,
            isUnison,
            unisonPartId,
          }
        }

        // Group pitched notes under cursor by partId
        const notesByPart = new Map<string, any[]>()
        for (const n of notesUnderCursor) {
          if (n && !n.isRest() && n.Pitch && n.Pitch.Frequency > 0) {
            const voiceEntry = n.ParentVoiceEntry
            const voice = voiceEntry ? voiceEntry.ParentVoice : null
            const inst = voice ? voice.Parent : (n.ParentStaff ? n.ParentStaff.ParentInstrument : null)
            const partId = inst ? (inst.IdString || `P${inst.Id + 1}`) : 'P1'
            if (!notesByPart.has(partId)) {
              notesByPart.set(partId, [])
            }
            notesByPart.get(partId)!.push(n)
          }
        }

        for (const [partId, partNotes] of notesByPart.entries()) {
          const partVoiceCount = partVoiceCountMap.get(partId) || 1

          if (partVoiceCount > 1) {
            if (partNotes.length >= 2) {
              // Divisi: multiple simultaneous notes!
              // Sort descending by pitch (highest pitch first)
              const sortedNotes = [...partNotes].sort((a, b) => {
                const midiA = typeof a.Pitch.getHalfTone === 'function' ? a.Pitch.getHalfTone() : a.Pitch.Frequency
                const midiB = typeof b.Pitch.getHalfTone === 'function' ? b.Pitch.getHalfTone() : b.Pitch.Frequency
                return midiB - midiA
              })

              for (let j = 0; j < sortedNotes.length; j++) {
                const noteObj = sortedNotes[j]
                const vId = Math.min(j + 1, partVoiceCount)
                const trackId = `${partId}_v${vId}`
                const pn = processNoteForTrack(noteObj, trackId, false)
                if (pn) stepNotes.push(pn)
              }
            } else if (partNotes.length === 1) {
              // Unison: single note!
              // Both Voice 1 and Voice 2 sing this same line until they decouple again.
              const noteObj = partNotes[0]
              for (let vId = 1; vId <= partVoiceCount; vId++) {
                const trackId = `${partId}_v${vId}`
                const pn = processNoteForTrack(noteObj, trackId, true, partId)
                if (pn) stepNotes.push(pn)
              }
            }
          } else {
            // Single voice part (or keyboard accompaniment)
            for (const noteObj of partNotes) {
              const voiceEntry = noteObj.ParentVoiceEntry
              const voice = voiceEntry ? voiceEntry.ParentVoice : null
              const voiceId = voice && typeof voice.VoiceId === 'number' ? voice.VoiceId : 1
              const trackId = `${partId}_v${voiceId}`
              const pn = processNoteForTrack(noteObj, trackId, false)
              if (pn) stepNotes.push(pn)
            }
          }
        }

        const soundingPitches = stepNotes.map((sn) => sn.pitchText).filter(Boolean)
        const pitchSummary = soundingPitches.length > 0 ? Array.from(new Set(soundingPitches)).join(', ') : ''

        this.steps.push({
          stepIndex,
          measureNumber: curMeasure,
          timestampWholeNotes: curTimestamp,
          sourceTimestampWholeNotes: sourceTimestamp,
          stepDurationWholeNotes: 0.25, // Updated below based on step deltas
          notes: stepNotes,
          pitchSummary,
        })

        if (typeof (osmd.cursor.iterator as any).moveToNext === 'function') {
          (osmd.cursor.iterator as any).moveToNext()
        } else {
          osmd.cursor.next()
        }
        stepIndex++
      }

      this.totalMeasures = maxMeasure

      // Compute step durations based on delta between timestamps
      for (let i = 0; i < this.steps.length; i++) {
        const maxNoteLen = this.steps[i].notes.reduce((max, n) => Math.max(max, n.durationWholeNotes), 0.25)
        if (i < this.steps.length - 1) {
          const delta = this.steps[i + 1].timestampWholeNotes - this.steps[i].timestampWholeNotes
          this.steps[i].stepDurationWholeNotes = delta > 0 ? delta : maxNoteLen
        } else {
          // Last step: take the maximum duration of sounding notes, or fallback to quarter note
          this.steps[i].stepDurationWholeNotes = maxNoteLen
        }
      }

      if (this.steps.length > 0) {
        const lastStep = this.steps[this.steps.length - 1]
        this.totalWholeNotes = lastStep.timestampWholeNotes + lastStep.stepDurationWholeNotes
      }

      // Reset cursor back to start
      try {
        osmd.cursor.reset()
        this.osmdCursorIndex = 0
        if (!this.cursorVisible) {
          osmd.cursor.hide()
        }
      } catch (cursorResetErr) {
        console.warn('Cursor reset after extraction warning:', cursorResetErr)
      }
    } catch (err) {
      console.error('Failed to extract score playback timeline:', err)
    }

    // Fallback: If cursor iterator yielded 0 steps (e.g. cursor layout failed or iterator ended prematurely),
    // extract timeline directly from OSMD sheet SourceMeasures.
    if (this.steps.length === 0 && (osmd as any)?.sheet?.SourceMeasures) {
      try {
        this.extractTimelineFromSourceMeasures(osmd, discoveredTracks, partVoiceCountMap)
      } catch (fallbackErr) {
        console.error('SourceMeasures fallback extraction error:', fallbackErr)
      }
    }

    // Set extracted tracks or provide standard default
    if (discoveredTracks.size > 0) {
      this.tracks = Array.from(discoveredTracks.values())
    } else {
      this.tracks = [
        {
          id: 'P1_v1',
          name: 'Melodic Line',
          partId: 'P1',
          voiceId: 1,
          instrument: this.synth.getInstrument(),
          isCustomInstrument: false,
          volume: 80,
          pan: 0.0,
          reverbSend: 0.25,
          isMuted: false,
          isSolo: false,
        },
      ]
    }

    if (this.userExplicitInstrument) {
      for (const t of this.tracks) {
        if (!t.isCustomInstrument) {
          t.instrument = this.userExplicitInstrument
        }
      }
      this.synth.setInstrument(this.userExplicitInstrument)
    } else if (this.tracks.length > 0) {
      const primaryInst = this.tracks[0].instrument
      const allSame = this.tracks.every((t) => t.instrument === primaryInst)
      if (allSame) {
        this.synth.setInstrument(primaryInst)
      }
    }

    this.rebuildTrackBuses()
    this.currentStepIndex = 0
    this.lastScrolledMeasure = 0
    this.lastNotifiedMeasure = 0
    if (this.synth.audioContext) {
      this.prewarmScoreSamples().catch(() => {})
    }
    this.notify()
  }

  /**
   * Direct sheet-level fallback: Extract musical steps directly from OSMD sheet SourceMeasures
   * when cursor iteration fails, is skipped, or reaches EndReached prematurely.
   */
  private extractTimelineFromSourceMeasures(
    osmd: OpenSheetMusicDisplay,
    _discoveredTracks?: Map<string, TrackConfig>,
    _partVoiceCountMap?: Map<string, number>
  ): void {
    const sheet = (osmd as any).sheet
    const sourceMeasures = sheet?.SourceMeasures || []
    if (sourceMeasures.length === 0) return

    const stepMap = new Map<number, {
      measureNumber: number
      timestampWholeNotes: number
      stepDurationWholeNotes: number
      notes: PlaybackNote[]
    }>()

    let maxMeasure = 1

    for (let m = 0; m < sourceMeasures.length; m++) {
      const sm = sourceMeasures[m]
      const curMeasure = sm.MeasureNumber || (m + 1)
      if (curMeasure > maxMeasure) maxMeasure = curMeasure

      const containers = sm.VerticalSourceStaffEntryContainers || []
      for (const container of containers) {
        const curTimestamp = container.AbsoluteTimestamp ? container.AbsoluteTimestamp.RealValue : 0
        const roundedTs = Math.round(curTimestamp * 10000) / 10000

        let existingStep = stepMap.get(roundedTs)
        if (!existingStep) {
          existingStep = {
            measureNumber: curMeasure,
            timestampWholeNotes: curTimestamp,
            stepDurationWholeNotes: 0.25,
            notes: [],
          }
          stepMap.set(roundedTs, existingStep)
        }

        const staffEntries = container.StaffEntries || []
        for (const se of staffEntries) {
          const voiceEntries = se.VoiceEntries || []
          for (const ve of voiceEntries) {
            const voice = ve.ParentVoice
            const inst = voice ? voice.Parent : (se.ParentStaff ? se.ParentStaff.ParentInstrument : null)
            const partId = inst ? (inst.IdString || `P${inst.Id + 1}`) : 'P1'
            const voiceId = voice && typeof voice.VoiceId === 'number' ? voice.VoiceId : 1
            const trackId = `${partId}_v${voiceId}`

            for (const n of (ve.Notes || [])) {
              if (!n || n.isRest() || !n.Pitch) continue
              const freq = n.Pitch.Frequency
              if (!freq || freq <= 0) continue

              const noteMidi = freqToMidi(freq)
              const duration = n.Length ? n.Length.RealValue : 0.25
              let pitchText = ''
              try {
                pitchText = midiToPitch(noteMidi).name
              } catch {}

              const isTieStart = n.NoteTie ? n.NoteTie.StartNote === n : false
              const isTieContinuation = n.NoteTie ? n.NoteTie.StartNote !== n : false

              existingStep.notes.push({
                frequency: freq,
                midi: noteMidi,
                durationWholeNotes: duration,
                isRest: false,
                trackId,
                pitchText,
                isTieStart,
                isTieContinuation,
              })
            }
          }
        }
      }
    }

    const sortedTimestamps = Array.from(stepMap.keys()).sort((a, b) => a - b)
    const rawSteps: PlaybackStep[] = []

    for (let i = 0; i < sortedTimestamps.length; i++) {
      const stepData = stepMap.get(sortedTimestamps[i])!
      const soundingPitches = stepData.notes.map((sn) => sn.pitchText).filter(Boolean)
      const pitchSummary = soundingPitches.length > 0 ? Array.from(new Set(soundingPitches)).join(', ') : ''

      rawSteps.push({
        stepIndex: i,
        measureNumber: stepData.measureNumber,
        timestampWholeNotes: stepData.timestampWholeNotes,
        stepDurationWholeNotes: 0.25,
        notes: stepData.notes,
        pitchSummary,
      })
    }

    // Compute step durations based on deltas
    for (let i = 0; i < rawSteps.length; i++) {
      if (i < rawSteps.length - 1) {
        const delta = rawSteps[i + 1].timestampWholeNotes - rawSteps[i].timestampWholeNotes
        rawSteps[i].stepDurationWholeNotes = delta > 0 ? delta : 0.25
      } else {
        const maxNoteLen = rawSteps[i].notes.reduce((max, n) => Math.max(max, n.durationWholeNotes), 0.25)
        rawSteps[i].stepDurationWholeNotes = maxNoteLen
      }
    }

    if (rawSteps.length > 0) {
      this.steps = rawSteps
      this.totalMeasures = maxMeasure
      const lastStep = this.steps[this.steps.length - 1]
      this.totalWholeNotes = lastStep.timestampWholeNotes + lastStep.stepDurationWholeNotes
      console.log(`[ScorePlaybackController] Recovered ${this.steps.length} steps via SourceMeasures fallback, totalWholeNotes: ${this.totalWholeNotes}`)
    }
  }

  /**
   * Pre-warm audio samples for all unique pitches present in the score.
   * Eliminates synthesis latency and hitching during live playback.
   */
  public async prewarmScoreSamples(): Promise<void> {
    if (typeof window === 'undefined' && typeof AudioContext === 'undefined') {
      return
    }
    const ctx = await this.synth.ensureContext()
    const uniqueRequests = new Map<string, { instrument: InstrumentType; midiNote: number }>()

    for (const step of this.steps) {
      for (const note of step.notes) {
        if (!note.midi || note.isRest) continue
        const track = this.tracks.find((t) => t.id === note.trackId)
        const inst = track ? track.instrument : this.synth.getInstrument()
        if (inst in INSTRUMENT_PROFILES) {
          const key = `${inst}_${note.midi}`
          if (!uniqueRequests.has(key)) {
            uniqueRequests.set(key, { instrument: inst, midiNote: note.midi })
          }
        }
      }
    }

    if (uniqueRequests.size > 0) {
      SampleBank.getInstance().prewarmSamples(ctx, Array.from(uniqueRequests.values()))
    }
  }

  public getTotalDurationSeconds(): number {
    if (this.totalWholeNotes > 0) {
      return this.totalWholeNotes * (240 / this.bpm)
    }
    // Dynamic fallback if steps exist but totalWholeNotes was 0 or unassigned
    if (this.steps.length > 0) {
      const lastStep = this.steps[this.steps.length - 1]
      const dur = (lastStep.timestampWholeNotes || 0) + (lastStep.stepDurationWholeNotes || 0.25)
      if (dur > 0) {
        this.totalWholeNotes = dur
        return dur * (240 / this.bpm)
      }
    }
    return 0
  }

  public getCurrentTimeSeconds(): number {
    if (this.steps.length === 0 || this.currentStepIndex >= this.steps.length) return 0
    return this.steps[this.currentStepIndex].timestampWholeNotes * (240 / this.bpm)
  }

  public async play(): Promise<void> {
    if (this.status === 'playing' || this.steps.length === 0) return

    const ctx = await this.synth.ensureContext()
    await this.ensureEffectsBus()
    await this.prewarmScoreSamples()

    if (this.currentStepIndex >= this.steps.length) {
      this.seekToStep(0)
    }

    this.status = 'playing'
    this.isUserScrollSuspended = false
    this.pauseAutoScrollUntil = 0
    if (this.osmd && this.cursorVisible) {
      this.osmd.cursor.show()
    }

    this.scheduledStepIndex = this.currentStepIndex
    this.scheduledTimelineQueue = []
    // 30ms initial scheduling buffer
    this.nextStepAudioTime = ctx.currentTime + 0.03

    this.startScheduler()
    this.startVisualSync()
    this.notify()
  }

  public pause(): void {
    if (this.status !== 'playing') return
    this.clearScheduler()
    this.stopVisualSync()
    this.scheduledTimelineQueue = []
    this.synth.stopAll()
    midiService.sendAllNotesOff()
    this.status = 'paused'
    this.notify()
  }

  public stop(): void {
    this.clearScheduler()
    this.stopVisualSync()
    this.scheduledTimelineQueue = []
    this.synth.stopAll()
    midiService.sendAllNotesOff()
    this.status = 'stopped'
    this.lastScrolledMeasure = 0
    this.lastNotifiedMeasure = 0
    this.seekToStep(0)
    if (this.osmd && !this.cursorVisible) {
      this.osmd.cursor.hide()
    }
    this.notify()
  }

  public togglePlayPause(): void {
    if (this.status === 'playing') {
      this.pause()
    } else {
      this.play()
    }
  }

  public setBpm(newBpm: number) {
    const clamped = Math.max(30, Math.min(280, Math.round(newBpm)))
    if (this.bpm === clamped) return
    this.bpm = clamped
    if (this.status === 'playing') {
      this.clearScheduler()
      this.synth.stopAll()
      this.scheduledTimelineQueue = []
      this.scheduledStepIndex = this.currentStepIndex
      const ctx = this.synth.audioContext
      this.nextStepAudioTime = (ctx ? ctx.currentTime : 0) + 0.02
      this.startScheduler()
    }
    this.notify()
  }

  public resetBpmToDefault() {
    this.setBpm(this.defaultBpm)
  }

  public setVolume(volPercent: number) {
    this.volume = Math.max(0, Math.min(100, volPercent))
    this.synth.setVolume(this.volume)
    this.notify()
  }

  public setMuted(muted: boolean) {
    this.isMuted = muted
    this.synth.setMuted(muted)
    this.notify()
  }

  public toggleMute() {
    this.setMuted(!this.isMuted)
  }

  public setLoop(loop: boolean) {
    this.isLooping = loop
    this.notify()
  }

  public toggleLoop() {
    this.setLoop(!this.isLooping)
  }

  public setInstrument(type: InstrumentType, forceAll: boolean = false) {
    this.userExplicitInstrument = type
    this.synth.setInstrument(type)
    for (const track of this.tracks) {
      if (forceAll || !track.isCustomInstrument) {
        track.instrument = type
      }
    }
    this.prewarmScoreSamples().catch((err) => {
      console.warn('Failed to prewarm samples for new instrument:', err)
    })
    this.notify()
  }

  public setCursorVisible(visible: boolean) {
    this.cursorVisible = visible
    if (this.osmd) {
      if (visible) {
        this.osmd.cursor.show()
      } else {
        this.osmd.cursor.hide()
      }
    }
    this.notify()
  }

  public toggleCursorVisible() {
    this.setCursorVisible(!this.cursorVisible)
  }

  public seekToProgress(progressFraction: number) {
    const clamped = Math.max(0, Math.min(1, progressFraction))
    const targetWholeNotes = clamped * this.totalWholeNotes
    let bestIndex = 0
    let minDelta = Infinity

    for (let i = 0; i < this.steps.length; i++) {
      const delta = Math.abs(this.steps[i].timestampWholeNotes - targetWholeNotes)
      if (delta < minDelta) {
        minDelta = delta
        bestIndex = i
      }
    }
    this.seekToStep(bestIndex)
  }

  public seekToMeasure(measureNumber: number) {
    const idx = this.steps.findIndex((s) => s.measureNumber === measureNumber)
    if (idx !== -1) {
      this.seekToStep(idx)
    }
  }

  public jumpMeasures(delta: number) {
    const currentMeas = this.steps[this.currentStepIndex]?.measureNumber || 1
    const targetMeas = Math.max(1, Math.min(this.totalMeasures, currentMeas + delta))
    this.seekToMeasure(targetMeas)
  }

  public seekToStep(targetIndex: number) {
    if (this.steps.length === 0) return
    const clampedIndex = Math.max(0, Math.min(this.steps.length - 1, targetIndex))
    this.currentStepIndex = clampedIndex
    this.scheduledStepIndex = clampedIndex
    this.scheduledTimelineQueue = []
    this.isUserScrollSuspended = false
    this.pauseAutoScrollUntil = 0

    this.positionOsmdCursor(clampedIndex)

    const currentMeasure = this.steps[clampedIndex]?.measureNumber || 1
    if (currentMeasure !== this.lastNotifiedMeasure) {
      this.lastNotifiedMeasure = currentMeasure
      for (const cb of this.measureChangeCallbacks) {
        try {
          cb(currentMeasure)
        } catch (err) {
          console.error('Error in measure change callback:', err)
        }
      }
    }

    if (this.status === 'playing') {
      this.clearScheduler()
      this.synth.stopAll()
      const ctx = this.synth.audioContext
      this.nextStepAudioTime = (ctx ? ctx.currentTime : 0) + 0.03
      this.startScheduler()
    }

    this.notify()
  }

  /**
   * Position OSMD cursor precisely to target step.
   */
  private positionOsmdCursor(targetIndex: number) {
    if (!this.osmd || !this.osmd.cursor) return

    try {
      if (this.osmdCursorIndex < 0 || targetIndex < this.osmdCursorIndex) {
        this.osmd.cursor.reset()
        this.osmdCursorIndex = 0
      }

      const MAX_ADVANCE_STEPS = 50000
      let advanceGuard = 0
      while (this.osmdCursorIndex < targetIndex && ++advanceGuard < MAX_ADVANCE_STEPS) {
        if (this.osmd.cursor.iterator.EndReached) break
        // For multi-step seeks, advance iterator directly without heavy DOM reflows per intermediate step
        if (targetIndex - this.osmdCursorIndex > 1 && typeof (this.osmd.cursor.iterator as any).moveToNext === 'function') {
          (this.osmd.cursor.iterator as any).moveToNext()
        } else {
          this.osmd.cursor.next()
        }
        this.osmdCursorIndex++
      }

      // Ensure cursor graphic is updated to active position
      if (typeof (this.osmd.cursor as any).update === 'function') {
        this.osmd.cursor.update()
      }

      if (this.cursorVisible) {
        this.osmd.cursor.show()
        this.scrollCursorIntoView()
      } else {
        this.osmd.cursor.hide()
      }
    } catch (err) {
      console.warn('Cursor positioning issue:', err)
      this.osmdCursorIndex = -1
    }
  }

  /**
   * Smoothly scroll container or window to ensure the active measure/cursor is visible.
   */
  public scrollCursorIntoView(force: boolean = false) {
    if (!this.autoScrollEnabled || !this.osmd || !this.osmd.cursor) return
    if (this.isUserScrollSuspended && !force) return
    if (Date.now() < this.pauseAutoScrollUntil && !force) return

    if (force) {
      this.isUserScrollSuspended = false
      this.pauseAutoScrollUntil = 0
    }

    const now = Date.now()
    const currentMeasure = this.steps[this.currentStepIndex]?.measureNumber || 1

    if (!force && currentMeasure === this.lastScrolledMeasure && (now - this.lastScrollTime < 500)) {
      return
    }

    // Record check timestamp and measure to avoid layout thrashing on subsequent fast notes within same measure
    this.lastScrollTime = now
    this.lastScrolledMeasure = currentMeasure

    try {
      const cursorEl = this.osmd.cursor.cursorElement
      if (cursorEl && cursorEl.parentElement) {
        const rect = cursorEl.getBoundingClientRect()
        // Abort if cursor is inside a hidden page or not rendered in layout
        if (rect.width === 0 || rect.height === 0) return

        const viewportHeight = window.innerHeight || document.documentElement.clientHeight
        const isMobile = typeof window !== 'undefined' && window.innerWidth <= 768
        const stickyOffset = isMobile ? 60 : 160
        const isTooLow = rect.bottom > viewportHeight * 0.78
        const isTooHigh = rect.top < (stickyOffset + 20)

        if (isTooLow || isTooHigh || force) {
          // If programmatic scrolling is currently active (e.g. from page flip), do not fight it unless forced
          if (this.isProgrammaticScrolling && !force) return

          const container = cursorEl.closest('.score-viewer-wrapper.is-fullscreen, .score-canvas-scroller') as HTMLElement | null
          if (container && container.scrollHeight > container.clientHeight && container.clientHeight > 200) {
            const containerRect = container.getBoundingClientRect()
            const relativeTop = rect.top - containerRect.top + container.scrollTop
            this.setProgrammaticScrolling()
            container.scrollTo({ top: Math.max(0, relativeTop - stickyOffset - 24), behavior: 'smooth' })
          } else {
            this.setProgrammaticScrolling()
            const targetY = (window.scrollY || window.pageYOffset || 0) + rect.top - stickyOffset - 24
            window.scrollTo({ top: Math.max(0, targetY), behavior: 'smooth' })
          }
        }
      }
    } catch {}
  }

  /**
   * Start the 25ms high-frequency scheduler ticker.
   */
  private startScheduler() {
    this.clearScheduler()
    this.runSchedulerTick()
    this.schedulerTimer = window.setInterval(() => {
      this.runSchedulerTick()
    }, this.lookaheadIntervalMs)
  }

  private clearScheduler() {
    if (this.schedulerTimer !== null) {
      clearInterval(this.schedulerTimer)
      this.schedulerTimer = null
    }
  }

  /**
   * High-precision lookahead scheduler tick.
   * Schedules notes onto the Web Audio hardware clock within the lookahead window (150ms).
   */
  private runSchedulerTick() {
    if (this.status !== 'playing') return
    const ctx = this.synth.audioContext
    if (!ctx) return

    // Resynchronize if hardware clock drifted significantly ahead (e.g. backgrounded tab or heavy reflow)
    if (this.nextStepAudioTime < ctx.currentTime - 0.25) {
      this.nextStepAudioTime = ctx.currentTime + 0.03
    }

    let scheduledCount = 0
    while (
      this.scheduledStepIndex < this.steps.length &&
      this.nextStepAudioTime < ctx.currentTime + this.scheduleAheadTimeSec &&
      scheduledCount++ < 100
    ) {
      const step = this.steps[this.scheduledStepIndex]
      const stepDurationSec = Math.max(0.01, (step.stepDurationWholeNotes || 0.25) * (240 / Math.max(20, this.bpm)))

      this.scheduleStepAudio(step, this.nextStepAudioTime, this.scheduledStepIndex)

      this.scheduledTimelineQueue.push({
        stepIndex: this.scheduledStepIndex,
        audioTime: this.nextStepAudioTime,
        measureNumber: step.measureNumber,
      })

      this.nextStepAudioTime += stepDurationSec
      this.scheduledStepIndex++
    }

    if (this.scheduledStepIndex >= this.steps.length && this.isLooping) {
      this.scheduledStepIndex = 0
    }
  }

  /**
   * Schedule audio synthesis for a step at the exact hardware audio timestamp.
   */
  private scheduleStepAudio(step: PlaybackStep, stepAudioTime: number, stepIdx: number) {
    const isSequential = stepIdx > 0

    const notesToPlay: PolyphonicNote[] = []
    const unisonPlayedParts = new Set<string>()

    for (const n of step.notes) {
      if (!this.isTrackAudible(n.trackId)) continue

      if (n.isUnison && n.unisonPartId) {
        if (unisonPlayedParts.has(n.unisonPartId)) {
          // Avoid duplicate synthesis when multiple sibling voices of a section are audible
          continue
        }
        unisonPlayedParts.add(n.unisonPartId)
      }

      if (n.isTieContinuation) {
        if (isSequential) {
          // Do not re-attack notes that are continuations of a tie/ligature during sequential playback
          continue
        } else {
          // Playback started or seeked directly into a tied continuation step!
          let remainingDurationWholeNotes = n.durationWholeNotes
          if (typeof n.tieEndTimestampWholeNotes === 'number') {
            remainingDurationWholeNotes = Math.max(0.05, n.tieEndTimestampWholeNotes - step.timestampWholeNotes)
          }
          const remainingDurationSec = remainingDurationWholeNotes * (240 / this.bpm)
          const track = this.tracks.find((t) => t.id === n.trackId)
          const inst = track ? track.instrument : this.synth.getInstrument()
          const trackVol = track ? track.volume / 100 : 0.8
          const trackBus = this.trackBusMap.get(n.trackId)

          notesToPlay.push({
            frequency: n.frequency,
            durationSec: remainingDurationSec,
            velocity: 0.75,
            instrument: inst,
            volumeMultiplier: trackVol,
            destinationNode: trackBus ? trackBus.inputGain : undefined,
            isLegato: true,
          })
          continue
        }
      }

      const track = this.tracks.find((t) => t.id === n.trackId)
      const inst = track ? track.instrument : this.synth.getInstrument()
      const trackVol = track ? track.volume / 100 : 0.8
      const trackBus = this.trackBusMap.get(n.trackId)

      notesToPlay.push({
        frequency: n.frequency,
        durationSec: n.durationWholeNotes * (240 / this.bpm),
        velocity: 0.8,
        instrument: inst,
        volumeMultiplier: trackVol,
        destinationNode: trackBus ? trackBus.inputGain : undefined,
        isLegato: !!n.isSlurContinuation,
      })
    }

    if (notesToPlay.length > 0) {
      const ctx = this.synth.audioContext
      const offsetSec = ctx ? Math.max(0, stepAudioTime - ctx.currentTime) : 0
      this.synth.playPolyphonicNotes(notesToPlay, offsetSec)
      if (midiService.isOutputEnabled) {
        midiService.routeScoreNotes(notesToPlay, offsetSec)
      }
    }
  }

  /**
   * Decoupled visual synchronization engine.
   * Tracks AudioContext.currentTime using requestAnimationFrame to update OSMD cursor
   * and auto-scroll without blocking the audio scheduler thread.
   */
  private startVisualSync() {
    this.stopVisualSync()

    const tickVisuals = () => {
      if (this.status !== 'playing') return
      const ctx = this.synth.audioContext
      if (!ctx) return

      const curAudioTime = ctx.currentTime

      // Drain scheduled queue up to curAudioTime
      let newlyActiveStepIndex: number | null = null
      while (
        this.scheduledTimelineQueue.length > 0 &&
        this.scheduledTimelineQueue[0].audioTime <= curAudioTime
      ) {
        const item = this.scheduledTimelineQueue.shift()!
        newlyActiveStepIndex = item.stepIndex
      }

      if (newlyActiveStepIndex !== null && newlyActiveStepIndex !== this.currentStepIndex) {
        this.currentStepIndex = newlyActiveStepIndex
        const currentStep = this.steps[this.currentStepIndex]
        const currentMeasure = currentStep?.measureNumber || 1

        this.positionOsmdCursor(newlyActiveStepIndex)

        if (currentMeasure !== this.lastNotifiedMeasure) {
          this.lastNotifiedMeasure = currentMeasure
          for (const cb of this.measureChangeCallbacks) {
            try {
              cb(currentMeasure)
            } catch (err) {
              console.error('Error in measure change callback:', err)
            }
          }
        }

        this.notify()
      }

      // Check if playback reached the very end (when not looping)
      if (
        !this.isLooping &&
        this.scheduledStepIndex >= this.steps.length &&
        this.scheduledTimelineQueue.length === 0 &&
        curAudioTime >= this.nextStepAudioTime
      ) {
        this.stop()
        return
      }

      const raf = typeof requestAnimationFrame === 'function' ? requestAnimationFrame : (cb: any) => setTimeout(cb, 16)
      this.animationFrameId = raf(tickVisuals) as any
    }

    const raf = typeof requestAnimationFrame === 'function' ? requestAnimationFrame : (cb: any) => setTimeout(cb, 16)
    this.animationFrameId = raf(tickVisuals) as any
  }

  private stopVisualSync() {
    if (this.animationFrameId !== null) {
      const caf = typeof cancelAnimationFrame === 'function' ? cancelAnimationFrame : clearTimeout
      caf(this.animationFrameId)
      this.animationFrameId = null
    }
  }

  /**
   * Export audio with the selected configuration (soloed lines, instruments, volumes, BPM)
   * to a standard 44.1kHz 16-bit PCM WAV file via OfflineAudioContext.
   */
  public async exportAudio(customFilename?: string): Promise<{ blob: Blob; filename: string }> {
    if ((this.steps.length === 0 || this.getTotalDurationSeconds() <= 0) && this.osmd) {
      try {
        this.loadScore(this.osmd)
      } catch (recoverErr) {
        console.warn('Audio export timeline recovery warning:', recoverErr)
      }
    }

    const totalSec = this.getTotalDurationSeconds()
    if (totalSec <= 0 || this.steps.length === 0) {
      throw new Error('No playable score notes available to export.')
    }

    const sampleRate = 44100
    const releaseTailSec = 1.0
    const totalDurationSec = totalSec + releaseTailSec
    const totalFrames = Math.ceil(totalDurationSec * sampleRate)

    const OfflineCtxClass =
      window.OfflineAudioContext || (window as any).webkitOfflineAudioContext
    if (!OfflineCtxClass) {
      throw new Error('OfflineAudioContext is not supported by your browser.')
    }

    const offlineCtx = new OfflineCtxClass(2, totalFrames, sampleRate)
    const offlineMasterGain = offlineCtx.createGain()
    const masterGainValue = this.isMuted ? 0 : this.volume / 100
    offlineMasterGain.gain.setValueAtTime(masterGainValue, 0)
    offlineMasterGain.connect(offlineCtx.destination)

    // Wire matching offline effects bus and track buses
    const offlineBusManager = new EffectsBusManager(offlineCtx, offlineMasterGain, this.reverbPreset)
    const offlineTrackBusMap = new Map<string, TrackBusNodes>()
    for (const track of this.tracks) {
      const bus = offlineBusManager.createTrackBus(track.pan, track.reverbSend)
      offlineTrackBusMap.set(track.id, bus)
    }

    // Schedule notes across entire score timeline
    for (const step of this.steps) {
      const stepStartTimeSec = step.timestampWholeNotes * (240 / this.bpm)
      const unisonRenderedParts = new Set<string>()
      for (const note of step.notes) {
        if (!this.isTrackAudible(note.trackId)) continue
        if (note.isUnison && note.unisonPartId) {
          if (unisonRenderedParts.has(note.unisonPartId)) {
            continue
          }
          unisonRenderedParts.add(note.unisonPartId)
        }
        // Do not re-schedule notes that are continuations of a tie/ligature
        if (note.isTieContinuation) continue

        const track = this.tracks.find((t) => t.id === note.trackId)
        const inst = track ? track.instrument : this.synth.getInstrument()
        const trackVol = track ? track.volume / 100 : 0.8
        const noteDurationSec = Math.max(0.08, note.durationWholeNotes * (240 / this.bpm))
        const effectiveVelocity = 0.8 * trackVol
        const bus = offlineTrackBusMap.get(note.trackId)
        const targetDest = bus ? bus.inputGain : offlineMasterGain

        this.synth.renderNoteToContext(
          offlineCtx,
          note.frequency,
          noteDurationSec,
          effectiveVelocity,
          stepStartTimeSec,
          inst,
          targetDest,
          !!note.isSlurContinuation
        )
      }
    }

    const renderedBuffer = await offlineCtx.startRendering()
    const wavBlob = encodeAudioBufferToWav(renderedBuffer)

    // Determine descriptive filename
    let filename = customFilename
    if (!filename) {
      const safeBase = this.scoreTitle.toLowerCase().replace(/[^a-z0-9_-]/g, '_').replace(/_+/g, '_') || 'score'
      const activeSoloTracks = this.tracks.filter((t) => t.isSolo)
      if (activeSoloTracks.length === 1) {
        const trackSlug = activeSoloTracks[0].name.toLowerCase().replace(/[^a-z0-9]/g, '_').replace(/_+/g, '_')
        filename = `${safeBase}_${trackSlug}_solo.wav`
      } else if (activeSoloTracks.length > 1) {
        filename = `${safeBase}_selected_voices.wav`
      } else {
        filename = `${safeBase}_audio_mix.wav`
      }
    }

    downloadAudioBlob(wavBlob, filename)
    return { blob: wavBlob, filename }
  }

  /**
   * Render a dedicated rehearsal practice audio track for a specific lead voice.
   * Highlights the chosen voice at leadVolume (e.g. 100% Grand Piano) while keeping
   * other ensemble voices softly audible in background (e.g. 10% Concert Flute).
   */
  public async renderRehearsalTrack(options: RehearsalTrackOptions): Promise<RehearsalRenderResult> {
    if ((this.steps.length === 0 || this.getTotalDurationSeconds() <= 0) && this.osmd) {
      try {
        this.loadScore(this.osmd)
      } catch (recoverErr) {
        console.warn('Rehearsal export timeline recovery warning:', recoverErr)
      }
    }

    const totalSec = this.getTotalDurationSeconds()
    if (totalSec <= 0 || this.steps.length === 0) {
      throw new Error('No playable score notes available to export.')
    }

    let leadTrack = this.tracks.find((t) => t.id === options.leadTrackId)
    if (!leadTrack) {
      leadTrack = this.tracks.find((t) => t.voiceTag === options.leadTrackId || t.name === options.leadTrackId)
    }
    if (!leadTrack) {
      throw new Error(`Lead track with ID '${options.leadTrackId}' not found.`)
    }

    const leadVolume = typeof options.leadVolume === 'number' ? options.leadVolume : 100
    const bgVolume = typeof options.backgroundVolume === 'number' ? options.backgroundVolume : 10
    const leadInstOption = options.leadInstrument || 'piano'
    const bgInstOption = options.backgroundInstrument || 'flute'
    const effectiveBpm = options.tempoBpm && options.tempoBpm >= 30 && options.tempoBpm <= 300 ? options.tempoBpm : this.bpm
    const effectiveReverb = options.reverbPreset || this.reverbPreset

    const bpmScale = 240 / effectiveBpm
    const effectiveWholeNotes = this.totalWholeNotes > 0
      ? this.totalWholeNotes
      : (this.steps[this.steps.length - 1]?.timestampWholeNotes || 0) + (this.steps[this.steps.length - 1]?.stepDurationWholeNotes || 0.25)
    const totalDurationSec = (effectiveWholeNotes * bpmScale) + 1.0 // 1.0s release tail
    const sampleRate = 44100
    const totalFrames = Math.ceil(totalDurationSec * sampleRate)

    const OfflineCtxClass =
      window.OfflineAudioContext || (window as any).webkitOfflineAudioContext
    if (!OfflineCtxClass) {
      throw new Error('OfflineAudioContext is not supported by your browser.')
    }

    const offlineCtx = new OfflineCtxClass(2, totalFrames, sampleRate)
    const offlineMasterGain = offlineCtx.createGain()
    offlineMasterGain.gain.setValueAtTime(1.0, 0)
    offlineMasterGain.connect(offlineCtx.destination)

    const offlineBusManager = new EffectsBusManager(offlineCtx, offlineMasterGain, effectiveReverb)
    const offlineTrackBusMap = new Map<string, TrackBusNodes>()
    for (const track of this.tracks) {
      const bus = offlineBusManager.createTrackBus(track.pan, track.reverbSend)
      offlineTrackBusMap.set(track.id, bus)
    }

    // Schedule all score notes
    for (const step of this.steps) {
      const stepStartTimeSec = step.timestampWholeNotes * bpmScale
      for (const note of step.notes) {
        if (note.isTieContinuation) continue

        const isLead = note.trackId === options.leadTrackId
        const track = this.tracks.find((t) => t.id === note.trackId)

        // For rehearsal tracks: if this is a unison note and is NOT the lead track,
        // do not duplicate it on background accompaniment if the lead track is in that same part!
        if (note.isUnison && !isLead) {
          const leadTrackConfig = this.tracks.find((t) => t.id === options.leadTrackId)
          if (leadTrackConfig && leadTrackConfig.partId === note.unisonPartId) {
            continue // Lead is already singing this unison note at lead volume
          }
        }

        // Calculate volume
        let trackVol = 0.8
        if (isLead) {
          trackVol = leadVolume / 100
        } else {
          if (bgInstOption === 'muted' || bgVolume <= 0) {
            continue // Silenced
          }
          trackVol = bgVolume / 100
        }

        if (trackVol <= 0) continue

        // Determine instrument
        let inst: InstrumentType = 'piano'
        if (isLead) {
          inst = leadInstOption === 'original' && track ? track.instrument : (leadInstOption as InstrumentType) || 'piano'
        } else {
          inst = bgInstOption === 'original' && track ? track.instrument : (bgInstOption as InstrumentType) || 'flute'
        }

        const noteDurationSec = Math.max(0.08, note.durationWholeNotes * bpmScale)
        const effectiveVelocity = 0.8 * trackVol
        const bus = offlineTrackBusMap.get(note.trackId)
        const targetDest = bus ? bus.inputGain : offlineMasterGain

        this.synth.renderNoteToContext(
          offlineCtx,
          note.frequency,
          noteDurationSec,
          effectiveVelocity,
          stepStartTimeSec,
          inst,
          targetDest,
          !!note.isSlurContinuation
        )
      }
    }

    const renderedBuffer = await offlineCtx.startRendering()
    // Rehearsal tracks are strictly encoded to MP3 (128 kbps) to guarantee minimal file size (<15MB total),
    // prevent mobile browser memory exhaustion, and enable easy sharing over messaging & email.
    const mp3Blob = await encodeAudioBufferToMp3(renderedBuffer, { bitrate: 128 })

    // Format safe voice name filename
    let filename = options.customFilename
    if (!filename) {
      const activeTitle = (options.scoreTitle && options.scoreTitle.trim()) || this.scoreTitle
      const safeScore = activeTitle.trim().replace(/[^a-zA-Z0-9_\-\s]/g, '').replace(/\s+/g, '_') || 'score'
      const voiceRaw = leadTrack.displayName || leadTrack.name
      const safeVoice = voiceRaw.trim().replace(/[^a-zA-Z0-9_\-\s]/g, '').replace(/\s+/g, '_')
      filename = `${safeScore}_${safeVoice}_rehearsal.mp3`
    }

    return {
      trackId: leadTrack.id,
      trackName: leadTrack.name,
      voiceTag: leadTrack.voiceTag,
      filename,
      blob: mp3Blob,
      format: 'mp3',
    }
  }

  /**
   * Batch render and export rehearsal practice tracks for multiple voices.
   * Can package into a single .zip file (DEFLATE compressed) or download individual tracks.
   */
  public async exportRehearsalTracksBatch(
    options: RehearsalBatchOptions = {}
  ): Promise<{ results: RehearsalRenderResult[]; zipBlob?: Blob; zipFilename?: string }> {
    const trackIds = options.selectedTrackIds && options.selectedTrackIds.length > 0
      ? options.selectedTrackIds
      : this.tracks.map((t) => t.id)

    if (trackIds.length === 0) {
      throw new Error('No tracks selected for rehearsal export.')
    }

    const results: RehearsalRenderResult[] = []
    const total = trackIds.length

    for (let i = 0; i < total; i++) {
      const trackId = trackIds[i]
      const track = this.tracks.find((t) => t.id === trackId)
      const trackName = track ? (track.displayName || track.name) : `Track ${i + 1}`

      if (options.onProgress) {
        options.onProgress({
          currentTrackIndex: i + 1,
          totalTracks: total,
          currentTrackName: trackName,
          percent: Math.round((i / total) * 100),
          status: 'rendering',
        })
      }

      // Small yield so UI updates smoothly
      await new Promise((r) => setTimeout(r, 10))

      const result = await this.renderRehearsalTrack({
        leadTrackId: trackId,
        leadVolume: options.leadVolume,
        leadInstrument: options.leadInstrument,
        backgroundVolume: options.backgroundVolume,
        backgroundInstrument: options.backgroundInstrument,
        tempoBpm: options.tempoBpm,
        reverbPreset: options.reverbPreset,
        scoreTitle: options.scoreTitle,
        audioFormat: options.audioFormat,
        mp3Bitrate: options.mp3Bitrate,
      })
      results.push(result)
    }

    let zipBlob: Blob | undefined
    let zipFilename: string | undefined

    const shouldDownloadDirect = options.downloadDirect !== false
    const downloadAsZip = options.downloadAsZip !== false

    if (downloadAsZip) {
      if (options.onProgress) {
        options.onProgress({
          currentTrackIndex: total,
          totalTracks: total,
          currentTrackName: 'Packaging ZIP archive...',
          percent: 95,
          status: 'zipping',
        })
      }

      const zip = new JSZip()
      const usedFilenames = new Map<string, number>()
      for (const res of results) {
        let entryName = res.filename
        const count = usedFilenames.get(entryName) || 0
        if (count > 0) {
          const dotIdx = entryName.lastIndexOf('.')
          const base = dotIdx !== -1 ? entryName.substring(0, dotIdx) : entryName
          const ext = dotIdx !== -1 ? entryName.substring(dotIdx) : ''
          entryName = `${base}_${count + 1}${ext}`
        }
        usedFilenames.set(res.filename, count + 1)

        const arrayBuf = await res.blob.arrayBuffer()
        zip.file(entryName, arrayBuf)
      }

      zipBlob = await zip.generateAsync({
        type: 'blob',
        compression: 'DEFLATE',
        compressionOptions: {
          level: 6,
        },
      })
      const activeTitle = (options.scoreTitle && options.scoreTitle.trim()) || this.scoreTitle
      const safeScore = activeTitle.trim().replace(/[^a-zA-Z0-9_\-\s]/g, '').replace(/\s+/g, '_') || 'score'
      zipFilename = `${safeScore}_rehearsal_tracks.zip`

      if (shouldDownloadDirect) {
        downloadAudioBlob(zipBlob, zipFilename)
      }
    } else {
      if (shouldDownloadDirect) {
        // Stagger individual downloads slightly so browser doesn't block them
        for (let i = 0; i < results.length; i++) {
          const res = results[i]
          setTimeout(() => {
            downloadAudioBlob(res.blob, res.filename)
          }, i * 250)
        }
      }
    }

    if (options.onProgress) {
      options.onProgress({
        currentTrackIndex: total,
        totalTracks: total,
        currentTrackName: 'Completed',
        percent: 100,
        status: 'completed',
      })
    }

    return { results, zipBlob, zipFilename }
  }

  /**
   * Apply rehearsal practice balance directly to the active live player.
   * Allows the musician to listen and practice interactively inside NoteSight.
   */
  public applyRehearsalMix(
    leadTrackId: string,
    leadVolume: number = 100,
    leadInstrument: InstrumentType | 'original' = 'piano',
    backgroundVolume: number = 10,
    backgroundInstrument: InstrumentType | 'original' | 'muted' = 'flute'
  ): void {
    for (const track of this.tracks) {
      track.isSolo = false
      if (track.id === leadTrackId) {
        track.isMuted = false
        track.volume = Math.max(0, Math.min(100, leadVolume))
        if (leadInstrument !== 'original') {
          track.instrument = leadInstrument
          track.isCustomInstrument = true
        }
      } else {
        if (backgroundInstrument === 'muted' || backgroundVolume <= 0) {
          track.isMuted = true
          track.volume = 0
        } else {
          track.isMuted = false
          track.volume = Math.max(0, Math.min(100, backgroundVolume))
          if (backgroundInstrument !== 'original') {
            track.instrument = backgroundInstrument
            track.isCustomInstrument = true
          }
        }
      }
    }

    this.rebuildTrackBuses()
    this.prewarmScoreSamples().catch(() => {})
    this.notify()
  }

  public destroy() {
    this.stop()
    if (this.programmaticScrollTimer) {
      clearTimeout(this.programmaticScrollTimer)
      this.programmaticScrollTimer = null
    }
    this.clearScheduler()
    this.stopVisualSync()
    if (this.effectsBus) {
      for (const bus of this.trackBusMap.values()) {
        this.effectsBus.disconnectTrackBus(bus)
      }
      this.trackBusMap.clear()
      this.effectsBus.dispose()
      this.effectsBus = null
    }
    this.synth.close()
    this.stateChangeCallbacks.clear()
    this.measureChangeCallbacks.clear()
    this.osmd = null
  }
}
