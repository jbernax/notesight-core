<script setup lang="ts">
import { activeToasts, dismissToast, type ToastItem } from '../composables/useToast'

const handleAction = (toast: ToastItem) => {
  if (toast.onAction) {
    toast.onAction()
  }
  dismissToast(toast.id)
}
</script>

<template>
  <teleport to="body">
    <div class="toast-viewport" aria-live="polite" aria-atomic="true">
      <transition-group name="toast-anim" tag="div" class="toast-list">
        <div
          v-for="toast in activeToasts"
          :key="toast.id"
          class="toast-card"
          :class="toast.type"
          role="status"
        >
          <div class="toast-icon-col">
            <svg v-if="toast.type === 'success'" class="toast-icon success" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <path d="M20 6L9 17l-5-5"></path>
            </svg>
            <svg v-else-if="toast.type === 'error'" class="toast-icon error" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
            <svg v-else-if="toast.type === 'warning'" class="toast-icon warning" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
              <line x1="12" y1="9" x2="12" y2="13"></line>
              <line x1="12" y1="17" x2="12.01" y2="17"></line>
            </svg>
            <svg v-else class="toast-icon info" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="16" x2="12" y2="12"></line>
              <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>
          </div>

          <div class="toast-content-col">
            <h5 class="toast-title">{{ toast.title }}</h5>
            <p class="toast-message">{{ toast.message }}</p>
            <div v-if="toast.actionLabel" class="toast-action-row">
              <button class="toast-action-btn" @click="handleAction(toast)">
                {{ toast.actionLabel }}
              </button>
            </div>
          </div>

          <button
            class="toast-close-btn"
            aria-label="Dismiss notification"
            @click="dismissToast(toast.id)"
          >
            ✕
          </button>
        </div>
      </transition-group>
    </div>
  </teleport>
</template>

<style scoped>
.toast-viewport {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  pointer-events: none;
  max-width: 420px;
  width: calc(100vw - 32px);
}

.toast-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.toast-card {
  pointer-events: auto;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 12px;
  background: var(--bg-card, #1e293b);
  border: 1px solid var(--border, #334155);
  box-shadow: var(--shadow-lg, 0 10px 25px -5px rgba(0, 0, 0, 0.4), 0 8px 10px -6px rgba(0, 0, 0, 0.3));
  color: var(--text-primary, #f8fafc);
  backdrop-filter: blur(12px);
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.toast-card.success {
  border-left: 4px solid var(--color-success, #10b981);
}

.toast-card.error {
  border-left: 4px solid var(--color-danger, #ef4444);
}

.toast-card.warning {
  border-left: 4px solid var(--color-warning, #f59e0b);
}

.toast-card.info {
  border-left: 4px solid var(--color-primary, #3b82f6);
}

.toast-icon-col {
  flex-shrink: 0;
  margin-top: 2px;
}

.toast-icon {
  width: 20px;
  height: 20px;
}

.toast-icon.success {
  color: var(--color-success, #10b981);
}

.toast-icon.error {
  color: var(--color-danger, #ef4444);
}

.toast-icon.warning {
  color: var(--color-warning, #f59e0b);
}

.toast-icon.info {
  color: var(--color-primary, #3b82f6);
}

.toast-content-col {
  flex: 1;
  min-width: 0;
}

.toast-title {
  margin: 0 0 3px 0;
  font-size: 0.92rem;
  font-weight: 600;
  color: var(--text-primary, #f8fafc);
}

.toast-message {
  margin: 0;
  font-size: 0.84rem;
  line-height: 1.35;
  color: var(--text-secondary, #94a3b8);
  word-break: break-word;
}

.toast-action-row {
  margin-top: 8px;
}

.toast-action-btn {
  display: inline-flex;
  align-items: center;
  padding: 6px 14px;
  font-size: 0.8rem;
  font-weight: 600;
  border-radius: 6px;
  background: var(--color-primary, #3b82f6);
  color: #ffffff;
  border: none;
  cursor: pointer;
  transition: background 0.15s ease, transform 0.1s ease;
  min-height: 36px;
}

.toast-action-btn:hover {
  background: var(--primary-hover, #2563eb);
  transform: translateY(-1px);
}

.toast-close-btn {
  flex-shrink: 0;
  background: transparent;
  border: none;
  color: var(--text-muted, #94a3b8);
  cursor: pointer;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  font-size: 0.85rem;
  line-height: 1;
  transition: color 0.15s ease, background 0.15s ease;
}

.toast-close-btn:hover {
  color: var(--text-main, #f8fafc);
  background: var(--bg-hover);
}

@media (max-width: 768px) {
  .toast-viewport {
    bottom: calc(var(--mobile-bottom-offset, 60px) + 14px);
    right: 12px;
    left: 12px;
    width: auto;
    max-width: none;
  }
}

/* Animations */
.toast-anim-enter-active,
.toast-anim-leave-active {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.toast-anim-enter-from {
  opacity: 0;
  transform: translateY(20px) scale(0.95);
}

.toast-anim-leave-to {
  opacity: 0;
  transform: translateX(30px) scale(0.95);
}
</style>
