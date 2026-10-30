<script setup lang="ts">
import { ref, computed } from 'vue'
import { FileText, AlertCircle, X } from 'lucide-vue-next'

const props = defineProps<{
  jobId?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const splitSize = ref<'compact' | 'standard' | 'wide'>('compact')

const originalSourceUrl = computed(() => {
  if (!props.jobId) return null
  const token = localStorage.getItem('token')
  return `/api/jobs/${props.jobId}/original${token ? `?token=${encodeURIComponent(token)}` : ''}`
})
</script>

<template>
  <div class="review-split-pane" :class="`size-${splitSize}`" aria-label="Original sheet music reference">
    <div class="split-pane-header">
      <div class="pane-title">
        <FileText :size="14" />
        <span>{{ $t('studio.reviewSplit.originalScan') }}</span>
      </div>
      <div class="header-right-tools">
        <div class="width-selector" title="Adjust comparison split width">
          <button
            type="button"
            class="width-pill-btn"
            :class="{ active: splitSize === 'compact' }"
            @click="splitSize = 'compact'"
          >
            35%
          </button>
          <button
            type="button"
            class="width-pill-btn"
            :class="{ active: splitSize === 'standard' }"
            @click="splitSize = 'standard'"
          >
            45%
          </button>
          <button
            type="button"
            class="width-pill-btn"
            :class="{ active: splitSize === 'wide' }"
            @click="splitSize = 'wide'"
          >
            55%
          </button>
        </div>
        <button type="button" class="close-split-btn" @click="emit('close')" title="Close split view">
          <X :size="14" />
        </button>
      </div>
    </div>

    <div v-if="originalSourceUrl" class="split-content-frame">
      <iframe
        :src="originalSourceUrl"
        class="source-iframe"
        title="Original Sheet Music Scan"
      ></iframe>
    </div>
    <div v-else class="split-empty-state">
      <AlertCircle :size="28" />
      <p>{{ $t('studio.reviewSplit.noOriginalDoc') }}</p>
    </div>
  </div>
</template>

<style scoped>
.review-split-pane {
  display: flex;
  flex-direction: column;
  width: 35%;
  min-width: 260px;
  max-width: 500px;
  height: 100%;
  background: var(--bg-card, #151b28);
  border-right: 2px solid var(--border, #242f48);
  flex-shrink: 0;
  z-index: 5;
  transition: width 0.2s ease, max-width 0.2s ease;
}

.review-split-pane.size-compact {
  width: 35%;
  max-width: 480px;
}

.review-split-pane.size-standard {
  width: 45%;
  max-width: 650px;
}

.review-split-pane.size-wide {
  width: 55%;
  max-width: 800px;
}

.split-pane-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: rgba(12, 16, 23, 0.85);
  border-bottom: 1px solid var(--border, #242f48);
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text-primary, #ffffff);
}

.pane-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #a5b4fc;
}

.header-right-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.width-selector {
  display: inline-flex;
  align-items: center;
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #242f48);
  border-radius: 4px;
  padding: 1px;
  gap: 1px;
}

.width-pill-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary, #94a3b8);
  font-size: 0.68rem;
  font-weight: 600;
  padding: 2px 5px;
  border-radius: 3px;
  cursor: pointer;
  transition: all 0.12s ease;
}

.width-pill-btn:hover {
  color: var(--text-primary, #ffffff);
}

.width-pill-btn.active {
  background: var(--color-primary, #6366f1);
  color: #ffffff;
}

.close-split-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary, #94a3b8);
  padding: 3px;
  border-radius: 4px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}

.close-split-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

.split-content-frame {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: #000;
}

.source-iframe {
  width: 100%;
  height: 100%;
  border: none;
  background: #ffffff;
}

.split-empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px;
  text-align: center;
  color: var(--text-secondary, #94a3b8);
  gap: 12px;
}

@media (max-width: 768px) {
  .review-split-pane {
    position: fixed;
    inset: 0;
    width: 100% !important;
    max-width: 100% !important;
    height: 100% !important;
    z-index: 9500;
    border-right: none;
    padding-top: var(--sat);
    padding-bottom: var(--sab);
  }
}
</style>
