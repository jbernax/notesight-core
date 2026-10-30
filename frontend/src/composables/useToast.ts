import { ref } from 'vue'

export type ToastType = 'info' | 'success' | 'warning' | 'error'

export interface ToastItem {
  id: string
  title: string
  message: string
  type: ToastType
  actionLabel?: string
  onAction?: () => void
  duration?: number
}

export const activeToasts = ref<ToastItem[]>([])

export function showToast(toast: Omit<ToastItem, 'id'>): string {
  const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
  const duration = toast.duration ?? (toast.type === 'error' ? 8000 : 6000)

  const item: ToastItem = {
    ...toast,
    id,
    duration,
  }

  activeToasts.value.push(item)

  if (duration > 0) {
    setTimeout(() => {
      dismissToast(id)
    }, duration)
  }

  return id
}

export function dismissToast(id: string) {
  activeToasts.value = activeToasts.value.filter((t) => t.id !== id)
}

/**
 * Request permission and dispatch native browser desktop notification if supported
 */
export async function dispatchDesktopNotification(title: string, options?: NotificationOptions) {
  if (typeof window === 'undefined' || !('Notification' in window)) {
    return
  }

  try {
    if (Notification.permission === 'default') {
      await Notification.requestPermission()
    }

    if (Notification.permission === 'granted') {
      const notification = new Notification(title, {
        icon: '/favicon.svg',
        ...options,
      })

      notification.onclick = () => {
        window.focus()
        notification.close()
      }
    }
  } catch (err) {
    console.warn('Unable to dispatch desktop notification:', err)
  }
}
