<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  MessageSquare,
  CheckCircle2,
  Circle,
  Trash2,
  X,
  Send,
  Tag
} from 'lucide-vue-next'
import type { ScoreAnnotation } from '../../composables/useScoreAnnotations'

const props = defineProps<{
  isOpen: boolean
  jobId: string
  currentMeasureNum: number
  annotations: ScoreAnnotation[]
  isLoading: boolean
  shareToken?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'selectMeasure', measureNum: number): void
  (e: 'create', payload: {
    measure_number: number
    annotation_type: 'comment' | 'fingering' | 'rehearsal' | 'technique'
    content: string
    color: string
  }): void
  (e: 'update', annotationId: string, update: { is_resolved?: boolean; content?: string }): void
  (e: 'delete', annotationId: string): void
}>()

const activeTab = ref<'all' | 'comment' | 'fingering' | 'rehearsal' | 'technique'>('all')
const newType = ref<'comment' | 'fingering' | 'rehearsal' | 'technique'>('comment')
const newContent = ref('')
const selectedColor = ref('#6366f1')

const colorOptions = [
  { name: 'Indigo', hex: '#6366f1' },
  { name: 'Emerald', hex: '#10b981' },
  { name: 'Amber', hex: '#f59e0b' },
  { name: 'Rose', hex: '#ec4899' },
  { name: 'Cyan', hex: '#06b6d4' },
]

const filteredList = computed(() => {
  if (activeTab.value === 'all') {
    return props.annotations
  }
  return props.annotations.filter(a => a.annotation_type === activeTab.value)
})

const submitNewAnnotation = () => {
  const content = newContent.value.trim()
  if (!content) return

  emit('create', {
    measure_number: props.currentMeasureNum,
    annotation_type: newType.value,
    content,
    color: selectedColor.value,
  })

  newContent.value = ''
}

const formatTypeLabel = (type: string) => {
  switch (type) {
    case 'fingering': return 'Fingering'
    case 'rehearsal': return 'Rehearsal'
    case 'technique': return 'Technique'
    default: return 'Comment'
  }
}
</script>

<template>
  <aside v-if="isOpen" class="annotations-drawer">
    <!-- Drawer Header -->
    <div class="drawer-header">
      <div class="header-title-row">
        <MessageSquare :size="18" class="text-indigo-400" />
        <span class="drawer-title">{{ $t('studio.annotations.title') }}</span>
        <span class="count-pill">{{ annotations.length }}</span>
      </div>
      <button class="drawer-close-btn" @click="emit('close')" :title="$t('common.close')">
        <X :size="16" />
      </button>
    </div>

    <!-- Filter Tabs -->
    <div class="filter-strip">
      <button
        class="filter-tab"
        :class="{ active: activeTab === 'all' }"
        @click="activeTab = 'all'"
      >
        {{ $t('studio.annotations.all') }}
      </button>
      <button
        class="filter-tab"
        :class="{ active: activeTab === 'comment' }"
        @click="activeTab = 'comment'"
      >
        {{ $t('studio.annotations.comments') }}
      </button>
      <button
        class="filter-tab"
        :class="{ active: activeTab === 'fingering' }"
        @click="activeTab = 'fingering'"
      >
        {{ $t('studio.annotations.fingerings') }}
      </button>
      <button
        class="filter-tab"
        :class="{ active: activeTab === 'rehearsal' }"
        @click="activeTab = 'rehearsal'"
      >
        {{ $t('studio.annotations.rehearsal') }}
      </button>
    </div>

    <!-- Quick Note Creator -->
    <div class="create-annotation-card">
      <div class="create-header">
        <span class="target-measure-badge">
          {{ $t('studio.statusBar.measure') }} {{ currentMeasureNum }}
        </span>
        <div class="type-picker">
          <select v-model="newType" class="type-select">
            <option value="comment">💬 {{ $t('studio.annotations.comments') }}</option>
            <option value="fingering">🖐️ {{ $t('studio.annotations.fingerings') }}</option>
            <option value="rehearsal">🎯 {{ $t('studio.annotations.rehearsal') }}</option>
            <option value="technique">⚡ {{ $t('studio.annotations.technique') }}</option>
          </select>
        </div>
      </div>

      <textarea
        v-model="newContent"
        rows="2"
        :placeholder="$t('studio.annotations.placeholder', { measure: currentMeasureNum })"
        class="annotation-textarea"
        @keydown.enter.ctrl="submitNewAnnotation"
      ></textarea>

      <div class="create-footer">
        <div class="color-palette">
          <button
            v-for="c in colorOptions"
            :key="c.hex"
            class="color-dot"
            :style="{ backgroundColor: c.hex }"
            :class="{ active: selectedColor === c.hex }"
            @click="selectedColor = c.hex"
            :title="c.name"
          ></button>
        </div>
        <button
          class="submit-ann-btn"
          :disabled="!newContent.trim()"
          @click="submitNewAnnotation"
        >
          <Send :size="13" />
          <span>{{ $t('studio.annotations.add') }}</span>
        </button>
      </div>
    </div>

    <!-- Annotations List -->
    <div class="annotations-feed">
      <div v-if="filteredList.length === 0" class="empty-state">
        <Tag :size="24" class="text-slate-600 mb-2" />
        <p class="empty-text">{{ $t('studio.annotations.noAnnotations') }}</p>
        <span class="empty-hint">{{ $t('studio.annotations.emptyHint') }}</span>
      </div>

      <div
        v-for="item in filteredList"
        :key="item.id"
        class="annotation-item"
        :class="{ resolved: item.is_resolved }"
        :style="{ borderLeftColor: item.color }"
      >
        <div class="item-header">
          <button
            class="measure-jump-btn"
            @click="emit('selectMeasure', item.measure_number)"
            title="Jump to this measure"
          >
            {{ $t('studio.statusBar.measure') }} {{ item.measure_number }}
          </button>
          <span class="type-tag" :style="{ color: item.color }">
            {{ formatTypeLabel(item.annotation_type) }}
          </span>
          <span class="author-name">{{ item.author_name }}</span>
        </div>

        <p class="item-content">{{ item.content }}</p>

        <div class="item-footer">
          <button
            class="resolve-toggle-btn"
            @click="emit('update', item.id, { is_resolved: !item.is_resolved })"
            :title="item.is_resolved ? 'Re-open' : 'Mark resolved'"
          >
            <CheckCircle2 v-if="item.is_resolved" :size="14" class="text-emerald-400" />
            <Circle v-else :size="14" class="text-slate-500" />
            <span>{{ item.is_resolved ? 'Resolved' : 'Resolve' }}</span>
          </button>

          <button
            class="item-delete-btn"
            @click="emit('delete', item.id)"
            title="Delete annotation"
          >
            <Trash2 :size="13" />
          </button>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.annotations-drawer {
  width: 320px;
  background: var(--bg-card);
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  box-shadow: var(--shadow-lg);
  z-index: 30;
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.875rem 1rem;
  border-bottom: 1px solid var(--border);
}

