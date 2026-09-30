/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        orbitron: ['Orbitron', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      scale: {
        115: '1.15',
      },
    },
  },
}
