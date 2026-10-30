/**
 * SoundFont / Sample Engine for NoteSight
 * Generates natural sample instruments (Grand Piano, Nylon Guitar, Cello/Strings, Flute, Brass)
 * using additive harmonic profiles with realistic decay, formant shaping, and micro-timbre modeling.
 * Operates offline, zero network latency, with full AudioBuffer caching.
 */

export interface CachedSampleNote {
  midiNote: number
  buffer: AudioBuffer
}

export interface InstrumentSampleProfile {
  name: string
  attack: number
  decay: number
  sustain: number
  release: number
  harmonics: number[] // relative amplitudes of harmonics [1st (fundamental), 2nd, 3rd, 4th, ...]
  inharmonicity?: number
  vibratoRate?: number
  vibratoDepth?: number
  noiseRatio?: number
  loopStartSec?: number
  loopEndSec?: number
}

export const INSTRUMENT_PROFILES: Record<string, InstrumentSampleProfile> = {
  piano: {
    name: 'Grand Piano',
    attack: 0.003,
    decay: 4.8,
    sustain: 0.0,
    release: 0.45,
    harmonics: [1.0, 0.72, 0.48, 0.32, 0.20, 0.12, 0.08, 0.04],
    inharmonicity: 0.0003,
  },
  choir: {
    name: 'Choir Ensemble',
    attack: 0.05,
    decay: 0.2,
    sustain: 0.95,
    release: 0.35,
    // Formant-shaped harmonics representing open vocal vowels ("Aah" / "Ooh")
    harmonics: [1.0, 0.85, 0.70, 0.55, 0.40, 0.30, 0.22, 0.16, 0.10, 0.06],
    vibratoRate: 5.2,
    vibratoDepth: 0.0045,
    noiseRatio: 0.02, // subtle vocal breath warmth
    loopStartSec: 0.35,
    loopEndSec: 2.35,
  },
  guitar: {
    name: 'Acoustic Guitar',
    attack: 0.006,
    decay: 2.2,
    sustain: 0.0,
    release: 0.3,
    harmonics: [1.0, 0.85, 0.55, 0.4, 0.3, 0.15, 0.08, 0.05],
    inharmonicity: 0.0007,
    noiseRatio: 0.04,
  },
  strings: {
    name: 'Strings Ensemble',
    attack: 0.08,
    decay: 0.3,
    sustain: 0.85,
    release: 0.38,
    harmonics: [1.0, 0.9, 0.75, 0.6, 0.5, 0.4, 0.3, 0.2, 0.15],
    vibratoRate: 5.5,
    vibratoDepth: 0.004,
    loopStartSec: 0.4,
    loopEndSec: 2.4,
  },
  flute: {
    name: 'Concert Flute',
    attack: 0.04,
    decay: 0.2,
    sustain: 0.9,
    release: 0.15,
    harmonics: [1.0, 0.35, 0.18, 0.06, 0.02],
    vibratoRate: 5.0,
    vibratoDepth: 0.006,
    noiseRatio: 0.035, // breath chiff
    loopStartSec: 0.3,
    loopEndSec: 2.3,
  },
  brass: {
    name: 'Brass Section',
    attack: 0.035,
    decay: 0.25,
    sustain: 0.8,
    release: 0.2,
    harmonics: [1.0, 0.8, 0.85, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1],
    loopStartSec: 0.35,
    loopEndSec: 2.3,
  },
}

/**
 * Maps frequency in Hz to closest MIDI note number.
 */
export function freqToMidi(freq: number): number {
  return Math.round(69 + 12 * Math.log2(freq / 440))
}

/**
 * Maps MIDI note number to frequency in Hz.
 */
export function midiToFreq(midi: number): number {
  return 440 * Math.pow(2, (midi - 69) / 12)
}

/**
 * SoundFont sampler bank with pre-rendered AudioBuffer cache.
 */
export class SampleBank {
  private static instance: SampleBank
  // Key: `${instrument}_${midiNote}`
  private bufferCache: Map<string, AudioBuffer> = new Map()

  public static getInstance(): SampleBank {
    if (!SampleBank.instance) {
      SampleBank.instance = new SampleBank()
    }
    return SampleBank.instance
  }

