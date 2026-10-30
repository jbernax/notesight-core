<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  Share2,
  Copy,
  Check,
  Code,
  Eye,
  Trash2,
  Globe,
  Sparkles,
  X
} from 'lucide-vue-next'
import { showToast } from '../../composables/useToast'
import { apiFetch } from '../../services/apiClient'

const props = defineProps<{
  isOpen: boolean
  jobId: string
  scoreTitle?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const isLoading = ref(false)
const shareToken = ref<string | null>(null)
const allowPlayback = ref(true)
const allowFork = ref(true)
const viewCount = ref(0)
const hasCopiedLink = ref(false)
const hasCopiedEmbed = ref(false)
const showRevokeConfirm = ref(false)

const shareUrl = computed(() => {
  if (!shareToken.value) return ''
  return `${window.location.origin}/score/share/${shareToken.value}`
})

const embedSnippet = computed(() => {
  if (!shareToken.value) return ''
  const embedUrl = `${window.location.origin}/score/embed/${shareToken.value}`
  return `<iframe src="${embedUrl}" width="100%" height="600" frameborder="0" allow="autoplay; fullscreen" loading="lazy"></iframe>`
})

const fetchShareSettings = async () => {
  if (!props.jobId) return
  isLoading.value = true
  try {
    const res = await apiFetch(`/api/jobs/${props.jobId}/share`)
    if (res.ok) {
      const data = await res.json()
      shareToken.value = data.share_token
      allowPlayback.value = data.allow_playback
      allowFork.value = data.allow_fork
      viewCount.value = data.view_count || 0
    } else {
      shareToken.value = null
    }
  } catch (err) {
    console.error('Failed to load share settings:', err)
  } finally {
    isLoading.value = false
  }
}

watch(
  () => [props.isOpen, props.jobId],
  ([open]) => {
    if (open) {
      fetchShareSettings()
    }
  },
  { immediate: true }
)

const createOrUpdateShare = async (forceCreate: boolean = false) => {
  isLoading.value = true
  try {
    const res = await apiFetch(`/api/jobs/${props.jobId}/share`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        allow_playback: allowPlayback.value,
        allow_fork: allowFork.value,
      }),
    })

    if (res.ok) {
      const data = await res.json()
      shareToken.value = data.share_token
      allowPlayback.value = data.allow_playback
      allowFork.value = data.allow_fork
      viewCount.value = data.view_count || 0
      showToast({
        title: forceCreate ? 'Share Link Created' : 'Permissions Updated',
        message: 'Your public score settings have been saved.',
        type: 'success',
      })
    } else {
      showToast({
        title: 'Share Failed',
        message: 'Could not create or update share link.',
        type: 'error',
      })
    }
  } catch (err) {
    console.error('Failed to create/update share:', err)
  } finally {
    isLoading.value = false
  }
}

const revokeShare = async () => {
  isLoading.value = true
  showRevokeConfirm.value = false
  try {
    const res = await apiFetch(`/api/jobs/${props.jobId}/share`, {
      method: 'DELETE',
    })
    if (res.ok) {
      shareToken.value = null
      showToast({
        title: 'Share Link Revoked',
        message: 'This score is now private.',
        type: 'info',
      })
    }
  } catch (err) {
    console.error('Failed to revoke share link:', err)
  } finally {
    isLoading.value = false
  }
}

const copyShareUrl = async () => {
  if (!shareUrl.value) return
  await navigator.clipboard.writeText(shareUrl.value)
  hasCopiedLink.value = true
  showToast({
    title: 'Link Copied',
    message: 'Public score URL copied to clipboard!',
    type: 'success',
  })
  setTimeout(() => {
    hasCopiedLink.value = false
  }, 2500)
}

const copyEmbedCode = async () => {
  if (!embedSnippet.value) return
  await navigator.clipboard.writeText(embedSnippet.value)
  hasCopiedEmbed.value = true
  showToast({
    title: 'Embed Code Copied',
    message: 'HTML <iframe> code snippet copied to clipboard!',
    type: 'success',
  })
  setTimeout(() => {
    hasCopiedEmbed.value = false
  }, 2500)
}
</script>

