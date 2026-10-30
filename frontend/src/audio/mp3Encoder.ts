/**
 * AudioBuffer to MP3 Encoder using pure JavaScript @breezystack/lamejs.
 * Converts Web Audio AudioBuffer (e.g. from OfflineAudioContext)
 * into a lightweight, highly compressed MP3 Blob ('audio/mpeg').
 */

import { Mp3Encoder } from '@breezystack/lamejs'

export interface Mp3EncodingOptions {
  /**
   * Bitrate in kbps (e.g. 96, 128, 160, 192, 256, 320).
   * Default: 128 kbps (crystal clear practice audio with ~91% size savings vs WAV).
   */
  bitrate?: number

  /**
   * Number of channels: 1 (mono) or 2 (stereo).
   * Default matches the buffer's channel count, clamped to 1 or 2.
   */
  channels?: 1 | 2

  /**
   * Optional progress callback reporting 0.0 to 1.0 during encoding.
   */
  onProgress?: (progress: number) => void
}

/**
 * Encodes an AudioBuffer into a compressed MP3 Blob.
 * Non-blocking: periodically yields to the event loop so the UI remains fluid.
 */
export async function encodeAudioBufferToMp3(
  buffer: AudioBuffer,
  options: Mp3EncodingOptions = {}
): Promise<Blob> {
  const sampleRate = buffer.sampleRate
  const channels = options.channels
    ? Math.min(buffer.numberOfChannels, options.channels) as 1 | 2
    : (Math.min(buffer.numberOfChannels, 2) as 1 | 2)
  const bitrate = options.bitrate || 128

  const encoder = new Mp3Encoder(channels, sampleRate, bitrate)
  const numFrames = buffer.length

  const leftChannel = buffer.getChannelData(0)
  const rightChannel = channels > 1 && buffer.numberOfChannels > 1
    ? buffer.getChannelData(1)
    : leftChannel

  const mp3DataChunks: Uint8Array[] = []
  const sampleBlockSize = 1152 // Standard MPEG-1 Layer 3 frame size
  const yieldInterval = sampleBlockSize * 25 // Yield roughly every ~28,800 samples (~0.65s of audio)

  let samplesProcessedSinceYield = 0

  for (let i = 0; i < numFrames; i += sampleBlockSize) {
    const chunkLength = Math.min(sampleBlockSize, numFrames - i)
    const leftInt16 = new Int16Array(chunkLength)
    const rightInt16 = channels > 1 ? new Int16Array(chunkLength) : undefined

    for (let j = 0; j < chunkLength; j++) {
      const idx = i + j
      // Clamp left
      let sL = leftChannel[idx]
      if (sL < -1) sL = -1
      else if (sL > 1) sL = 1
      leftInt16[j] = sL < 0 ? Math.round(sL * 0x8000) : Math.round(sL * 0x7fff)

      // Clamp right if stereo
      if (rightInt16) {
        let sR = rightChannel[idx]
        if (sR < -1) sR = -1
        else if (sR > 1) sR = 1
        rightInt16[j] = sR < 0 ? Math.round(sR * 0x8000) : Math.round(sR * 0x7fff)
      }
    }

    const mp3chunk = channels > 1
      ? encoder.encodeBuffer(leftInt16, rightInt16!)
      : encoder.encodeBuffer(leftInt16)

    if (mp3chunk && mp3chunk.length > 0) {
      mp3DataChunks.push(mp3chunk)
    }

    samplesProcessedSinceYield += chunkLength
    if (samplesProcessedSinceYield >= yieldInterval) {
      samplesProcessedSinceYield = 0
      if (options.onProgress) {
        options.onProgress(Math.min(0.99, (i + chunkLength) / numFrames))
      }
      // Small yield to prevent main thread starvation
      await new Promise((resolve) => setTimeout(resolve, 0))
    }
  }

  const finalChunk = encoder.flush()
  if (finalChunk && finalChunk.length > 0) {
    mp3DataChunks.push(finalChunk)
  }

  if (options.onProgress) {
    options.onProgress(1.0)
  }

  return new Blob(mp3DataChunks as BlobPart[], { type: 'audio/mpeg' })
}
