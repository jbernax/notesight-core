<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import type { OpenSheetMusicDisplay } from 'opensheetmusicdisplay'
import { ScorePlaybackController } from '../audio/scorePlayer'
import { apiFetch } from '../services/apiClient'
import { Play, Pause, Square, ZoomIn, ZoomOut, ExternalLink, Music2 } from 'lucide-vue-next'
import { sanitizeMusicXmlLyrics } from '../utils/musicxmlLyricsSanitizer'

const route = useRoute()
const token = route.params.token as string

const isLoading = ref(true)
const errorMessage = ref<string | null>(null)
const isPlaying = ref(false)
const zoomLevel = ref(0.9)
const containerRef = ref<HTMLDivElement | null>(null)

let osmd: OpenSheetMusicDisplay | null = null
const player = new ScorePlaybackController()
let unsubscribeState: (() => void) | null = null

const fetchScore = async () => {
  isLoading.value = true
  errorMessage.value = null
  try {
    const res = await apiFetch(`/api/scores/share/${token}`)
    if (!res.ok) {
      throw new Error('Score not found or expired.')
    }
    const data = await res.json()
    isLoading.value = false
    await nextTick()
    await renderOsm(data.musicxml, data.allow_playback)
  } catch (err: any) {
    errorMessage.value = err.message || 'Error loading score.'
  } finally {
    if (isLoading.value) {
      isLoading.value = false
    }
  }
}

const renderOsm = async (xml: string, canPlay: boolean) => {
  if (!containerRef.value) {
    await nextTick()
  }
  if (!containerRef.value || !xml) return
  try {
    let cleanXml = sanitizeMusicXmlLyrics(xml.trim())
    if (!cleanXml.startsWith('<?xml')) {
      cleanXml = '<?xml version="1.0" encoding="utf-8"?>\n' + cleanXml
    }

    containerRef.value.innerHTML = ''
    const { OpenSheetMusicDisplay: OSMDClass } = await import('opensheetmusicdisplay')
    osmd = new OSMDClass(containerRef.value, {
      autoResize: true,
      backend: 'svg',
      drawTitle: true,
      drawSubtitle: true,
      drawComposer: true,
      drawingParameters: 'compact',
      pageFormat: 'Endless',
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
    osmd.EngravingRules.LyricsHeight = 1.6

    osmd.zoom = zoomLevel.value
    await osmd.load(cleanXml)
    osmd.render()

    if (canPlay) {
      player.loadScore(osmd)
      unsubscribeState = player.onStateChange((snap) => {
        isPlaying.value = snap.status === 'playing'
      })
    }
  } catch (err: any) {
    console.error('Failed to render embedded score:', err)
    errorMessage.value = err?.message ? `Failed to render sheet music: ${err.message}` : 'Failed to render sheet music notation.'
  }
}

const togglePlay = () => {
  if (isPlaying.value) {
    player.pause()
  } else {
    player.play()
  }
}

const stopPlay = () => {
  player.stop()
}

const zoomIn = () => {
  zoomLevel.value = Math.min(1.8, zoomLevel.value + 0.1)
  if (osmd) {
    osmd.zoom = zoomLevel.value
    osmd.render()
  }
}

const zoomOut = () => {
  zoomLevel.value = Math.max(0.4, zoomLevel.value - 0.1)
  if (osmd) {
    osmd.zoom = zoomLevel.value
    osmd.render()
  }
}

onMounted(() => {
  fetchScore()
})

onUnmounted(() => {
  if (unsubscribeState) unsubscribeState()
  player.stop()
  if (osmd) {
    osmd.clear()
    osmd = null
  }
})
</script>

<template>
  <div class="embed-wrapper">
    <div v-if="isLoading" class="center-msg">
      <div class="spinner"></div>
    </div>
    <div v-else-if="errorMessage" class="center-msg error">
      <p>{{ errorMessage }}</p>
    </div>
    <div v-else class="embed-canvas-scroller">
      <div ref="containerRef" class="sheet-container"></div>
    </div>

    <!-- Compact Bottom Controls -->
    <div class="embed-bottom-bar">
      <div class="playback-controls">
        <button class="embed-btn play-btn" @click="togglePlay" :title="isPlaying ? 'Pause' : 'Play'">
          <Pause v-if="isPlaying" :size="15" />
          <Play v-else :size="15" />
        </button>
        <button class="embed-btn" @click="stopPlay" title="Stop">
          <Square :size="13" />
        </button>
      </div>

      <div class="zoom-controls">
        <button class="embed-btn" @click="zoomOut" title="Zoom out"><ZoomOut :size="14" /></button>
        <button class="embed-btn" @click="zoomIn" title="Zoom in"><ZoomIn :size="14" /></button>
      </div>

      <a :href="`/score/share/${token}`" target="_blank" rel="noopener" class="watermark-link" title="Open in NoteSight">
        <Music2 :size="14" class="text-indigo-400" />
        <span>NoteSight</span>
        <ExternalLink :size="10" />
      </a>
    </div>
  </div>
</template>

<style scoped>
.embed-wrapper {
  width: 100vw;
  height: 100vh;
  margin: 0;
  padding: 0;
  overflow: hidden;
  background: #ffffff;
  display: flex;
  flex-direction: column;
}

.embed-canvas-scroller {
  flex: 1;
  overflow: auto;
  display: flex;
  justify-content: center;
  padding: 1rem 0.5rem 3.5rem 0.5rem;
}

.sheet-container {
  width: 100%;
  max-width: 900px;
  min-width: 0;
}

.center-msg {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: sans-serif;
  color: #64748b;
}

.spinner {
  width: 2rem;
  height: 2rem;
  border: 3px solid rgba(99, 102, 241, 0.2);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.embed-bottom-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 2.75rem;
  background: rgba(15, 23, 42, 0.95);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 1rem;
  z-index: 50;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.playback-controls, .zoom-controls {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.embed-btn {
  background: #1e293b;
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #f1f5f9;
  border-radius: 0.25rem;
  padding: 0.3rem 0.5rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.embed-btn:hover {
  background: #334155;
}

.play-btn {
  background: #6366f1;
  border-color: #4f46e5;
}

.play-btn:hover {
  background: #4f46e5;
}

.watermark-link {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-family: sans-serif;
  font-size: 0.75rem;
  color: #94a3b8;
  text-decoration: none;
  font-weight: 500;
}

.watermark-link:hover {
  color: #ffffff;
}
</style>
