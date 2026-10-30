import { ref } from 'vue'
import { apiFetch } from '../services/apiClient'

export interface StorageInfo {
  used_bytes: number
  used_mb: number
  limit_bytes: number
  limit_mb: number
  percent_used: number
}

export interface PagesInfo {
  max_per_score: number
  processed_this_month: number
  monthly_limit: number
  remaining_this_month: number
}

export interface TierDetail {
  id: 'starter' | 'pro' | 'virtuoso' | 'maestro'
  name: string
  display_name: string
  tagline: string
  storage_limit_mb: number
  max_pages_per_score: number
  monthly_page_limit: number
  price: string
  features: string[]
}

export interface SubscriptionInfo {
  id: string
  tier: string
  status: string
  current_period_start: string
  current_period_end: string
  cancel_at_period_end: boolean
  pending_tier?: string | null
  downgrade_scheduled_at?: string | null
}

export interface UserQuota {
  user_id: string
  email: string
  tier: 'starter' | 'pro' | 'virtuoso' | 'maestro'
  tier_name: string
  storage: StorageInfo
  pages: PagesInfo
  available_tiers: TierDetail[]
  subscription?: SubscriptionInfo | null
  is_grace_period_active?: boolean
}

// Reactive singleton quota state
export const userQuota = ref<UserQuota | null>(null)
export const isLoadingQuota = ref<boolean>(false)
export const isPlanModalOpen = ref<boolean>(false)
export const quotaError = ref<string | null>(null)

export async function fetchUserQuota(): Promise<UserQuota | null> {
  const token = localStorage.getItem('token')
  if (!token) {
    userQuota.value = null
    return null
  }

  isLoadingQuota.value = true
  quotaError.value = null

  try {
    const res = await apiFetch('/api/user/quota')

    if (!res.ok) {
      if (res.status === 401) {
        userQuota.value = null
      }
      return null
    }

    const data: UserQuota = await res.json()
    userQuota.value = data
    return data
  } catch (err: any) {
    console.error('Failed to load user quota:', err)
    quotaError.value = err.message || 'Failed to load subscription quota'
    return null
  } finally {
    isLoadingQuota.value = false
  }
}

export async function updateUserTier(tier: 'starter' | 'pro' | 'virtuoso' | 'maestro'): Promise<boolean> {
  isLoadingQuota.value = true
  quotaError.value = null

  try {
    const res = await apiFetch('/api/user/tier', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ tier }),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Failed to update plan')
    }

    const data: UserQuota = await res.json()
    userQuota.value = data
    return true
  } catch (err: any) {
    console.error('Failed to update tier:', err)
    quotaError.value = err.message || 'Failed to update plan'
    return false
  } finally {
    isLoadingQuota.value = false
  }
}

export async function scheduleDowngrade(targetTier: 'starter' | 'pro' | 'virtuoso' | 'maestro'): Promise<{ success: boolean; error?: string }> {
  isLoadingQuota.value = true
  quotaError.value = null

  try {
    const res = await apiFetch('/api/billing/downgrade', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ tier: targetTier === 'maestro' ? 'virtuoso' : targetTier }),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Failed to schedule plan downgrade')
    }

    const data: UserQuota = await res.json()
    userQuota.value = data
    return { success: true }
  } catch (err: any) {
    console.error('Failed to schedule downgrade:', err)
    quotaError.value = err.message || 'Failed to schedule plan downgrade'
    return { success: false, error: quotaError.value ?? undefined }
  } finally {
    isLoadingQuota.value = false
  }
}

export async function resumeSubscription(): Promise<{ success: boolean; error?: string }> {
  isLoadingQuota.value = true
  quotaError.value = null

  try {
    const res = await apiFetch('/api/billing/resume', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Failed to resume subscription')
    }

    const data: UserQuota = await res.json()
    userQuota.value = data
    return { success: true }
  } catch (err: any) {
    console.error('Failed to resume subscription:', err)
    quotaError.value = err.message || 'Failed to resume subscription'
    return { success: false, error: quotaError.value ?? undefined }
  } finally {
    isLoadingQuota.value = false
  }
}
