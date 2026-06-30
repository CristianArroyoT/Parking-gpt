/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,ts,tsx,js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      colors: {
        park: {
          libre: '#10b981',
          ocupado: '#f43f5e',
          alerta: '#f59e0b',
          inactivo: '#64748b',
          marca: '#0f172a',
          acento: '#2563eb',
        },
      },
    },
  },
  plugins: [],
}