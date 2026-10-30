<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  userQuota,
  updateUserTier,
  scheduleDowngrade,
  resumeSubscription,
  isLoadingQuota,
  type TierDetail,
} from '../composables/useQuota'
import { currentLocale } from '../i18n'
import { apiFetch } from '../services/apiClient'
import PlanDowngradeModal from './PlanDowngradeModal.vue'

const props = defineProps<{
  isOpen: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && props.isOpen && !isInitiatingPayment.value && !isDowngradeModalOpen.value) {
    emit('close')
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})

const feedbackMsg = ref<string | null>(null)
const feedbackType = ref<'success' | 'error'>('success')

const isInitiatingPayment = ref(false)
const isDowngradeModalOpen = ref(false)
const downgradeTargetTier = ref<TierDetail | null>(null)
const isSchedulingDowngrade = ref(false)
const isResumingSubscription = ref(false)

const TIER_RANKS: Record<string, number> = {
  starter: 0,
  pro: 1,
  virtuoso: 2,
  maestro: 2,
}

const currentTierRank = computed(() => {
  const t = userQuota.value?.tier || 'starter'
  return TIER_RANKS[t] ?? 0
})

const currentTierDetail = computed(() => {
  return userQuota.value?.available_tiers?.find(t => t.id === userQuota.value?.tier) || null
})

const getTierActionType = (tierId: string): 'current' | 'upgrade' | 'downgrade' => {
  if (userQuota.value?.tier === tierId) return 'current'
  const targetRank = TIER_RANKS[tierId] ?? 0
  if (targetRank > currentTierRank.value) return 'upgrade'
  return 'downgrade'
}

const isDowngradeScheduledFor = (tierId: string): boolean => {
  if (!userQuota.value?.subscription?.cancel_at_period_end) return false
  const pending = userQuota.value.subscription.pending_tier || 'starter'
  return pending === tierId
}

const formatPeriodEnd = (dateStr?: string | null): string => {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return dateStr
  }
}

const handleTierClick = (tier: TierDetail) => {
  const action = getTierActionType(tier.id)
  if (action === 'current') {
    if (tier.id !== 'starter') {
      handleOpenBillingPortal()
    }
    return
  }

  if (action === 'downgrade') {
    downgradeTargetTier.value = tier
    isDowngradeModalOpen.value = true
    return
  }

  // Upgrade path -> Stripe Checkout
  handleSelectTier(tier.id)
}

const handleConfirmDowngrade = async () => {
  if (!downgradeTargetTier.value) return
  isSchedulingDowngrade.value = true
  feedbackMsg.value = null

  try {
    const res = await scheduleDowngrade(downgradeTargetTier.value.id)
    if (res.success) {
      feedbackType.value = 'success'
      const effectiveDate = formatPeriodEnd(userQuota.value?.subscription?.current_period_end)
      feedbackMsg.value = `Plan downgrade scheduled. Your ${userQuota.value?.tier_name} privileges remain active until ${effectiveDate}.`
      isDowngradeModalOpen.value = false
    } else {
      feedbackType.value = 'error'
      feedbackMsg.value = res.error || 'Failed to schedule plan downgrade.'
    }
  } finally {
    isSchedulingDowngrade.value = false
  }
}

const handleResumeSubscription = async () => {
  isResumingSubscription.value = true
  feedbackMsg.value = null
  try {
    const res = await resumeSubscription()
    if (res.success) {
      feedbackType.value = 'success'
      feedbackMsg.value = 'Subscription successfully resumed. Regular renewals will continue.'
    } else {
      feedbackType.value = 'error'
      feedbackMsg.value = res.error || 'Failed to resume subscription.'
    }
  } finally {
    isResumingSubscription.value = false
  }
}

