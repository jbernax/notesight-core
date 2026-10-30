import { onMounted, onUnmounted, ref } from 'vue';
import { useNativePlatform } from './useNativePlatform';

export interface PedalOptions {
  nextKeys?: string[];
  prevKeys?: string[];
  debounceMs?: number;
  enableHaptics?: boolean;
}

const DEFAULT_NEXT_KEYS = ['PageDown', 'ArrowRight', 'ArrowDown'];
const DEFAULT_PREV_KEYS = ['PageUp', 'ArrowLeft', 'ArrowUp'];

/**
 * Bluetooth & USB Hardware Page Turner Pedal Composable
 * Listens for hardware footswitch signals and dispatches hands-free
 * page-turning and measure-jumping actions.
 */
export function usePedalNavigation(
  onNext: () => void,
  onPrev: () => void,
  options?: PedalOptions
) {
  const { triggerHapticLight } = useNativePlatform();
  const nextKeys = options?.nextKeys || DEFAULT_NEXT_KEYS;
  const prevKeys = options?.prevKeys || DEFAULT_PREV_KEYS;
  const debounceMs = options?.debounceMs ?? 180;
  const enableHaptics = options?.enableHaptics ?? true;

  const isEnabled = ref(true);
  let lastTriggerTime = 0;

  function handleKeyDown(event: KeyboardEvent) {
    if (!isEnabled.value) return;

    // Guard: ignore when typing inside editable fields
    const activeEl = document.activeElement;
    if (activeEl) {
      const tag = activeEl.tagName.toLowerCase();
      if (
        tag === 'input' ||
        tag === 'textarea' ||
        activeEl.getAttribute('contenteditable') === 'true'
      ) {
        return;
      }
    }

    const key = event.key;
    const now = Date.now();

    if (nextKeys.includes(key)) {
      if (now - lastTriggerTime < debounceMs) return;
      lastTriggerTime = now;
      event.preventDefault();
      if (enableHaptics) triggerHapticLight();
      onNext();
    } else if (prevKeys.includes(key)) {
      if (now - lastTriggerTime < debounceMs) return;
      lastTriggerTime = now;
      event.preventDefault();
      if (enableHaptics) triggerHapticLight();
      onPrev();
    }
  }

  onMounted(() => {
    if (typeof window !== 'undefined') {
      window.addEventListener('keydown', handleKeyDown);
    }
  });

  onUnmounted(() => {
    if (typeof window !== 'undefined') {
      window.removeEventListener('keydown', handleKeyDown);
    }
  });

  return {
    isEnabled,
  };
}
