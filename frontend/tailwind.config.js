/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Field console — dark, high-contrast, readable in field conditions.
        forge: {
          bg: "#0a0e14",
          panel: "#111722",
          edge: "#1e2733",
          accent: "#7c3aed", // violet — agent/brain
          live: "#22c55e", // green — connected/listening
          warn: "#f59e0b", // amber — caution / threshold near
          alert: "#ef4444", // red — threshold crossed / hazard
          vision: "#06b6d4", // cyan — vision active
          text: "#e5edf5",
          muted: "#7d8da3",
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      keyframes: {
        pulseRing: {
          "0%, 100%": { opacity: "0.4" },
          "50%": { opacity: "1" },
        },
      },
      animation: {
        pulseRing: "pulseRing 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
