import { ref, computed, onUnmounted } from 'vue'
import { Capacitor } from '@capacitor/core'

export interface PeerInfo {
  client_id: string
  user_id?: string | null
  user_name: string
  avatar_url?: string | null
  color: string
  current_measure: number
  current_staff: number
  current_tool: string
}

export interface ScoreDeltaEvent {
  musicxml: string
  author: string
  client_id: string
  description: string
}

export function useCollaboration(
  jobIdGetter: () => string | undefined,
  shareTokenGetter?: () => string | undefined,
) {
  const isConnected = ref(false)
  const myClientId = ref<string>('')
  const myColor = ref<string>('#6366f1')
  const peers = ref<Map<string, PeerInfo>>(new Map())
  const lockedMeasures = ref<Map<number, string>>(new Map()) // measure -> holder_name

  let ws: WebSocket | null = null
  let reconnectTimer: number | null = null
  let pingTimer: number | null = null
  let reconnectAttempts = 0
  const maxReconnectDelay = 10000

  // Event callbacks
  let onScoreDeltaCallback: ((event: ScoreDeltaEvent) => void) | null = null
  const pendingLockRequests = new Map<number, (granted: boolean) => void>()

  const peerList = computed(() => Array.from(peers.value.values()))
  const activeCollaboratorsCount = computed(() => peers.value.size + (isConnected.value ? 1 : 0))

  const acquireStreamTicket = async (): Promise<string | null> => {
    const token = localStorage.getItem('token')
    if (!token) return null
    try {
      const res = await fetch('/api/auth/stream-ticket', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) {
        const data = await res.json()
        return data.ticket || null
      }
    } catch (err) {
      console.warn('[Collaboration WS] Failed to acquire stream ticket:', err)
    }
    return null
  }

  const getWsUrl = (jobId: string, streamTicket?: string | null): string => {
    const loc = window.location
    const token = localStorage.getItem('token') || ''
    const userEmail = localStorage.getItem('user_email') || ''
    const guestName = userEmail ? userEmail.split('@')[0] : 'Musician'
    const shareToken = shareTokenGetter?.()
    const query = new URLSearchParams()
    if (streamTicket) {
      query.set('token', streamTicket)
    } else if (token) {
      query.set('token', token)
    }
    if (shareToken) {
      query.set('share_token', shareToken)
    }
    query.set('guest_name', guestName)

    if (import.meta.env.VITE_WS_BASE_URL) {
      const baseWs = import.meta.env.VITE_WS_BASE_URL.replace(/\/+$/, '')
      return `${baseWs}/api/ws/studio/${jobId}?${query.toString()}`
    }

    if (import.meta.env.VITE_API_BASE_URL) {
      try {
        const apiUrl = new URL(import.meta.env.VITE_API_BASE_URL)
        const wsProto = apiUrl.protocol === 'https:' ? 'wss:' : 'ws:'
        return `${wsProto}//${apiUrl.host}/api/ws/studio/${jobId}?${query.toString()}`
      } catch {}
    }

    const isNative = Capacitor.isNativePlatform()
    const protocol = isNative ? 'ws:' : (loc.protocol === 'https:' ? 'wss:' : 'ws:')
    const isDev = loc.port === '5173'
    const host = (isDev || isNative) ? `${loc.hostname}:8000` : loc.host
    return `${protocol}//${host}/api/ws/studio/${jobId}?${query.toString()}`
  }

  const connect = async () => {
    const jobId = jobIdGetter()
    if (!jobId) return

    cleanupSocket()

    try {
      const streamTicket = await acquireStreamTicket()
      const url = getWsUrl(jobId, streamTicket)
      ws = new WebSocket(url)

      ws.onopen = () => {
        isConnected.value = true
        reconnectAttempts = 0
        startHeartbeat()
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          handleIncomingMessage(data)
        } catch (err) {
          console.error('[Collaboration WS] Failed to parse message:', err)
        }
      }

      ws.onclose = () => {
        isConnected.value = false
        stopHeartbeat()
        scheduleReconnect()
      }

      ws.onerror = (err) => {
        console.warn('[Collaboration WS] Connection error:', err)
        ws?.close()
      }
    } catch (err) {
      console.error('[Collaboration WS] Connection initialization failed:', err)
      scheduleReconnect()
    }
  }

  const handleIncomingMessage = (data: any) => {
    switch (data.type) {
      case 'room_state': {
        myClientId.value = data.your_client_id
        myColor.value = data.your_color
        const newPeers = new Map<string, PeerInfo>()
        if (Array.isArray(data.peers)) {
          for (const p of data.peers) {
            if (p.client_id !== myClientId.value) {
              newPeers.set(p.client_id, p)
            }
          }
        }
        peers.value = newPeers

        const newLocks = new Map<number, string>()
        if (data.locks && typeof data.locks === 'object') {
          for (const [m, holder] of Object.entries(data.locks)) {
            newLocks.set(Number(m), String(holder))
          }
        }
        lockedMeasures.value = newLocks
        break
      }

      case 'peer_joined': {
        if (data.peer && data.peer.client_id !== myClientId.value) {
          const newMap = new Map(peers.value)
          newMap.set(data.peer.client_id, data.peer)
          peers.value = newMap
        }
        break
      }

      case 'peer_left': {
        if (data.client_id) {
          const newMap = new Map(peers.value)
          newMap.delete(data.client_id)
          peers.value = newMap
        }
        break
      }

      case 'presence_update': {
        if (data.peer && data.peer.client_id !== myClientId.value) {
          const newMap = new Map(peers.value)
          newMap.set(data.peer.client_id, data.peer)
          peers.value = newMap
        }
        break
      }

      case 'measure_locked': {
        const m = Number(data.measure)
        const holder = String(data.holder_name || 'Collaborator')
        const newLocks = new Map(lockedMeasures.value)
        newLocks.set(m, holder)
        lockedMeasures.value = newLocks
        break
      }

      case 'measure_unlocked': {
        const m = Number(data.measure)
        const newLocks = new Map(lockedMeasures.value)
        newLocks.delete(m)
        lockedMeasures.value = newLocks
        break
      }

      case 'lock_ack': {
        const measureNum = Number(data.measure)
        const callback = pendingLockRequests.get(measureNum)
        if (callback) {
          callback(Boolean(data.acquired))
          pendingLockRequests.delete(measureNum)
        }
        break
      }

      case 'score_delta': {
        if (onScoreDeltaCallback && data.client_id !== myClientId.value) {
          onScoreDeltaCallback({
            musicxml: data.musicxml,
            author: data.author,
            client_id: data.client_id,
            description: data.description,
          })
        }
        break
      }

      case 'pong':
        break
    }
  }

  const broadcastPresence = (measure: number, staff: number, tool: string) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'presence',
        measure,
        staff,
        tool,
      }))
    }
  }

  const requestMeasureLock = (measure: number): Promise<boolean> => {
    return new Promise((resolve) => {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        resolve(false)
        return
      }

      let timeoutId: number | null = null
      const handleResult = (granted: boolean) => {
        if (timeoutId !== null) {
          clearTimeout(timeoutId)
          timeoutId = null
        }
        pendingLockRequests.delete(measure)
        resolve(granted)
      }

      pendingLockRequests.set(measure, handleResult)

      ws.send(JSON.stringify({
        type: 'measure_lock',
        measure,
      }))

      // Fallback timeout in case of latency: resolve false
      timeoutId = window.setTimeout(() => {
        handleResult(false)
      }, 1500)
    })
  }

  const releaseMeasureLock = (measure: number) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'measure_unlock',
        measure,
      }))
    }
  }

  const broadcastMutation = (musicxml: string, description: string = 'Notation update') => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'score_mutation',
        musicxml,
        description,
      }))
    }
  }

  const onScoreDelta = (cb: (event: ScoreDeltaEvent) => void) => {
    onScoreDeltaCallback = cb
  }

  const startHeartbeat = () => {
    stopHeartbeat()
    pingTimer = window.setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, 20000)
  }

  const stopHeartbeat = () => {
    if (pingTimer) {
      clearInterval(pingTimer)
      pingTimer = null
    }
  }

  const scheduleReconnect = () => {
    if (reconnectTimer) return
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), maxReconnectDelay)
    reconnectAttempts++
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      connect()
    }, delay)
  }

  const cleanupSocket = () => {
    stopHeartbeat()
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    for (const callback of pendingLockRequests.values()) {
      callback(false)
    }
    pendingLockRequests.clear()
    if (ws) {
      ws.onopen = null
      ws.onmessage = null
      ws.onerror = null
      ws.onclose = null
      ws.close()
      ws = null
    }
    isConnected.value = false
  }

  onUnmounted(() => {
    cleanupSocket()
  })

  return {
    isConnected,
    myClientId,
    myColor,
    peers,
    peerList,
    lockedMeasures,
    activeCollaboratorsCount,
    connect,
    disconnect: cleanupSocket,
    broadcastPresence,
    requestMeasureLock,
    releaseMeasureLock,
    broadcastMutation,
    onScoreDelta,
  }
}