const handleSelectTier = async (tierId: 'starter' | 'pro' | 'virtuoso' | 'maestro') => {
  if (userQuota.value?.tier === tierId) return

  feedbackMsg.value = null

  if (tierId === 'starter') {
    const success = await updateUserTier('starter')
    if (success) {
      feedbackType.value = 'success'
      feedbackMsg.value = `Switched to Starter Soloist.`
      setTimeout(() => {
        if (props.isOpen) {
          emit('close')
        }
        feedbackMsg.value = null
      }, 1800)
    } else {
      feedbackType.value = 'error'
      feedbackMsg.value = 'Failed to switch plans. Please try again.'
    }
    return
  }

  // Paid tiers: initiate Stripe Checkout session
  isInitiatingPayment.value = true
  try {
    const res = await apiFetch('/api/billing/create-checkout-session', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        tier: tierId === 'maestro' ? 'virtuoso' : tierId,
        locale: currentLocale.value,
      }),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Could not initialize secure checkout session')
    }

    const data = await res.json()
    if (data.checkout_url) {
      window.location.href = data.checkout_url
    }
  } catch (err: any) {
    feedbackType.value = 'error'
    feedbackMsg.value = err.message || 'Payment initiation failed. Please try again.'
  } finally {
    isInitiatingPayment.value = false
  }
}

const handleOpenBillingPortal = async () => {
  isInitiatingPayment.value = true
  feedbackMsg.value = null
  try {
    const res = await apiFetch('/api/billing/create-portal-session', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        locale: currentLocale.value,
      }),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Could not open billing portal')
    }

    const data = await res.json()
    if (data.portal_url) {
      window.location.href = data.portal_url
    }
  } catch (err: any) {
    feedbackType.value = 'error'
    feedbackMsg.value = err.message || 'Failed to open customer billing portal.'
  } finally {
    isInitiatingPayment.value = false
  }
}
</script>

