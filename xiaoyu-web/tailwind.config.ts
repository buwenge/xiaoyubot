import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        warm: {
          bg: "var(--bg-primary)",
          "bg-alt": "var(--bg-secondary)",
          chat: "var(--bg-chat)",
          assistant: "var(--bg-assistant)",
          text: "var(--text-primary)",
          "text-secondary": "var(--text-secondary)",
          accent: "var(--accent)",
          "accent-light": "var(--accent-light)",
          border: "var(--border)",
          thinking: "var(--thinking-bg)",
          "forge-bg": "var(--forge-bg)",
          "forge-border": "var(--forge-border)",
        },
      },
      fontFamily: {
        serif: ['"Noto Serif SC"', "Georgia", "serif"],
      },
    },
  },
  plugins: [],
};
export default config;
