/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        card: "var(--card)",
        muted: "var(--muted)",
        "muted-foreground": "var(--muted-foreground)",
        secondary: "var(--secondary)",
        border: "var(--border)",
        sidebar: "var(--sidebar)",
        "sidebar-foreground": "var(--sidebar-foreground)",
        destructive: "var(--destructive)",
      },
      boxShadow: {
        card: "var(--shadow-card)",
        composer: "var(--shadow-composer)",
        "composer-focus": "var(--shadow-composer-focus)",
        float: "var(--shadow-float)",
      },
      transitionTimingFunction: {
        spring: "var(--ease-spring)",
      },
    },
  },
  plugins: [],
};