<template>
  <teleport to="body">
    <div v-if="isOpen" class="plan-modal-backdrop" @click="emit('close')">
      <div class="plan-modal-card" @click.stop role="dialog" aria-modal="true" aria-labelledby="plan-title">
        <!-- Modal Header -->
        <div class="plan-header">
          <div class="plan-title-group">
            <div>
              <h3 id="plan-title" class="plan-title">{{ $t('plans.title') }}</h3>
              <p class="plan-subtitle">{{ $t('plans.subtitle') }}</p>
            </div>
          </div>
          <button class="plan-close-btn" @click="emit('close')" :aria-label="$t('common.close')">✕</button>
        </div>

        <!-- Feedback Alert Banner -->
        <div v-if="feedbackMsg" class="feedback-banner" :class="feedbackType">
          <span>{{ feedbackMsg }}</span>
        </div>

        <!-- Grace Period Scheduled Downgrade Banner -->
        <div v-if="userQuota?.subscription?.cancel_at_period_end" class="scheduled-downgrade-banner">
          <div class="scheduled-banner-left">
            <span class="scheduled-banner-icon">ℹ️</span>
            <div>
              <strong class="scheduled-banner-title">{{ $t('plans.downgradeScheduled') }}</strong>
              <p class="scheduled-banner-text">
                {{ $t('plans.downgradeScheduledBanner', {
                  target: userQuota.subscription.pending_tier ? userQuota.subscription.pending_tier.toUpperCase() : 'STARTER',
                  date: formatPeriodEnd(userQuota.subscription.current_period_end),
                  current: userQuota.tier_name
                }) }}
              </p>
            </div>
          </div>
          <button
            type="button"
            class="resume-subscription-btn"
            :disabled="isResumingSubscription"
            @click="handleResumeSubscription"
          >
            <span v-if="isResumingSubscription">{{ $t('plans.resuming') }}</span>
            <span v-else>{{ $t('plans.resumeSubscription') }}</span>
          </button>
        </div>

        <!-- Modal Body / 3-Card Grid -->
        <div class="plan-body">
          <div class="tiers-grid">
            <div 
              v-for="tier in userQuota?.available_tiers || []" 
              :key="tier.id"
              class="tier-card"
              :class="{ 
                'is-current': userQuota?.tier === tier.id,
                'is-featured': tier.id === 'pro' && getTierActionType(tier.id) === 'upgrade'
              }"
            >
              <div v-if="tier.id === 'pro' && getTierActionType(tier.id) === 'upgrade'" class="featured-ribbon">
                {{ $t('plans.mostPopular') }}
              </div>

              <div class="tier-card-header">
                <div class="tier-name-row">
                  <h4 class="tier-card-title">{{ tier.display_name }}</h4>
                  <span v-if="userQuota?.tier === tier.id" class="current-badge">{{ $t('plans.activePlan') }}</span>
                </div>
                <div class="tier-price-row">
                  <span class="price-val">{{ tier.price }}</span>
                </div>
                <p class="tier-tagline">{{ tier.tagline }}</p>
              </div>

              <!-- Key Specs Badges -->
              <div class="tier-specs">
                <div class="spec-pill" title="Secure Score Storage">
                  <svg class="spec-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
                    <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
                    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
                  </svg>
                  <span><strong>{{ tier.storage_limit_mb }} MB</strong> {{ $t('plans.secureStorage') }}</span>
                </div>

                <div class="spec-pill" title="Pages Processed Per Month">
                  <svg class="spec-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                  </svg>
                  <span><strong>{{ tier.monthly_page_limit }} pages</strong> {{ $t('plans.processedPerMonth') }}</span>
                </div>
              </div>

              <!-- Card Action Button -->
              <div class="tier-action-wrapper">
                <button
                  type="button"
                  class="tier-action-btn"
                  :class="{ 
                    'current-plan-btn': userQuota?.tier === tier.id,
                    'featured-btn': tier.id === 'pro' && userQuota?.tier !== tier.id && getTierActionType(tier.id) === 'upgrade',
                    'downgrade-btn': getTierActionType(tier.id) === 'downgrade',
                    'scheduled-btn': isDowngradeScheduledFor(tier.id)
                  }"
                  :disabled="(userQuota?.tier === tier.id && tier.id === 'starter') || isDowngradeScheduledFor(tier.id) || isLoadingQuota || isInitiatingPayment || isSchedulingDowngrade"
                  @click="handleTierClick(tier)"
                >
                  <span v-if="isInitiatingPayment">{{ $t('plans.connecting') }}</span>
                  <span v-else-if="isDowngradeScheduledFor(tier.id)">{{ $t('plans.downgradeScheduled') }}</span>
                  <span v-else-if="userQuota?.tier === tier.id && tier.id !== 'starter'">{{ $t('plans.manageBilling') }}</span>
                  <span v-else-if="userQuota?.tier === tier.id">{{ $t('plans.currentPlan') }}</span>
                  <span v-else-if="isLoadingQuota">{{ $t('plans.switching') }}</span>
                  <span v-else-if="getTierActionType(tier.id) === 'downgrade'">
                    {{ tier.id === 'pro' ? $t('plans.downgradeToPro') : $t('plans.downgradeToStarter') }}
                  </span>
                  <span v-else-if="tier.id === 'virtuoso' || tier.id === 'maestro'">{{ $t('plans.upgradeToVirtuoso') }}</span>
                  <span v-else>{{ $t('plans.upgradeToPro') }}</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Modal Footer -->
        <div class="plan-footer">
          <div class="footer-security-col">
            <div class="pci-badge">
              <svg class="pci-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
              </svg>
              <span>{{ $t('plans.pciSecure') }}</span>
            </div>
            <p class="enterprise-note">
              {{ $t('plans.enterpriseNote') }}
            </p>
          </div>
          <div class="footer-actions-group">
            <button 
              v-if="userQuota?.tier && userQuota.tier !== 'starter'" 
              class="portal-btn" 
              @click="handleOpenBillingPortal"
              :disabled="isInitiatingPayment"
            >
              {{ $t('plans.manageBilling') }}
            </button>
            <button class="plan-done-btn" @click="emit('close')">{{ $t('common.done') }}</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Downgrade Confirmation Safety Modal -->
    <PlanDowngradeModal
      :is-open="isDowngradeModalOpen"
      :target-tier="downgradeTargetTier"
      :current-tier="currentTierDetail"
      :storage-used-mb="userQuota?.storage?.used_mb || 0"
      :current-period-end="userQuota?.subscription?.current_period_end || null"
      :is-submitting="isSchedulingDowngrade"
      @close="isDowngradeModalOpen = false"
      @confirm="handleConfirmDowngrade"
    />
  </teleport>
</template>

<style scoped>
.plan-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(5px);
  z-index: 9600;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.plan-modal-card {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  border-radius: 18px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
  width: 100%;
  max-width: 960px;
  max-height: 92vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: scaleUp 0.2s ease;
}

