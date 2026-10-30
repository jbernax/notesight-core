<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const props = defineProps<{
  isOpen: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && props.isOpen) {
    emit('close')
  }
}

interface LegalSection {
  title: string
  content: string
}

const termsVersion = ref('2026.1-copyright')
const effectiveDate = ref('October 2026')
const sections = ref<LegalSection[]>([
  {
    title: '1. Lawful Use & Sheet Music Copyright Authorization',
    content: 'You affirm, represent, and warrant that you either own the copyright, possess an explicit license from the copyright owner, or are transcribing musical scores that reside in the public domain or qualify under statutory fair use in your jurisdiction. NoteSight strictly prohibits unauthorized copying, digitization, or reproduction of copyrighted sheet music without authorization.'
  },
  {
    title: '2. Acceptable Use Policy & Prevention of Piracy',
    content: 'You agree not to use NoteSight to digitize, upload, export, or distribute sheet music in any manner that infringes on third-party intellectual property rights. Any attempt to use NoteSight to bypass digital rights management (DRM), mass-scrape protected score catalogs, or facilitate illegal score sharing will result in immediate termination of the account and potential reporting to rightsholders.'
  },
  {
    title: '3. User Representations & Age Requirement',
    content: 'You must be at least 13 years of age (or the applicable age of digital consent in your jurisdiction) to register an account. You agree to provide accurate, current, and complete registration information.'
  },
  {
    title: '4. Optional Billing & Subscription Tiers',
    content: 'Access to basic NoteSight OMR processing is available under our free Starter plan without requiring billing or payment information. Should you choose to upgrade to a paid tier (Virtuoso or Maestro), payments are processed securely via Stripe. Billing information is optional until a paid subscription is selected.'
  },
  {
    title: '5. Disclaimer of Warranties & AI Transcription Limitations',
    content: 'Neural optical music recognition produces algorithmic estimations of musical notation. NoteSight provides score transcription on an "as is" and "as available" basis. Users are advised to review and verify transcribed notation before performance, publishing, or commercial use.'
  },
  {
    title: '6. Open-Source Attribution & OMR Engine Source Availability',
    content: 'NoteSight\'s optical music recognition inference is powered by the standalone open-source package notesight-omr-engine (built on homr), licensed under the GNU Affero General Public License v3.0 (AGPL-3.0-or-later) and executed as an isolated CLI subprocess. In accordance with AGPL-3.0 Section 13, the complete Corresponding Source code for notesight-omr-engine is publicly available at packages/notesight-omr-engine. Server-side PDF rendering and engraving utilize pypdfium2 (Apache-2.0/BSD-3-Clause), pypdf (BSD-3-Clause), Verovio (LGPL-3.0), and CairoSVG (LGPL-3.0); browser notation rendering uses OpenSheetMusicDisplay (BSD-3-Clause).'
  }
])


