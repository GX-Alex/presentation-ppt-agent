/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: "#EEF2FF",
          100: "#E0E7FF",
          200: "#C7D2FE",
          300: "#A5B4FC",
          400: "#818CF8",
          500: "#6366F1",
          600: "#4F46E5",
          700: "#4338CA",
          800: "#3730A3",
          900: "#312E81",
          950: "#1E1B4B",
        },
        canvas: "#EEEEF0",
        surface: "#FFFFFF",
        neon: {
          bg: "#0A0A0C",
          border: "rgba(99,102,241,0.25)",
          glow: "#818CF8",
        },
      },
      borderRadius: {
        bento: "20px",
      },
      boxShadow: {
        bento: "0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.03)",
        "bento-hover": "0 2px 8px rgba(0,0,0,0.06), 0 8px 24px rgba(0,0,0,0.05)",
        glass: "0 8px 32px rgba(0,0,0,0.08)",
        neon: "0 0 20px rgba(99,102,241,0.12), 0 0 60px rgba(99,102,241,0.04)",
      },
      fontFamily: {
        mono: ['"SF Mono"', '"Fira Code"', '"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
};