<template>
  <div v-if="isOpen" class="share-modal-backdrop" @click.self="emit('close')">
    <div class="share-modal-card">
      <!-- Modal Header -->
      <div class="modal-header">
        <div class="header-title-row">
          <div class="icon-bubble">
            <Share2 :size="18" class="text-indigo-400" />
          </div>
          <div>
            <h3 class="modal-title">{{ $t('share.title') }}</h3>
            <p class="modal-subtitle">{{ scoreTitle || 'Sheet Music Score' }}</p>
          </div>
        </div>
        <button class="close-btn" @click="emit('close')" :title="$t('common.close')">
          <X :size="18" />
        </button>
      </div>

      <!-- Modal Body -->
      <div class="modal-body">
        <!-- If link not created yet -->
        <div v-if="!shareToken" class="unshared-state">
          <div class="unshared-illustration">
            <Globe :size="36" class="text-indigo-400" />
          </div>
          <h4>{{ $t('share.scorePrivateTitle') }}</h4>
          <p>
            {{ $t('share.scorePrivateDesc') }}
          </p>
          <button class="primary-btn create-link-btn" :disabled="isLoading" @click="createOrUpdateShare(true)">
            <Sparkles :size="16" />
            <span>{{ isLoading ? $t('share.generatingLink') : $t('share.createLinkBtn') }}</span>
          </button>
        </div>

        <!-- Active share link configured -->
        <div v-else class="active-share-state">
          <!-- Share URL Field -->
          <div class="form-group">
            <div class="label-row">
              <label>{{ $t('share.publicShareUrl') }}</label>
              <span class="badge view-badge">
                <Eye :size="12" />
                <span>{{ $t('share.viewsCount', { count: viewCount }) }}</span>
              </span>
            </div>
            <div class="copy-input-row">
              <input type="text" readonly :value="shareUrl" class="text-input readonly-input" />
              <button class="copy-btn" @click="copyShareUrl" :title="$t('share.copyLink')">
                <Check v-if="hasCopiedLink" :size="16" class="text-emerald-400" />
                <Copy v-else :size="16" />
                <span>{{ hasCopiedLink ? $t('share.copied') : $t('share.copyLink') }}</span>
              </button>
            </div>
          </div>

          <!-- Permission Switches -->
          <div class="permissions-card">
            <h5 class="card-heading">{{ $t('share.permissions') }}</h5>

            <label class="toggle-row">
              <div class="toggle-info">
                <span class="toggle-title">{{ $t('share.allowPlayback') }}</span>
                <span class="toggle-desc">{{ $t('share.allowPlaybackHint') }}</span>
              </div>
              <input
                type="checkbox"
                v-model="allowPlayback"
                @change="createOrUpdateShare(false)"
                class="switch-input"
              />
            </label>

            <label class="toggle-row">
              <div class="toggle-info">
                <span class="toggle-title">{{ $t('share.allowFork') }}</span>
                <span class="toggle-desc">{{ $t('share.allowForkHint') }}</span>
              </div>
              <input
                type="checkbox"
                v-model="allowFork"
                @change="createOrUpdateShare(false)"
                class="switch-input"
              />
            </label>
          </div>

          <!-- Embed Widget Code -->
          <div class="form-group">
            <div class="label-row">
              <label class="embed-label">
                <Code :size="14" />
                <span>{{ $t('share.embedScore') }}</span>
              </label>
            </div>
            <div class="embed-box">
              <textarea readonly :value="embedSnippet" rows="2" class="embed-textarea"></textarea>
              <button class="copy-embed-btn" @click="copyEmbedCode">
                <Check v-if="hasCopiedEmbed" :size="14" />
                <Copy v-else :size="14" />
                <span>{{ hasCopiedEmbed ? $t('share.copied') : $t('share.copyEmbed') }}</span>
              </button>
            </div>
          </div>

          <!-- Revoke Danger Row -->
          <div class="danger-row">
            <template v-if="!showRevokeConfirm">
              <button class="revoke-btn" @click="showRevokeConfirm = true" :disabled="isLoading">
                <Trash2 :size="14" />
                <span>{{ $t('share.revokeLink') }}</span>
              </button>
            </template>
            <template v-else>
              <div class="revoke-confirm-group">
                <span class="revoke-confirm-text">Revoke public link?</span>
                <button class="revoke-btn is-confirm" @click="revokeShare" :disabled="isLoading">Yes, Revoke</button>
                <button class="cancel-btn" @click="showRevokeConfirm = false">Cancel</button>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.share-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(15, 23, 42, 0.72);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}

