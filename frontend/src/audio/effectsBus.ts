/**
 * Effects Chain and Master Reverb Graph for NoteSight Web Audio Engine
 * Supports studio reverb presets (Room, Hall, Cathedral, Plate) via
 * high-precision synthetic impulse responses and stereo panning per track.
 */

export type ReverbPreset = 'none' | 'room' | 'hall' | 'cathedral' | 'plate'

export interface ReverbPresetOption {
  id: ReverbPreset
  name: string
  description: string
  decayTime: number
}

export const REVERB_PRESETS: ReverbPresetOption[] = [
  { id: 'none', name: 'Dry / Off', description: 'Zero artificial reverb', decayTime: 0 },
  { id: 'room', name: 'Studio Room', description: 'Intimate acoustic chamber with short decay', decayTime: 0.9 },
  { id: 'hall', name: 'Concert Hall', description: 'Warm acoustic concert hall with spacious decay', decayTime: 2.2 },
  { id: 'cathedral', name: 'Cathedral', description: 'Expansive stone sanctuary with sustained reverberation', decayTime: 4.0 },
  { id: 'plate', name: 'Vintage Plate', description: 'Bright, metallic plate reverb resonance', decayTime: 1.6 },
]

/**
 * Generate a high quality algorithmic stereo impulse response buffer.
 * Eliminates external static audio file downloads and is compatible with
 * both live AudioContext and OfflineAudioContext.
 */
export function generateImpulseResponse(
  ctx: BaseAudioContext,
  preset: ReverbPreset
): AudioBuffer | null {
  if (preset === 'none') return null

  const opt = REVERB_PRESETS.find((p) => p.id === preset) || REVERB_PRESETS[2]
  const sampleRate = ctx.sampleRate
  const lengthSec = opt.decayTime
  const lengthFrames = Math.floor(sampleRate * lengthSec)

  const buffer = ctx.createBuffer(2, lengthFrames, sampleRate)
  const left = buffer.getChannelData(0)
  const right = buffer.getChannelData(1)

  const decay = opt.decayTime

  for (let i = 0; i < lengthFrames; i++) {
    const t = i / sampleRate
    // Exponential envelope decay
    const envelope = Math.exp(-3.5 * (t / decay))

    // Pre-delay simulation for room/hall (first 10-25ms has discrete early reflections)
    const earlyReflect = t < 0.03 ? (Math.sin(t * 1200) * 0.4) : 0

    // High frequency damping over time
    const damping = Math.exp(-1.5 * t)

    // Pseudo-random noise with stereo decorrelation
    const nLeft = (Math.random() * 2 - 1) * damping + earlyReflect
    const nRight = (Math.random() * 2 - 1) * damping + earlyReflect

    left[i] = nLeft * envelope
    right[i] = nRight * envelope
  }

  return buffer
}

export interface TrackBusNodes {
  inputGain: GainNode
  panner: StereoPannerNode | GainNode
  reverbSendGain: GainNode
  dryGain: GainNode
}

/**
 * Build or manage audio bus chain with master reverb bus.
 */
export class EffectsBusManager {
  private ctx: BaseAudioContext
  private masterOutput: AudioNode
  private convolver: ConvolverNode | null = null
  private reverbWetGain: GainNode | null = null
  private currentPreset: ReverbPreset = 'hall'

  constructor(ctx: BaseAudioContext, destination: AudioNode, initialPreset: ReverbPreset = 'hall') {
    this.ctx = ctx
    this.masterOutput = destination
    this.currentPreset = initialPreset
    this.setupReverbBus()
  }

  private setupReverbBus() {
    this.convolver = this.ctx.createConvolver()
    this.reverbWetGain = this.ctx.createGain()
    this.reverbWetGain.gain.setValueAtTime(0.4, this.ctx.currentTime)

    this.applyPreset(this.currentPreset)

    this.convolver.connect(this.reverbWetGain)
    this.reverbWetGain.connect(this.masterOutput)
  }

  public setPreset(preset: ReverbPreset) {
    this.currentPreset = preset
    this.applyPreset(preset)
  }

  public getPreset(): ReverbPreset {
    return this.currentPreset
  }

  private applyPreset(preset: ReverbPreset) {
    if (!this.convolver || !this.reverbWetGain) return

    if (preset === 'none') {
      this.convolver.buffer = null
      this.reverbWetGain.gain.setTargetAtTime(0, this.ctx.currentTime, 0.02)
    } else {
      const ir = generateImpulseResponse(this.ctx, preset)
      this.convolver.buffer = ir
      this.reverbWetGain.gain.setTargetAtTime(0.45, this.ctx.currentTime, 0.02)
    }
  }

  /**
   * Create an isolated track bus with stereo panning and reverb send.
   */
  public createTrackBus(pan: number = 0, reverbSend: number = 0.25): TrackBusNodes {
    const inputGain = this.ctx.createGain()
    const dryGain = this.ctx.createGain()
    const reverbSendGain = this.ctx.createGain()
    
    reverbSendGain.gain.setValueAtTime(Math.max(0, Math.min(1, reverbSend)), this.ctx.currentTime)
    dryGain.gain.setValueAtTime(1.0, this.ctx.currentTime)

    // Stereo Panner fallback for environments lacking StereoPannerNode
    let pannerNode: StereoPannerNode | GainNode
    if (typeof (this.ctx as any).createStereoPanner === 'function') {
      const p = this.ctx.createStereoPanner()
      p.pan.setValueAtTime(Math.max(-1, Math.min(1, pan)), this.ctx.currentTime)
      pannerNode = p
    } else {
      pannerNode = this.ctx.createGain()
    }

    // Wiring:
    // inputGain -> pannerNode -> dryGain -> masterOutput
    //                         -> reverbSendGain -> convolver (reverb bus)
    inputGain.connect(pannerNode)
    pannerNode.connect(dryGain)
    dryGain.connect(this.masterOutput)

    if (this.convolver) {
      pannerNode.connect(reverbSendGain)
      reverbSendGain.connect(this.convolver)
    }

    return {
      inputGain,
      panner: pannerNode,
      reverbSendGain,
      dryGain,
    }
  }

  /**
   * Disconnect all nodes associated with a TrackBusNodes graph.
   */
  public disconnectTrackBus(bus: TrackBusNodes): void {
    try { bus.inputGain.disconnect() } catch {}
    try { bus.panner.disconnect() } catch {}
    try { bus.dryGain.disconnect() } catch {}
    try { bus.reverbSendGain.disconnect() } catch {}
  }

  /**
   * Cleanly disconnect master reverb bus nodes.
   */
  public dispose(): void {
    if (this.reverbWetGain) {
      try { this.reverbWetGain.disconnect() } catch {}
      this.reverbWetGain = null
    }
    if (this.convolver) {
      try { this.convolver.disconnect() } catch {}
      this.convolver = null
    }
  }
}
