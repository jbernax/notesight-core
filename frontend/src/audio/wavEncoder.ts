/**
 * AudioBuffer to 16-bit PCM WAV Encoder
 * Converts standard Web Audio AudioBuffer (e.g. from OfflineAudioContext)
 * into a downloadable binary WAV Blob ('audio/wav').
 */

function writeString(view: DataView, offset: number, str: string) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i))
  }
}

/**
 * Encodes an AudioBuffer into a standard 16-bit PCM Stereo WAV Blob.
 */
export function encodeAudioBufferToWav(buffer: AudioBuffer): Blob {
  const numChannels = buffer.numberOfChannels
  const sampleRate = buffer.sampleRate
  const format = 1 // 1 = PCM uncompressed
  const bitDepth = 16

  const numFrames = buffer.length
  const numSamples = numFrames * numChannels
  const bytesPerSample = bitDepth / 8
  const blockAlign = numChannels * bytesPerSample
  const byteRate = sampleRate * blockAlign
  const dataSize = numSamples * bytesPerSample
  const headerSize = 44
  const totalLength = headerSize + dataSize

  const arrayBuffer = new ArrayBuffer(totalLength)
  const view = new DataView(arrayBuffer)

  // --- RIFF Chunk Descriptor ---
  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true) // file size - 8
  writeString(view, 8, 'WAVE')

  // --- "fmt " Sub-chunk ---
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true) // SubChunk1Size (16 for PCM)
  view.setUint16(20, format, true) // AudioFormat
  view.setUint16(22, numChannels, true) // NumChannels
  view.setUint32(24, sampleRate, true) // SampleRate
  view.setUint32(28, byteRate, true) // ByteRate
  view.setUint16(32, blockAlign, true) // BlockAlign
  view.setUint16(34, bitDepth, true) // BitsPerSample

  // --- "data" Sub-chunk ---
  writeString(view, 36, 'data')
  view.setUint32(40, dataSize, true)

  // Extract channel samples
  const channelData: Float32Array[] = []
  for (let c = 0; c < numChannels; c++) {
    channelData.push(buffer.getChannelData(c))
  }

  // Interleave channels and write 16-bit integers
  let offset = 44
  for (let i = 0; i < numFrames; i++) {
    for (let c = 0; c < numChannels; c++) {
      let sample = channelData[c][i]
      // Hard clamp between -1.0 and 1.0 to avoid overflow distortion
      if (sample < -1) sample = -1
      else if (sample > 1) sample = 1

      // Convert float [-1.0, 1.0] to signed 16-bit integer [-32768, 32767]
      const int16 = sample < 0 ? Math.round(sample * 0x8000) : Math.round(sample * 0x7fff)
      view.setInt16(offset, int16, true)
      offset += 2
    }
  }

  return new Blob([arrayBuffer], { type: 'audio/wav' })
}

/**
 * Triggers an immediate browser file download for an audio Blob.
 */
export function downloadAudioBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.URL.revokeObjectURL(url)
}