.header-title-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--color-primary);
}

.drawer-title {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-primary);
}

.count-pill {
  font-size: 0.7rem;
  background: var(--color-primary-light);
  color: var(--color-primary);
  padding: 0.1rem 0.45rem;
  border-radius: 9999px;
  font-weight: 600;
}

.drawer-close-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.375rem;
}

.drawer-close-btn:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.filter-strip {
  display: flex;
  gap: 0.25rem;
  padding: 0.5rem 0.75rem;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
}

.filter-tab {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-size: 0.75rem;
  padding: 0.35rem 0.65rem;
  min-height: 32px;
  border-radius: 0.375rem;
  cursor: pointer;
  white-space: nowrap;
}

.filter-tab.active {
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border);
  font-weight: 600;
}

.create-annotation-card {
  padding: 0.75rem 1rem;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.create-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.target-measure-badge {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-primary);
  background: var(--color-primary-light);
  padding: 0.15rem 0.5rem;
  border-radius: 0.25rem;
}

.type-select {
  background: var(--input-bg);
  border: 1px solid var(--input-border);
  color: var(--text-primary);
  font-size: 0.75rem;
  padding: 0.25rem 0.5rem;
  border-radius: 0.25rem;
  outline: none;
}

.annotation-textarea {
  background: var(--input-bg);
  border: 1px solid var(--input-border);
  color: var(--text-primary);
  font-size: 0.8rem;
  border-radius: 0.375rem;
  padding: 0.5rem;
  resize: none;
  outline: none;
}

.create-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.color-palette {
  display: flex;
  gap: 0.45rem;
}

.color-dot {
  width: 1.25rem;
  height: 1.25rem;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
}

.color-dot.active {
  border-color: var(--text-primary);
  transform: scale(1.15);
}

.submit-ann-btn {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  background: var(--color-primary);
  color: #ffffff;
  border: none;
  border-radius: 0.375rem;
  padding: 0.4rem 0.75rem;
  min-height: 36px;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
}

.submit-ann-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.annotations-feed {
  flex: 1;
  overflow-y: auto;
  padding: 0.75rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2.5rem 1rem;
  text-align: center;
  color: var(--text-muted);
}

.empty-text {
  font-size: 0.85rem;
  color: var(--text-secondary);
  margin: 0.5rem 0 0 0;
}

.empty-hint {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-top: 0.25rem;
}

.annotation-item {
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-left-width: 4px;
  border-radius: 0.375rem;
  padding: 0.65rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  transition: opacity 0.15s;
}

.annotation-item.resolved {
  opacity: 0.6;
}

.item-header {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.measure-jump-btn {
  background: var(--color-primary-light);
  border: none;
  color: var(--color-primary);
  font-size: 0.7rem;
  padding: 0.15rem 0.45rem;
  border-radius: 0.25rem;
  cursor: pointer;
  font-weight: 600;
}

.measure-jump-btn:hover {
  opacity: 0.85;
}

.type-tag {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
}

.author-name {
  margin-left: auto;
  font-size: 0.7rem;
  color: var(--text-muted);
}

.item-content {
  font-size: 0.8rem;
  color: var(--text-primary);
  line-height: 1.4;
  margin: 0;
  word-break: break-word;
}

.item-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 0.25rem;
  border-top: 1px solid var(--border-light);
}

.resolve-toggle-btn {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-size: 0.75rem;
  cursor: pointer;
  padding: 0.25rem 0;
}

.item-delete-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 0.25rem;
  border-radius: 0.25rem;
}

.item-delete-btn:hover {
  color: var(--color-danger);
}

@media (max-width: 768px) {
  .annotations-drawer {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    width: 100%;
    max-width: 100vw;
    height: 75vh;
    border-radius: 16px 16px 0 0;
    z-index: 10000;
    padding-bottom: calc(var(--sab) + 12px);
  }
}
</style>
