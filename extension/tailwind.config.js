/**
 * Graphite design system — token map for DevScope.
 *
 * Surfaces, text and borders are backed by CSS variables (see tailwind.css)
 * that flip between light and dark in the `.dark` scope, so a single utility
 * class (e.g. `bg-surface`, `text-fg`) renders correctly in both themes — no
 * `dark:` duplication across the component tree.
 *
 * @type {import('tailwindcss').Config}
 */
export default {
  content: ['./src/**/*.{ts,tsx}', './public/**/*.html', './*.html'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Surfaces — app bg / sidebar / cards
        surface: {
          DEFAULT: 'rgb(var(--surface-base) / <alpha-value>)',
          raised: 'rgb(var(--surface-raised) / <alpha-value>)',
          overlay: 'rgb(var(--surface-overlay) / <alpha-value>)',
        },
        // Foreground text
        fg: {
          DEFAULT: 'rgb(var(--fg-primary) / <alpha-value>)',
          muted: 'rgb(var(--fg-secondary) / <alpha-value>)',
          subtle: 'rgb(var(--fg-tertiary) / <alpha-value>)',
        },
        // Borders / dividers — `border-line`, `border-line-strong`
        line: {
          DEFAULT: 'rgb(var(--line-subtle) / <alpha-value>)',
          strong: 'rgb(var(--line-strong) / <alpha-value>)',
        },
        // Accent — warm amber signal
        signal: {
          DEFAULT: 'rgb(var(--signal) / <alpha-value>)',
          hover: 'rgb(var(--signal-hover) / <alpha-value>)',
          subtle: 'rgb(var(--signal-subtle) / <alpha-value>)',
          contrast: 'rgb(var(--signal-contrast) / <alpha-value>)',
        },
        // Semantic
        success: {
          DEFAULT: 'rgb(var(--success) / <alpha-value>)',
          subtle: 'rgb(var(--success-subtle) / <alpha-value>)',
        },
        warning: {
          DEFAULT: 'rgb(var(--warning) / <alpha-value>)',
          subtle: 'rgb(var(--warning-subtle) / <alpha-value>)',
        },
        danger: {
          DEFAULT: 'rgb(var(--danger) / <alpha-value>)',
          subtle: 'rgb(var(--danger-subtle) / <alpha-value>)',
        },
        // Agent identity (static brand colors — use /10 alpha for tints)
        claude: '#CC785C',
        cursor: '#7C6AF5',
      },
      fontFamily: {
        sans: [
          'Inter Variable',
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          'sans-serif',
        ],
        mono: [
          'JetBrains Mono Variable',
          'JetBrains Mono',
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Monaco',
          'Consolas',
          'monospace',
        ],
      },
      fontSize: {
        '2xs': ['11px', { lineHeight: '16px' }],
        xs: ['12px', { lineHeight: '16px' }],
        sm: ['13px', { lineHeight: '20px' }],
        base: ['14px', { lineHeight: '22px' }],
        md: ['14px', { lineHeight: '22px' }],
        lg: ['16px', { lineHeight: '24px' }],
      },
      borderRadius: {
        sm: '4px',
        md: '6px',
        lg: '10px',
        xl: '14px',
      },
      boxShadow: {
        tool: '0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04)',
        modal: '0 8px 32px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.06)',
        'modal-dark': '0 8px 40px rgba(0,0,0,0.40), 0 2px 12px rgba(0,0,0,0.24)',
      },
      transitionDuration: {
        fast: '120ms',
      },
      transitionTimingFunction: {
        tool: 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
      keyframes: {
        'cursor-pulse': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.25' },
        },
        // Gradient sweep across text (ThinkingBlock's "חושב…" label) — a
        // moving highlight rather than cursor-pulse's harder on/off blink.
        shimmer: {
          '0%': { backgroundPosition: '150% 0' },
          '100%': { backgroundPosition: '-150% 0' },
        },
        // ClaudeSpark's idle "breathing" — gentle open/close scale with a
        // matching opacity dip, distinct from cursor-pulse's harder blink.
        'spark-breathe': {
          '0%, 100%': { transform: 'scale(0.75)', opacity: '0.7' },
          '50%': { transform: 'scale(1)', opacity: '1' },
        },
      },
      animation: {
        'cursor-pulse': 'cursor-pulse 1.2s ease-in-out infinite',
        shimmer: 'shimmer 1.6s linear infinite',
        'spark-breathe': 'spark-breathe 1.2s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
