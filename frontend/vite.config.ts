import vue from '@vitejs/plugin-vue'
import { defineConfig, type Plugin } from 'vite'

function inlineCriticalCss(): Plugin {
  return {
    name: 'inline-critical-css',
    apply: 'build',
    enforce: 'post',
    transformIndexHtml(html, ctx) {
      if (!ctx.bundle) return html
      for (const [fileName, chunk] of Object.entries(ctx.bundle)) {
        if (fileName.endsWith('.css') && fileName.startsWith('assets/index-')) {
          if ('source' in chunk && typeof chunk.source === 'string') {
            const cssContent = chunk.source
            // Remove the render-blocking stylesheet link tag
            const linkTagRegex = new RegExp(`<link[^>]+href="[/]?[^"]*${fileName.replace(/^assets\//, '')}"[^>]*>`, 'g')
            html = html.replace(linkTagRegex, '')
            const fullLinkRegex = new RegExp(`<link[^>]+href="[/]?${fileName}"[^>]*>`, 'g')
            html = html.replace(fullLinkRegex, '')
            // Inject inline critical style into head
            html = html.replace('</head>', `<style>${cssContent}</style>\n  </head>`)
            // Retain the file in ctx.bundle so dynamic imports that reference it find the file on disk without 404
            break
          }
        }
      }
      return html
    }
  }
}

export default defineConfig({
  plugins: [vue(), inlineCriticalCss()],
  build: {
    modulePreload: {
      resolveDependencies(_url, deps) {
        // Exclude inlined index css from dynamic import preload chains
        return deps.filter((dep) => !(dep.includes('assets/index-') && dep.endsWith('.css')))
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