.share-modal-card {
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 1rem;
  width: 100%;
  max-width: 520px;
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--border);
}

.header-title-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.icon-bubble {
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 0.5rem;
  background: var(--color-primary-light);
  color: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.modal-subtitle {
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin: 0.1rem 0 0 0;
}

.close-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.5rem;
  transition: all 0.15s;
}

.close-btn:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.modal-body {
  padding: 1.5rem;
}

.unshared-state {
  text-align: center;
  padding: 1.5rem 0.5rem;
}

.unshared-illustration {
  width: 4rem;
  height: 4rem;
  border-radius: 50%;
  background: var(--color-primary-light);
  color: var(--color-primary);
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 1.25rem auto;
}

.unshared-state h4 {
  font-size: 1.1rem;
  color: var(--text-primary);
  margin: 0 0 0.5rem 0;
}

.unshared-state p {
  font-size: 0.875rem;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0 0 1.5rem 0;
}

.create-link-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: var(--color-primary);
  color: #ffffff;
  border: none;
  border-radius: 0.5rem;
  padding: 0.75rem 1.5rem;
  min-height: 44px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.create-link-btn:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.active-share-state {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.375rem;
}

.label-row label {
  font-size: 0.825rem;
  font-weight: 500;
  color: var(--text-secondary);
}

.embed-label {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  color: var(--text-secondary);
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  padding: 0.2rem 0.5rem;
  border-radius: 9999px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
}

.copy-input-row {
  display: flex;
  gap: 0.5rem;
}

.readonly-input {
  flex: 1;
  background: var(--input-bg);
  border: 1px solid var(--input-border);
  border-radius: 0.5rem;
  padding: 0.6rem 0.75rem;
  min-height: 44px;
  color: var(--text-primary);
  font-size: 0.85rem;
  outline: none;
}

.copy-btn {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  color: var(--text-primary);
  padding: 0.6rem 1rem;
  min-height: 44px;
  border-radius: 0.5rem;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.copy-btn:hover {
  background: var(--bg-hover);
}

.permissions-card {
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: 0.625rem;
  padding: 0.875rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.card-heading {
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  margin: 0;
}

.toggle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
  min-height: 44px;
}

.toggle-info {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.toggle-title {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text-primary);
}

.toggle-desc {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.switch-input {
  width: 1.25rem;
  height: 1.25rem;
  flex-shrink: 0;
  accent-color: var(--color-primary);
  cursor: pointer;
}

.embed-box {
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  padding: 0.625rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.embed-textarea {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-family: monospace;
  font-size: 0.75rem;
  resize: none;
  outline: none;
  width: 100%;
}

.copy-embed-btn {
  align-self: flex-end;
  display: flex;
  align-items: center;
  gap: 0.35rem;
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-primary);
  padding: 0.45rem 0.75rem;
  min-height: 38px;
  border-radius: 0.375rem;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s;
}

.copy-embed-btn:hover {
  background: var(--bg-hover);
}

.danger-row {
  display: flex;
  justify-content: flex-end;
  padding-top: 0.5rem;
}

.revoke-btn {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  background: transparent;
  border: none;
  color: var(--color-danger);
  font-size: 0.8rem;
  cursor: pointer;
  padding: 0.45rem 0.75rem;
  min-height: 40px;
  border-radius: 0.375rem;
  transition: background 0.15s;
}

.revoke-btn:hover {
  background: var(--color-danger-light);
}

@media (max-width: 768px) {
  .share-modal-backdrop {
    align-items: flex-end;
    padding: 0;
  }

  .share-modal-card {
    max-width: 100%;
    max-height: 90vh;
    border-radius: 1.25rem 1.25rem 0 0;
    padding-bottom: var(--sab);
  }

  .modal-header {
    padding: 1rem 1.25rem;
  }

  .modal-body {
    padding: 1.25rem;
    overflow-y: auto;
  }
}
</style>
