import { ref } from 'vue'
import { apiFetch } from '../services/apiClient'

export interface UserProfile {
  id: string
  email: string
  full_name: string
  birthdate: string | null
  musical_role: string | null
  country: string | null
  bio: string | null
  is_verified: boolean
  oauth_provider: string | null
  avatar_url: string | null
  email_notifications_enabled: boolean
  allow_omr_telemetry?: boolean
  totp_enabled?: boolean
  tier: string
  terms_accepted: boolean
  terms_accepted_at: string | null
  terms_version: string | null
  created_at: string
  has_billing_customer: boolean
  billing_name: string | null
  billing_country: string | null
}

export const userProfile = ref<UserProfile | null>(null)
export const isLoadingProfile = ref(false)
export const profileError = ref<string | null>(null)

export async function fetchUserProfile() {
  const token = localStorage.getItem('token')
  if (!token) return
  isLoadingProfile.value = true
  profileError.value = null
  try {
    const res = await apiFetch('/api/user/profile')
    if (res.ok) {
      userProfile.value = await res.json()
    }
  } catch (err: any) {
    profileError.value = err.message || 'Failed to load profile'
  } finally {
    isLoadingProfile.value = false
  }
}

export async function updateUserProfile(data: {
  full_name?: string
  birthdate?: string | null
  musical_role?: string | null
  country?: string | null
  bio?: string | null
  avatar_url?: string | null
  email_notifications_enabled?: boolean
  allow_omr_telemetry?: boolean
}): Promise<{ success: boolean; message?: string }> {
  try {
    const res = await apiFetch('/api/user/profile', {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    })
    if (res.ok) {
      userProfile.value = await res.json()
      return { success: true }
    } else {
      const err = await res.json().catch(() => ({}))
      return { success: false, message: err.detail || 'Failed to update profile' }
    }
  } catch (err: any) {
    return { success: false, message: err.message || 'Network error' }
  }
}

export async function changeUserPassword(data: {
  current_password: string
  new_password: string
}): Promise<{ success: boolean; message?: string }> {
  try {
    const res = await apiFetch('/api/user/change-password', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    })
    if (res.ok) {
      return { success: true }
    } else {
      const err = await res.json().catch(() => ({}))
      return { success: false, message: err.detail || 'Password change failed' }
    }
  } catch (err: any) {
    return { success: false, message: err.message || 'Network error' }
  }
}

export async function requestVerificationEmail(): Promise<{ success: boolean; message?: string }> {
  try {
    const res = await apiFetch('/api/auth/request-verification', {
      method: 'POST',
    })
    if (res.ok) {
      return { success: true, message: 'Verification link has been sent to your email.' }
    }
    const err = await res.json().catch(() => ({}))
    return { success: false, message: err.detail || 'Failed to send verification link' }
  } catch (err: any) {
    return { success: false, message: err.message || 'Network error' }
  }
}