  /**
   * Synthesize or retrieve an AudioBuffer for an instrument pitch.
   * Renders realistic physical models with harmonic decay and overtone dispersion.
   */
  public getOrCreateSample(
    ctx: BaseAudioContext,
    instrument: string,
    midiNote: number
  ): AudioBuffer {
    const key = `${instrument}_${midiNote}`
    const existing = this.bufferCache.get(key)
    if (existing) {
      return existing
    }

    const profile = INSTRUMENT_PROFILES[instrument] || INSTRUMENT_PROFILES.piano
    const sampleRate = ctx.sampleRate
    const baseFreq = midiToFreq(midiNote)

    // Render duration depends on profile decay & sustain characteristics
    // 6.5s for acoustic piano ensures long held notes (half & whole notes at slow BPM) keep sounding
    const totalSec = profile.sustain > 0 ? 3.0 : instrument === 'piano' ? 6.5 : instrument === 'guitar' ? 4.5 : 4.0
    const numFrames = Math.floor(sampleRate * totalSec)

    const buffer = ctx.createBuffer(2, numFrames, sampleRate)
    const left = buffer.getChannelData(0)
    const right = buffer.getChannelData(1)

    const harmonics = profile.harmonics
    const inharm = profile.inharmonicity || 0
    const isSustained = profile.sustain > 0

    // Pre-calculate harmonic frequencies and damping coefficients outside the frame loop
    const harmonicData = harmonics.map((amp, idx) => {
      const harmonicIndex = idx + 1
      const partialFreq = baseFreq * harmonicIndex * Math.sqrt(1 + inharm * harmonicIndex * harmonicIndex)
      // Sustained instruments (choir, strings, flute, brass) must maintain full harmonic presence during sustain
      // Piano has minimal fundamental damping (-0.05) so the singing pitch holds for seconds, with higher overtones damping realistically
      let dampingCoeff = 0
      if (!isSustained) {
        dampingCoeff = instrument === 'piano'
          ? (harmonicIndex === 1 ? -0.05 : -0.22 * harmonicIndex)
          : -0.32 * harmonicIndex
      }
      return {
        amp,
        omega: 2 * Math.PI * partialFreq,
        dampingCoeff,
      }
    })

    const hasVibrato = !!(profile.vibratoRate && profile.vibratoDepth)
    const vibratoRate = profile.vibratoRate || 0
    const vibratoDepth = profile.vibratoDepth || 0

    for (let i = 0; i < numFrames; i++) {
      const t = i / sampleRate

      // Envelope calculation
      let env = 0
      if (t < profile.attack) {
        env = t / Math.max(0.001, profile.attack)
      } else if (isSustained) {
        const decayTime = profile.decay
        const sustainLevel = profile.sustain
        if (t < profile.attack + decayTime) {
          const decayProgress = (t - profile.attack) / decayTime
          env = 1.0 - (1.0 - sustainLevel) * decayProgress
        } else {
          // Steady sustained amplitude throughout looping region (zero artificial decay)
          env = sustainLevel
        }
      } else {
        // Percussive natural decaying envelope
        const decayAge = t - profile.attack
        if (instrument === 'piano') {
          // Resonant grand piano soundboard: initial strike dissipation + warm singing fundamental
          env = 0.45 * Math.exp(-decayAge / 2.2) + 0.55 * Math.exp(-decayAge / 7.0)
        } else if (instrument === 'guitar') {
          env = 0.60 * Math.exp(-decayAge / 1.5) + 0.40 * Math.exp(-decayAge / 4.0)
        } else {
          env = Math.exp(-1.2 * (decayAge / profile.decay))
        }
      }

      // Additive synthesis with pre-computed harmonic frequencies
      let sample = 0
      const vibratoPhase = hasVibrato ? Math.sin(2 * Math.PI * vibratoRate * t) * vibratoDepth : 0
      for (let h = 0; h < harmonicData.length; h++) {
        const hd = harmonicData[h]
        const damping = hd.dampingCoeff ? Math.exp(hd.dampingCoeff * t) : 1.0
        sample += hd.amp * damping * Math.sin(hd.omega * t + vibratoPhase * (h + 1))
      }

      // Subtle breath or plucking noise component
      if (profile.noiseRatio && t < 0.12) {
        const noiseEnvelope = Math.exp(-35 * t)
        sample += (Math.random() * 2 - 1) * profile.noiseRatio * noiseEnvelope
      }

      // Normalization factor based on sum of harmonic amplitudes
      const normAmp = 0.35 / (harmonics.reduce((a, b) => a + b, 0) * 0.45 || 1)
      const finalVal = sample * env * normAmp

      // Stereo spread: slight phase difference
      left[i] = finalVal
      right[i] = finalVal
    }

    // Smooth crossfade at loop boundary for sustained instruments to ensure click-free looping
    if (isSustained && profile.loopStartSec && profile.loopEndSec) {
      const loopStartIdx = Math.floor(profile.loopStartSec * sampleRate)
      const loopEndIdx = Math.min(numFrames - 1, Math.floor(profile.loopEndSec * sampleRate))
      const xfadeSamples = Math.min(1024, Math.floor(sampleRate * 0.025))
      if (loopEndIdx - xfadeSamples > loopStartIdx) {
        for (let x = 0; x < xfadeSamples; x++) {
          const tailIdx = loopEndIdx - xfadeSamples + x
          const headIdx = loopStartIdx + x
          const crossfade = x / xfadeSamples
          left[tailIdx] = left[tailIdx] * (1 - crossfade) + left[headIdx] * crossfade
          right[tailIdx] = right[tailIdx] * (1 - crossfade) + right[headIdx] * crossfade
        }
      }
    }

    // Micro-fade at buffer end to guarantee zero truncation click
    const fadeSamples = Math.min(512, Math.floor(numFrames * 0.05))
    for (let f = 0; f < fadeSamples; f++) {
      const idx = numFrames - 1 - f
      const fadeGain = f / fadeSamples
      left[idx] *= fadeGain
      right[idx] *= fadeGain
    }

    this.bufferCache.set(key, buffer)
    return buffer
  }

  /**
   * Pre-warm audio sample cache for a list of pitch requests to eliminate
   * on-the-fly synthesis CPU spikes during playback.
   */
  public prewarmSamples(
    ctx: BaseAudioContext,
    requests: { instrument: string; midiNote: number }[]
  ): void {
    if (!ctx || !requests || requests.length === 0) return
    for (const req of requests) {
      if (!req.instrument || typeof req.midiNote !== 'number') continue
      const key = `${req.instrument}_${req.midiNote}`
      if (!this.bufferCache.has(key)) {
        try {
          this.getOrCreateSample(ctx, req.instrument, req.midiNote)
        } catch (err) {
          console.warn(`Failed to pre-warm sample for ${key}:`, err)
        }
      }
    }
  }

  /**
   * Check if sample is already generated and cached.
   */
  public hasSample(instrument: string, midiNote: number): boolean {
    return this.bufferCache.has(`${instrument}_${midiNote}`)
  }

  /**
   * Clear memory cache when unmounting or switching heavy scores.
   */
  public clearCache() {
    this.bufferCache.clear()
  }
}
