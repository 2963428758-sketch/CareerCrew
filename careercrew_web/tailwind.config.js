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
        display: [
          '"Inter"', "-apple-system", "BlinkMacSystemFont", '"Segoe UI"',
          '"PingFang SC"', '"Microsoft YaHei"', "sans-serif",
        ],
        sans: [
          '"Inter"', "-apple-system", "BlinkMacSystemFont", '"Segoe UI"',
          '"PingFang SC"', '"Microsoft YaHei"', "sans-serif",
        ],
        mono: [
          '"SFMono-Regular"', '"SF Mono"', '"Cascadia Code"',
          '"JetBrains Mono"', '"Roboto Mono"', "monospace",
        ],
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
        /* Codex 分层表面 */
        shell: "var(--shell)",
        workspace: "var(--workspace)",
        surface: {
          1: "var(--surface-1)",
          2: "var(--surface-2)",
          3: "var(--surface-3)",
        },
        ink: {
          DEFAULT: "var(--ink)",
          soft: "var(--ink-soft)",
          faint: "var(--ink-faint)",
        },
        button: {
          ink: "var(--button-ink)",
          onink: "var(--on-ink)",
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
        xs: "var(--radius-xs)",
        sm: "var(--radius-sm)",
        lg: "var(--radius)",
        md: "var(--radius-md)",
        xl: "var(--radius-xl)",
      },
      boxShadow: {
        workspace: "var(--shadow-workspace)",
        popover: "var(--shadow-popover)",
        prompt: "var(--shadow-prompt)",
      },
    },
  },
  plugins: [],
}
