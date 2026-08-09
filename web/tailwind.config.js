/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      fontFamily: {
        display: ['"Space Grotesk"', "-apple-system", '"PingFang SC"', '"Microsoft YaHei"', "sans-serif"],
        sans: ["-apple-system", "BlinkMacSystemFont", '"Segoe UI"', '"PingFang SC"', '"Microsoft YaHei"', "sans-serif"],
        mono: ['"SF Mono"', '"Cascadia Code"', '"JetBrains Mono"', "monospace"],
      },
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        sidebar: {
          DEFAULT: "hsl(var(--sidebar))",
          hover: "hsl(var(--sidebar-hover))",
          border: "hsl(var(--sidebar-border))",
          text: "hsl(var(--sidebar-text))",
          active: "hsl(var(--sidebar-text-active))",
        },
        /* Agent 身份色系 */
        agent: {
          matcher: "#0D9488",    /* 深青 - 职位匹配官 */
          resume: "#D97706",     /* 琥珀 - 简历顾问 */
          interviewer: "#BE185D", /* 玫红 - 面试官 */
          salary: "#7C3AED",     /* 紫罗兰 - 薪资谈判师 */
          planner: "#2563EB",    /* 钴蓝 - 职业规划师 */
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [],
}