@keyframes scaleUp {
  from { transform: scale(0.96); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}

.plan-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 22px 28px;
  border-bottom: 1px solid var(--border, #28334a);
  background: var(--bg-subtle, #1c2336);
}

.plan-title-group {
  display: flex;
  align-items: center;
  gap: 14px;
}

.plan-icon-wrapper {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--color-primary-light, rgba(99, 102, 241, 0.15));
  color: var(--color-primary, #6366f1);
  display: flex;
  align-items: center;
  justify-content: center;
}

.plan-icon {
  width: 24px;
  height: 24px;
}

.plan-title {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--text-primary, #f8fafc);
}

.plan-subtitle {
  margin: 2px 0 0 0;
  font-size: 0.85rem;
  color: var(--text-secondary, #94a3b8);
}

.plan-close-btn {
  background: transparent;
  border: none;
  color: var(--text-muted, #64748b);
  font-size: 1.25rem;
  cursor: pointer;
  padding: 6px;
  border-radius: 8px;
  transition: all 0.15s ease;
}

.plan-close-btn:hover {
  color: var(--text-primary, #f8fafc);
  background: var(--bg-elevated, #222c42);
}

.feedback-banner {
  padding: 12px 28px;
  font-size: 0.9rem;
  font-weight: 600;
  text-align: center;
  animation: slideDown 0.2s ease;
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

.feedback-banner.success {
  background: var(--color-success-light, rgba(16, 185, 129, 0.15));
  color: var(--color-success, #10b981);
  border-bottom: 1px solid var(--color-success, #10b981);
}

.feedback-banner.error {
  background: var(--color-danger-light, rgba(239, 68, 68, 0.15));
  color: var(--color-danger, #ef4444);
  border-bottom: 1px solid var(--color-danger, #ef4444);
}

.plan-body {
  padding: 24px 28px;
  overflow-y: auto;
  flex: 1;
}

.tiers-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

@media (max-width: 840px) {
  .tiers-grid {
    grid-template-columns: 1fr;
  }
}

.tier-card {
  position: relative;
  background: var(--bg-subtle, #1c2336);
  border: 1px solid var(--border, #28334a);
  border-radius: 14px;
  padding: 22px;
  display: flex;
  flex-direction: column;
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

.tier-card:hover {
  transform: translateY(-2px);
  border-color: var(--color-primary-hover, #818cf8);
}

.tier-card.is-featured {
  border-color: var(--color-primary, #6366f1);
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.15);
}

.tier-card.is-current {
  border-color: var(--color-success, #10b981);
}

.featured-ribbon {
  position: absolute;
  top: -11px;
  right: 18px;
  background: var(--color-primary, #6366f1);
  color: #ffffff;
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 3px 10px;
  border-radius: 20px;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.4);
}

.tier-card-header {
  margin-bottom: 16px;
}

.tier-name-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.tier-card-title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--text-primary, #f8fafc);
}

.current-badge {
  font-size: 0.7rem;
  font-weight: 700;
  background: var(--color-success-light, rgba(16, 185, 129, 0.15));
  color: var(--color-success, #10b981);
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid var(--color-success, #10b981);
}

.tier-price-row {
  margin-bottom: 6px;
}

.price-val {
  font-size: 1.5rem;
  font-weight: 800;
  color: var(--text-primary, #f8fafc);
}

.tier-tagline {
  margin: 0;
  font-size: 0.8rem;
  color: var(--text-secondary, #94a3b8);
  line-height: 1.4;
  min-height: 2.8em;
}

.tier-specs {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: var(--bg-card, #151b28);
  border-radius: 10px;
  margin-bottom: 18px;
  border: 1px solid var(--border, #28334a);
}

.spec-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.82rem;
  color: var(--text-secondary, #94a3b8);
}

.spec-icon {
  width: 16px;
  height: 16px;
  color: var(--color-accent, #22d3ee);
  flex-shrink: 0;
}

.spec-pill strong {
  color: var(--text-primary, #f8fafc);
}

.tier-features {
  list-style: none;
  padding: 0;
  margin: 0 0 20px 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
}

.feature-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 0.82rem;
  color: var(--text-secondary, #94a3b8);
  line-height: 1.35;
}

.feature-check {
  width: 15px;
  height: 15px;
  color: var(--color-primary, #6366f1);
  flex-shrink: 0;
  margin-top: 2px;
}

.tier-action-wrapper {
  margin-top: auto;
}

.tier-action-btn {
  width: 100%;
  padding: 11px 16px;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 600;
  border: 1px solid var(--border, #28334a);
  background: var(--bg-elevated, #222c42);
  color: var(--text-primary, #f8fafc);
  cursor: pointer;
  transition: all 0.2s ease;
}

.tier-action-btn:hover:not(:disabled) {
  background: var(--color-primary, #6366f1);
  border-color: var(--color-primary, #6366f1);
  color: #ffffff;
}

.tier-action-btn.featured-btn {
  background: var(--color-primary, #6366f1);
  border-color: var(--color-primary, #6366f1);
  color: #ffffff;
}

.tier-action-btn.featured-btn:hover:not(:disabled) {
  background: var(--color-primary-hover, #818cf8);
}

.tier-action-btn.current-plan-btn {
  background: var(--color-success-light, rgba(16, 185, 129, 0.15));
  border-color: var(--color-success, #10b981);
  color: var(--color-success, #10b981);
  cursor: default;
}

.tier-action-btn.downgrade-btn {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.35);
  color: #fca5a5;
}

.tier-action-btn.downgrade-btn:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.2);
  border-color: #ef4444;
  color: #ffffff;
}

.tier-action-btn.scheduled-btn {
  background: rgba(148, 163, 184, 0.1);
  border: 1px dashed rgba(148, 163, 184, 0.35);
  color: #94a3b8;
  cursor: not-allowed;
}

.scheduled-downgrade-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 12px 28px;
  background: rgba(99, 102, 241, 0.1);
  border-bottom: 1px solid rgba(99, 102, 241, 0.25);
  animation: slideDown 0.2s ease;
}

.scheduled-banner-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.scheduled-banner-icon {
  font-size: 1.25rem;
  flex-shrink: 0;
}

.scheduled-banner-title {
  font-size: 0.88rem;
  color: #c7d2fe;
  display: block;
  margin-bottom: 2px;
}

.scheduled-banner-text {
  margin: 0;
  font-size: 0.82rem;
  color: var(--text-secondary, #94a3b8);
  line-height: 1.4;
}

.resume-subscription-btn {
  background: rgba(99, 102, 241, 0.2);
  border: 1px solid rgba(99, 102, 241, 0.45);
  color: #ffffff;
  font-size: 0.82rem;
  font-weight: 600;
  padding: 7px 14px;
  border-radius: 8px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.resume-subscription-btn:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.35);
  border-color: #818cf8;
}

.resume-subscription-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

@media (max-width: 680px) {
  .scheduled-downgrade-banner {
    flex-direction: column;
    align-items: flex-start;
  }

  .resume-subscription-btn {
    align-self: flex-start;
  }
}

.plan-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 28px;
  border-top: 1px solid var(--border, #28334a);
  background: var(--bg-subtle, #1c2336);
}

.enterprise-note {
  margin: 0;
  font-size: 0.8rem;
  color: var(--text-muted, #64748b);
}

.contact-link {
  color: var(--color-accent, #22d3ee);
  text-decoration: underline;
}

.plan-done-btn {
  padding: 9px 22px;
  background: var(--color-primary, #6366f1);
  border: none;
  border-radius: 8px;
  color: #ffffff;
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.plan-done-btn:hover {
  background: var(--color-primary-hover, #818cf8);
}

.footer-security-col {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pci-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  color: #818cf8;
  font-weight: 500;
}

.pci-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.footer-actions-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.portal-btn {
  padding: 8px 16px;
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.35);
  border-radius: 8px;
  color: #a5b4fc;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.portal-btn:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.25);
  color: #ffffff;
}

@media (max-width: 640px) {
  .plan-modal-backdrop {
    padding: 0;
    align-items: stretch;
  }

  .plan-modal-card {
    width: 100%;
    height: 100%;
    max-height: 100dvh;
    border-radius: 0;
    border: none;
    box-shadow: none;
    padding-top: env(safe-area-inset-top, 0);
  }

  .plan-header {
    padding: 14px 16px;
    flex-shrink: 0;
  }

  .plan-subtitle {
    display: none;
  }

  .plan-body {
    padding: 14px 12px;
    flex: 1;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }

  .tiers-grid {
    grid-template-columns: 1fr;
    gap: 14px;
  }

  .tier-card {
    padding: 16px;
  }

  .plan-footer {
    padding: 12px 16px;
    padding-bottom: max(env(safe-area-inset-bottom, 0px), 14px);
    flex-direction: column;
    gap: 12px;
    align-items: stretch;
    flex-shrink: 0;
  }

  .footer-actions-group {
    width: 100%;
    justify-content: stretch;
  }

  .plan-done-btn,
  .portal-btn {
    flex: 1;
    text-align: center;
    min-height: 42px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
}
</style>
