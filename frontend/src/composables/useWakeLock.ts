import { ref, onMounted, onUnmounted } from 'vue';

/**
 * Screen Wake Lock Composable
 * Prevents mobile screens and tablet displays from dimming or locking
 * during live rehearsal or score reading sessions.
 */
export function useWakeLock() {
  const isSupported = ref(
    typeof navigator !== 'undefined' && 'wakeLock' in navigator
  );
  const isActive = ref(false);
  let sentinel: any = null;

  async function requestWakeLock() {
    if (!isSupported.value) return false;
    try {
      if (sentinel && !sentinel.released) {
        isActive.value = true;
        return true;
      }
      sentinel = await (navigator as any).wakeLock.request('screen');
      isActive.value = true;

      sentinel.addEventListener('release', () => {
        isActive.value = false;
        sentinel = null;
      });
      return true;
    } catch (err) {
      console.warn('Wake Lock request denied or unsupported:', err);
      isActive.value = false;
      return false;
    }
  }

  async function releaseWakeLock() {
    if (sentinel) {
      try {
        await sentinel.release();
      } catch (err) {
        console.warn('Wake Lock release error:', err);
      }
      sentinel = null;
      isActive.value = false;
    }
  }

  // Automatically re-request lock when app returns to foreground
  const handleVisibilityChange = async () => {
    if (document.visibilityState === 'visible' && isActive.value && !sentinel) {
      await requestWakeLock();
    }
  };

  onMounted(() => {
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibilityChange);
    }
  });

  onUnmounted(() => {
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    }
    releaseWakeLock();
  });

  return {
    isSupported,
    isActive,
    requestWakeLock,
    releaseWakeLock,
  };
}
