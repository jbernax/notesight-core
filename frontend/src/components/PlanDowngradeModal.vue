<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import type { TierDetail } from '../composables/useQuota'

const props = defineProps<{
  isOpen: boolean
  targetTier: TierDetail | null
  currentTier: TierDetail | null
  storageUsedMb: number
  currentPeriodEnd: string | null
  isSubmitting?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'confirm'): void
}>()

const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && props.isOpen && !props.isSubmitting) {
    emit('close')
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})

const isStorageExceeded = computed(() => {
  if (!props.targetTier) return false
  return props.storageUsedMb > props.targetTier.storage_limit_mb
})

const formattedPeriodEndDate = computed(() => {
  if (!props.currentPeriodEnd) return null
  try {
    const d = new Date(props.currentPeriodEnd)
    return d.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    })
  } catch {
    return props.currentPeriodEnd
  }
})
</script>

<template>
  <teleport to="body">
    <div v-if="isOpen && targetTier && currentTier" class="downgrade-backdrop" @click="emit('close')">
      <div
        class="downgrade-card"
        @click.stop
        role="dialog"
        aria-modal="true"
        aria-labelledby="downgrade-modal-title"
      >
        <!-- Modal Header -->
        <div class="downgrade-header">
          <div class="header-icon-group">
            <div class="warning-icon-pill">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="8" x2="12" y2="12"></line>
                <line x1="12" y1="16" x2="12.01" y2="16"></line>
              </svg>
            </div>
            <div>
              <h3 id="downgrade-modal-title" class="downgrade-title">
                {{ $t('plans.downgradeModalTitle', { tier: targetTier.display_name }) }}
              </h3>
              <p class="downgrade-subtitle">
                {{ $t('plans.downgradeModalDesc') }}
              </p>
            </div>
          </div>
          <button
            class="downgrade-close-btn"
            @click="emit('close')"
            :disabled="isSubmitting"
            :aria-label="$t('common.close')"
          >
            ✕
          </button>
        </div>

        <div class="downgrade-body">
          <!-- Grace Period Guarantee Box -->
          <div class="grace-period-box">
            <div class="grace-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                <line x1="16" y1="2" x2="16" y2="6"></line>
                <line x1="8" y1="2" x2="8" y2="6"></line>
                <line x1="3" y1="10" x2="21" y2="10"></line>
              </svg>
            </div>
            <div class="grace-content">
              <strong class="grace-headline">{{ $t('plans.paidStatusRetainedTitle') }}</strong>
              <p v-if="formattedPeriodEndDate" class="grace-text">
                {{ $t('plans.downgradeGraceNotice', { tier: currentTier.display_name, date: formattedPeriodEndDate, target: targetTier.display_name }) }}
              </p>
              <p v-else class="grace-text">
                {{ $t('plans.downgradeGraceNoticeGeneric', { tier: currentTier.display_name, target: targetTier.display_name }) }}
              </p>
            </div>
          </div>

          <!-- Side-by-side comparison -->
          <div class="comparison-grid">
            <!-- Current Plan -->
            <div class="tier-comp-card current">
              <span class="comp-badge">{{ $t('plans.activePlan') }}</span>
              <h4 class="comp-tier-title">{{ currentTier.display_name }}</h4>
              <div class="comp-price">{{ currentTier.price }}</div>
              <ul class="comp-features">
                <li>
                  <strong>{{ currentTier.storage_limit_mb }} MB</strong> {{ $t('plans.secureStorage') }}
                </li>
                <li>
                  <strong>{{ currentTier.monthly_page_limit }} pages</strong> {{ $t('plans.processedPerMonth') }}
                </li>
              </ul>
            </div>

            <!-- Arrow divider -->
            <div class="comp-arrow-divider">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <line x1="5" y1="12" x2="19" y2="12"></line>
                <polyline points="12 5 19 12 12 19"></polyline>
              </svg>
            </div>

            <!-- Target Plan -->
            <div class="tier-comp-card target">
              <span class="comp-badge new-badge">{{ $t('plans.newPlanBadge') }}</span>
              <h4 class="comp-tier-title">{{ targetTier.display_name }}</h4>
              <div class="comp-price">{{ targetTier.price }}</div>
              <ul class="comp-features">
                <li :class="{ 'warning-highlight': isStorageExceeded }">
                  <strong>{{ targetTier.storage_limit_mb }} MB</strong> {{ $t('plans.secureStorage') }}
                </li>
                <li>
                  <strong>{{ targetTier.monthly_page_limit }} pages</strong> {{ $t('plans.processedPerMonth') }}
                </li>
              </ul>
            </div>
          </div>

          <!-- Storage Alert if user currently exceeds lower tier capacity -->
          <div v-if="isStorageExceeded" class="storage-warning-box">
            <div class="storage-warning-icon">⚠️</div>
            <div class="storage-warning-text">
              <strong>{{ $t('plans.storageOverQuotaTitle') }}</strong>
              <p>
                {{ $t('plans.storageOverQuotaNotice', { used: storageUsedMb, limit: targetTier.storage_limit_mb }) }}
              </p>
            </div>
          </div>
        </div>

        <!-- Footer / Action Buttons -->
        <div class="downgrade-footer">
          <button
            type="button"
            class="btn-cancel"
            @click="emit('close')"
            :disabled="isSubmitting"
          >
            {{ $t('plans.keepCurrentPlanBtn', { tier: currentTier.display_name }) }}
          </button>
          <button
            type="button"
            class="btn-confirm-downgrade"
            @click="emit('confirm')"
            :disabled="isSubmitting"
          >
            <span v-if="isSubmitting">{{ $t('plans.scheduling') }}</span>
            <span v-else>{{ $t('plans.confirmDowngradeBtn', { tier: targetTier.display_name }) }}</span>
          </button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.downgrade-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.78);
  backdrop-filter: blur(6px);
  z-index: 9700;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  animation: fadeIn 0.18s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.downgrade-card {
  background: var(--bg-card, #151b28);
  border: 1px solid rgba(239, 68, 68, 0.35);
  border-radius: 18px;
  box-shadow: 0 25px 60px rgba(0, 0, 0, 0.65);
  width: 100%;
  max-width: 620px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: scaleUp 0.18s ease;
}

@keyframes scaleUp {
  from { transform: scale(0.95); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}

.downgrade-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid var(--border, #28334a);
  background: rgba(239, 68, 68, 0.06);
}

.header-icon-group {
  display: flex;
  align-items: center;
  gap: 14px;
}

.warning-icon-pill {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: rgba(239, 68, 68, 0.16);
  color: #ef4444;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.warning-icon-pill svg {
  width: 22px;
  height: 22px;
}

.downgrade-title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--text-primary, #f8fafc);
}

.downgrade-subtitle {
  margin: 3px 0 0;
  font-size: 0.85rem;
  color: var(--text-secondary, #94a3b8);
}

.downgrade-close-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary, #94a3b8);
  font-size: 1.25rem;
  cursor: pointer;
  padding: 6px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}

.downgrade-close-btn:hover:not(:disabled) {
  color: var(--text-primary, #f8fafc);
  background: rgba(255, 255, 255, 0.08);
}

.downgrade-body {
  padding: 22px 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.grace-period-box {
  display: flex;
  gap: 14px;
  padding: 14px 16px;
  border-radius: 12px;
  background: rgba(99, 102, 241, 0.1);
  border: 1px solid rgba(99, 102, 241, 0.28);
}

.grace-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(99, 102, 241, 0.2);
  color: #818cf8;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.grace-icon svg {
  width: 18px;
  height: 18px;
}

.grace-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.grace-headline {
  font-size: 0.88rem;
  color: #c7d2fe;
}

.grace-text {
  margin: 0;
  font-size: 0.82rem;
  line-height: 1.45;
  color: var(--text-secondary, #cbd5e1);
}

.comparison-grid {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 12px;
}

.tier-comp-card {
  padding: 16px;
  border-radius: 12px;
  background: var(--bg-subtle, #1a2234);
  border: 1px solid var(--border, #28334a);
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tier-comp-card.current {
  border-color: rgba(99, 102, 241, 0.4);
}

.tier-comp-card.target {
  border-color: rgba(239, 68, 68, 0.3);
}

.comp-badge {
  align-self: flex-start;
  font-size: 0.68rem;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 9999px;
  text-transform: uppercase;
  background: rgba(99, 102, 241, 0.2);
  color: #818cf8;
}

.comp-badge.new-badge {
  background: rgba(239, 68, 68, 0.2);
  color: #f87171;
}

.comp-tier-title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text-primary, #f8fafc);
}

.comp-price {
  font-size: 0.86rem;
  color: var(--text-secondary, #94a3b8);
  font-weight: 500;
}

.comp-features {
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 0.8rem;
  color: var(--text-secondary, #94a3b8);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.comp-features li strong {
  color: var(--text-primary, #f8fafc);
}

.comp-features li.warning-highlight {
  color: #ef4444;
}

.comp-arrow-divider {
  color: var(--text-secondary, #64748b);
  display: flex;
  align-items: center;
  justify-content: center;
}

.comp-arrow-divider svg {
  width: 22px;
  height: 22px;
}

.storage-warning-box {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  border-radius: 10px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.3);
  font-size: 0.82rem;
  line-height: 1.45;
}

.storage-warning-icon {
  font-size: 1.2rem;
  flex-shrink: 0;
}

.storage-warning-text strong {
  color: #fbbf24;
  display: block;
  margin-bottom: 2px;
}

.storage-warning-text p {
  margin: 0;
  color: #fde68a;
}

.downgrade-footer {
  padding: 16px 24px;
  border-top: 1px solid var(--border, #28334a);
  background: var(--bg-subtle, #1c2336);
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.btn-cancel {
  background: transparent;
  border: 1px solid var(--border, #334155);
  color: var(--text-primary, #f8fafc);
  padding: 9px 16px;
  border-radius: 10px;
  font-size: 0.86rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-cancel:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
}

.btn-confirm-downgrade {
  background: #dc2626;
  border: none;
  color: white;
  padding: 9px 18px;
  border-radius: 10px;
  font-size: 0.86rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  box-shadow: 0 2px 8px rgba(220, 38, 38, 0.4);
}

.btn-confirm-downgrade:hover:not(:disabled) {
  background: #b91c1c;
  box-shadow: 0 4px 12px rgba(220, 38, 38, 0.5);
}

.btn-confirm-downgrade:disabled,
.btn-cancel:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

@media (max-width: 580px) {
  .comparison-grid {
    grid-template-columns: 1fr;
  }

  .comp-arrow-divider {
    transform: rotate(90deg);
    padding: 6px 0;
  }

  .downgrade-footer {
    flex-direction: column-reverse;
  }

  .btn-confirm-downgrade,
  .btn-cancel {
    width: 100%;
  }
}
</style>
