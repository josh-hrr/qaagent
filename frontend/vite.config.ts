import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

/**
 * Content-Security-Policy for the built app.
 *
 * This is the defence that matters for QA Agent: the product renders untrusted
 * text it did not write — Linear ticket descriptions, review comments, code from
 * diffs. `script-src 'self'` means that even if something malicious reaches the
 * DOM, the browser refuses to execute it.
 *
 * `style-src` keeps 'unsafe-inline' for now: it is a small weakening (styles
 * cannot exfiltrate a session the way scripts can) and can be tightened with
 * hashes once the app stops changing shape. `script-src` stays strict.
 *
 * Note: `frame-ancestors` is ignored in a <meta> tag — clickjacking protection
 * has to come from a real header on whatever serves index.html in production.
 */
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'",
  "font-src 'self' https://fonts.gstatic.com",
  "img-src 'self' data:",
  "connect-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join('; ')

/** Injected on `vite build` only — the dev server needs inline scripts and eval for HMR. */
function contentSecurityPolicy(): Plugin {
  return {
    name: 'qa-agent-csp',
    apply: 'build',
    transformIndexHtml(html) {
      return {
        html,
        tags: [
          {
            tag: 'meta',
            attrs: { 'http-equiv': 'Content-Security-Policy', content: CSP },
            injectTo: 'head-prepend',
          },
        ],
      }
    },
  }
}

// The dev server proxies /api to Django so the SPA and the API share an origin.
// That keeps the session cookie a plain first-party cookie — no CORS, no
// SameSite surprises, and the same shape as production behind one domain.
export default defineConfig({
  plugins: [react(), tailwindcss(), contentSecurityPolicy()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
})
