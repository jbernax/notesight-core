/// <reference types="vite/client" />

declare module 'vue' {
  interface ComponentCustomProperties {
    $t: (key: string, params?: Record<string, string | number>) => string
  }
}

export {}
