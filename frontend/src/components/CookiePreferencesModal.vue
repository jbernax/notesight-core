<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import {
  isPreferencesModalOpen,
  cookieConsent,
  closeCookiePreferences,
  saveConsent,
  acceptAll,
} from '../composables/useCookieConsent'

const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && isPreferencesModalOpen.value) {
    closeCookiePreferences()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})

const functional = ref<boolean>(true)
const analytics = ref<boolean>(false)

watch(
  () => isPreferencesModalOpen.value,
  (open) => {
    if (open) {
      functional.value = cookieConsent.value?.functional ?? true
      analytics.value = cookieConsent.value?.analytics ?? false
    }
  },
  { immediate: true }
)

const handleSaveCustom = () => {
  saveConsent({
    functional: functional.value,
    analytics: analytics.value,
  })
}

const handleAcceptAll = () => {
  acceptAll()
}
</script>

<template>
  <teleport to="body">
    <div
      v-if="isPreferencesModalOpen"
      class="pref-backdrop"
      @click="closeCookiePreferences"
    >
      <div
        class="pref-card"
        @click.stop
        role="dialog"
        aria-modal="true"
        aria-labelledby="pref-title"
      >
        <!-- Modal Header -->
        <div class="pref-header">
          <div class="pref-title-group">
            <div class="pref-icon-box">
              <svg class="pref-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
              </svg>
            </div>
            <div>
              <h3 id="pref-title" class="pref-title">{{ $t('cookies.bannerTitle') }}</h3>
              <p class="pref-subtitle">{{ $t('cookies.customize') }}</p>
            </div>
          </div>
          <button class="pref-close-btn" @click="closeCookiePreferences" :aria-label="$t('common.close')">✕</button>
        </div>

        <!-- Modal Body -->
        <div class="pref-body">
          <p class="pref-intro">
            {{ $t('cookies.bannerText') }}
          </p>

          <!-- 1. Strictly Necessary -->
          <div class="category-card locked">
            <div class="category-header">
              <div class="category-meta">
                <span class="category-badge required">{{ $t('cookies.strictlyNecessary') }}</span>
                <h4 class="category-name">{{ $t('cookies.strictlyNecessary') }}</h4>
              </div>
              <div class="switch-wrapper">
                <span class="lock-label">{{ $t('cookies.alwaysActive') }}</span>
              </div>
            </div>
            <p class="category-desc">
              {{ $t('cookies.strictlyNecessaryDesc') }}
            </p>
          </div>

          <!-- 2. Functional & Studio Preferences -->
          <div class="category-card">
            <div class="category-header">
              <div class="category-meta">
                <span class="category-badge functional">{{ $t('cookies.functional') }}</span>
                <h4 class="category-name">{{ $t('cookies.functional') }}</h4>
              </div>
              <label class="switch-toggle" :aria-label="$t('cookies.functional')">
                <input type="checkbox" v-model="functional" />
                <span class="slider"></span>
              </label>
            </div>
            <p class="category-desc">
              {{ $t('cookies.functionalDesc') }}
            </p>
          </div>

          <!-- 3. Performance & Analytics -->
          <div class="category-card">
            <div class="category-header">
              <div class="category-meta">
                <span class="category-badge analytics">{{ $t('cookies.analytics') }}</span>
                <h4 class="category-name">{{ $t('cookies.analytics') }}</h4>
              </div>
              <label class="switch-toggle" :aria-label="$t('cookies.analytics')">
                <input type="checkbox" v-model="analytics" />
                <span class="slider"></span>
              </label>
            </div>
            <p class="category-desc">
              {{ $t('cookies.analyticsDesc') }}
            </p>
          </div>

          <!-- Detailed Cookie Audit Disclosure Table -->
          <div class="cookie-audit-section">
            <h5 class="audit-title">{{ $t('cookies.auditTitle') }}</h5>
            <div class="table-container">
              <table class="audit-table">
                <thead>
                  <tr>
                    <th>{{ $t('cookies.colKey') }}</th>
                    <th>{{ $t('cookies.colCategory') }}</th>
                    <th>{{ $t('cookies.colType') }}</th>
                    <th>{{ $t('cookies.colDuration') }}</th>
                    <th>{{ $t('cookies.colPurpose') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td><code>token</code></td>
                    <td><span class="cat-pill necessary">{{ $t('cookies.strictlyNecessary') }}</span></td>
                    <td>LocalStorage / Header</td>
                    <td>24 Hours</td>
                    <td>JWT authentication token for user tenancy isolation</td>
                  </tr>
                  <tr>
                    <td><code>notesight_cookie_consent</code></td>
                    <td><span class="cat-pill necessary">{{ $t('cookies.strictlyNecessary') }}</span></td>
                    <td>LocalStorage</td>
                    <td>1 Year</td>
                    <td>Persists user privacy and cookie consent preferences</td>
                  </tr>
                  <tr>
                    <td><code>__stripe_mid, __stripe_sid</code></td>
                    <td><span class="cat-pill necessary">{{ $t('cookies.strictlyNecessary') }}</span></td>
                    <td>Cookie (Stripe)</td>
                    <td>Session / 1 Year</td>
                    <td>Fraud prevention &amp; PCI-DSS Level 1 compliance during checkout</td>
                  </tr>
                  <tr>
                    <td><code>notesight_user_settings</code></td>
                    <td><span class="cat-pill functional">{{ $t('cookies.functional') }}</span></td>
                    <td>LocalStorage</td>
                    <td>Persistent</td>
                    <td>Saves visual theme, audio instrument timbre, and zoom</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <!-- Modal Footer -->
        <div class="pref-footer">
          <button type="button" class="btn-cancel" @click="closeCookiePreferences">{{ $t('common.cancel') }}</button>
          <div class="footer-actions">
            <button type="button" class="btn-save" @click="handleSaveCustom">{{ $t('cookies.savePreferences') }}</button>
            <button type="button" class="btn-all" @click="handleAcceptAll">{{ $t('cookies.acceptAll') }}</button>
          </div>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.pref-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(6px);
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
}

.pref-card {
  background: #111422;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 16px;
  max-width: 720px;
  width: 100%;
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.6);
  color: #e2e8f0;
  overflow: hidden;
}

