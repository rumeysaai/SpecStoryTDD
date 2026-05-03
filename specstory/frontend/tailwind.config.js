/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{jsx,js}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["DM Sans", "system-ui", "sans-serif"],
        display: ["Instrument Sans", "system-ui", "sans-serif"],
      },
      colors: {
        ink: { 950: "#0c0f14", 900: "#141922", 800: "#1c2330", 700: "#2a3344" },
        mist: { 400: "#8b98ad", 300: "#aab6c9", 200: "#c9d1de", 100: "#e8ecf2" },
        accent: { DEFAULT: "#e85d4c", muted: "#c94a3d" },
        amber: { panel: "#f59e0b" },
      },
      boxShadow: {
        panel: "0 4px 24px rgba(12, 15, 20, 0.35)",
      },
    },
  },
  plugins: [],
};
