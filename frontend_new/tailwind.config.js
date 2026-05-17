/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        hud: {
          bg: 'var(--hud-bg)',
          panel: 'var(--hud-panel-bg)',
          border: 'var(--hud-border-color)',
          text: 'var(--hud-text)',
          accent: 'var(--hud-accent)',
          /** Legacy `.hud-header__status--offline` */
          offline: 'hsl(0 14% 48%)',
        },
      },
      borderRadius: {
        hud: 'var(--hud-radius)',
      },
      spacing: {
        'hud-panel': 'var(--hud-panel-pad)',
      },
      fontFamily: {
        hud: [
          'system-ui',
          '"Segoe UI"',
          'Roboto',
          'Helvetica',
          'Arial',
          'sans-serif',
        ],
      },
      lineHeight: {
        hud: '1.5',
      },
    },
  },
}