onMounted(async () => {
  window.addEventListener('keydown', handleKeyDown)
  try {
    const res = await fetch('/api/legal/terms')
    if (res.ok) {
      const data = await res.json()
      if (data.sections && data.sections.length > 0) {
        sections.value = data.sections
        termsVersion.value = data.version
        effectiveDate.value = data.effective_date
      }
    }
  } catch {
    // Fallback static copy already populated
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <teleport to="body">
    <div v-if="isOpen" class="modal-backdrop" @click="emit('close')">
      <div class="modal-card" @click.stop role="dialog" aria-modal="true" aria-labelledby="terms-modal-title">
        <div class="modal-header">
          <div class="header-icon-title">
            <div class="legal-badge-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
              </svg>
            </div>
            <div>
              <h3 id="terms-modal-title" class="modal-title">{{ $t('terms.modalTitle') }}</h3>
              <p class="modal-subtitle">Effective {{ effectiveDate }} • Version {{ termsVersion }}</p>
            </div>
          </div>
          <button class="close-btn" @click="emit('close')" :aria-label="$t('common.close')">✕</button>
        </div>

        <div class="modal-body">
          <div class="terms-callout">
            <svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
            <p>
              <strong>{{ $t('terms.importantNotice') }}</strong> {{ $t('terms.importantNoticeText') }}
            </p>
          </div>

          <div class="sections-list">
            <div v-for="(sec, idx) in sections" :key="idx" class="term-section">
              <h4 class="section-title">{{ sec.title }}</h4>
              <p class="section-content">{{ sec.content }}</p>
            </div>
          </div>
        </div>

        <div class="modal-footer">
          <span class="legal-notice">{{ $t('terms.agreeNotice') }}</span>
          <button type="button" class="btn-agree" @click="emit('close')">{{ $t('terms.understandAndAgree') }}</button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  z-index: 9600;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal-card {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  border-radius: 16px;
  width: 100%;
  max-width: 640px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-lg, 0 20px 40px rgba(0, 0, 0, 0.4));
  color: var(--text-primary, #e2e8f0);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  border-bottom: 1px solid var(--border, #28334a);
}

.header-icon-title {
  display: flex;
  align-items: center;
  gap: 14px;
}

.legal-badge-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: var(--color-primary-light, rgba(59, 130, 246, 0.15));
  color: var(--color-primary, #3b82f6);
  display: flex;
  align-items: center;
  justify-content: center;
}

.legal-badge-icon svg {
  width: 22px;
  height: 22px;
}

.modal-title {
  font-size: 1.15rem;
  font-weight: 700;
  margin: 0;
  color: var(--text-primary);
}

.modal-subtitle {
  font-size: 0.8rem;
  color: var(--text-secondary, #94a3b8);
  margin-top: 2px;
}

.close-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary, #94a3b8);
  font-size: 1.2rem;
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  transition: all 0.15s ease;
}

.close-btn:hover {
  background: var(--bg-subtle, rgba(255, 255, 255, 0.08));
  color: var(--text-primary, #fff);
}

.modal-body {
  padding: 24px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.terms-callout {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: var(--color-warning-light, rgba(245, 158, 11, 0.1));
  border: 1px solid var(--color-warning, rgba(245, 158, 11, 0.3));
  padding: 14px 16px;
  border-radius: 10px;
  font-size: 0.88rem;
  line-height: 1.45;
  color: var(--color-warning, #d97706);
}

.callout-icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  margin-top: 2px;
}

.sections-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.term-section {
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.06));
}

.term-section:last-child {
  border-bottom: none;
}

.section-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
  margin-bottom: 6px;
}

.section-content {
  font-size: 0.86rem;
  color: var(--text-secondary, #94a3b8);
  line-height: 1.55;
  margin: 0;
}

.modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  border-top: 1px solid var(--border, #28334a);
  background: var(--bg-subtle, rgba(0, 0, 0, 0.15));
}

.legal-notice {
  font-size: 0.78rem;
  color: var(--text-muted, #94a3b8);
}

.btn-agree {
  background: var(--color-primary, #2563eb);
  color: white;
  border: none;
  padding: 8px 18px;
  border-radius: 8px;
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.btn-agree:hover {
  background: var(--color-primary-hover, #1d4ed8);
}

@media (max-width: 640px) {
  .modal-backdrop {
    padding: 0;
    align-items: stretch;
  }

  .modal-card {
    width: 100%;
    height: 100%;
    max-height: 100dvh;
    border-radius: 0;
    border: none;
    box-shadow: none;
    padding-top: env(safe-area-inset-top, 0);
  }

  .modal-header {
    padding: 14px 16px;
    flex-shrink: 0;
  }

  .legal-subtitle {
    display: none;
  }

  .modal-body {
    padding: 14px 16px;
    flex: 1;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }

  .modal-footer {
    padding: 12px 16px;
    padding-bottom: max(env(safe-area-inset-bottom, 0px), 14px);
    flex-shrink: 0;
  }

  .btn-agree {
    min-height: 42px;
    width: 100%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
}
</style>