.pref-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.pref-title-group {
  display: flex;
  align-items: center;
  gap: 0.85rem;
}

.pref-icon-box {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #818cf8;
}

.pref-icon {
  width: 18px;
  height: 18px;
}

.pref-title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 600;
  color: #ffffff;
}

.pref-subtitle {
  margin: 0;
  font-size: 0.82rem;
  color: #94a3b8;
}

.pref-close-btn {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 1.25rem;
  cursor: pointer;
  padding: 0.25rem 0.5rem;
  border-radius: 6px;
  transition: all 0.15s ease;
}

.pref-close-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #ffffff;
}

.pref-body {
  padding: 1.25rem 1.5rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.pref-intro {
  margin: 0;
  font-size: 0.85rem;
  color: #94a3b8;
  line-height: 1.5;
}

.category-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  padding: 1rem 1.15rem;
}

.category-card.locked {
  background: rgba(99, 102, 241, 0.05);
  border-color: rgba(99, 102, 241, 0.2);
}

.category-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.4rem;
}

.category-meta {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.category-badge {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  width: fit-content;
}

.category-badge.required {
  background: rgba(99, 102, 241, 0.25);
  color: #a5b4fc;
}

.category-badge.functional {
  background: rgba(16, 185, 129, 0.2);
  color: #6ee7b7;
}

.category-badge.analytics {
  background: rgba(245, 158, 11, 0.2);
  color: #fcd34d;
}

.category-name {
  margin: 0;
  font-size: 0.92rem;
  font-weight: 600;
  color: #f1f5f9;
}

.category-desc {
  margin: 0;
  font-size: 0.8rem;
  color: #94a3b8;
  line-height: 1.45;
}

.lock-label {
  font-size: 0.78rem;
  color: #818cf8;
  font-weight: 600;
  background: rgba(99, 102, 241, 0.12);
  padding: 0.25rem 0.65rem;
  border-radius: 6px;
}

/* Custom switch toggle */
.switch-toggle {
  position: relative;
  display: inline-block;
  width: 44px;
  height: 24px;
  flex-shrink: 0;
}

.switch-toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  inset: 0;
  background-color: rgba(255, 255, 255, 0.15);
  transition: 0.2s;
  border-radius: 24px;
}

.slider:before {
  position: absolute;
  content: "";
  height: 18px;
  width: 18px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  transition: 0.2s;
  border-radius: 50%;
}

input:checked + .slider {
  background-color: #6366f1;
}

input:checked + .slider:before {
  transform: translateX(20px);
}

/* Audit table */
.cookie-audit-section {
  margin-top: 0.5rem;
}

.audit-title {
  margin: 0 0 0.5rem 0;
  font-size: 0.88rem;
  font-weight: 600;
  color: #cbd5e1;
}

.table-container {
  overflow-x: auto;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
}

.audit-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.78rem;
}

.audit-table th {
  background: rgba(255, 255, 255, 0.04);
  padding: 0.6rem 0.85rem;
  text-align: left;
  color: #94a3b8;
  font-weight: 600;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.audit-table td {
  padding: 0.6rem 0.85rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  color: #cbd5e1;
}

.audit-table code {
  font-family: monospace;
  background: rgba(255, 255, 255, 0.08);
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  color: #a5b4fc;
}

.cat-pill {
  font-size: 0.7rem;
  font-weight: 600;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
}

.cat-pill.necessary {
  background: rgba(99, 102, 241, 0.2);
  color: #818cf8;
}

.cat-pill.functional {
  background: rgba(16, 185, 129, 0.2);
  color: #6ee7b7;
}

/* Footer */
.pref-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.5rem;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
}

.footer-actions {
  display: flex;
  gap: 0.65rem;
}

.btn-cancel {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #94a3b8;
  padding: 0.5rem 0.95rem;
  border-radius: 8px;
  font-size: 0.82rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-cancel:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #ffffff;
}

.btn-save {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #ffffff;
  padding: 0.5rem 1rem;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-save:hover {
  background: rgba(255, 255, 255, 0.15);
}

.btn-all {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border: none;
  color: #ffffff;
  padding: 0.5rem 1.15rem;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
  transition: all 0.15s ease;
}

.btn-all:hover {
  filter: brightness(1.1);
}

@media (max-width: 640px) {
  .pref-backdrop {
    padding: 0;
    align-items: stretch;
  }

  .pref-card {
    width: 100%;
    height: 100%;
    max-height: 100dvh;
    border-radius: 0;
    border: none;
    box-shadow: none;
    padding-top: env(safe-area-inset-top, 0);
  }

  .pref-header {
    padding: 12px 14px;
    flex-shrink: 0;
  }

  .pref-body {
    padding: 14px 12px;
    flex: 1;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }

  .pref-footer {
    padding: 12px 14px;
    padding-bottom: max(env(safe-area-inset-bottom, 0px), 14px);
    flex-shrink: 0;
    flex-direction: column;
    gap: 10px;
    align-items: stretch;
  }

  .footer-actions {
    width: 100%;
    display: flex;
    gap: 8px;
  }

  .btn-cancel,
  .btn-save,
  .btn-all {
    flex: 1;
    justify-content: center;
    text-align: center;
    min-height: 40px;
    display: inline-flex;
    align-items: center;
  }
}
</style>
