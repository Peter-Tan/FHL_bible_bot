import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Served under /bible_bot/ behind nginx; API is proxied to the FastAPI
// backend (nginx strips the /bible_bot prefix, so dev does too).
export default defineConfig({
  base: "/bible_bot/",
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/bible_bot/api": {
        target: "http://127.0.0.1:7861",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/bible_bot/, ""),
      },
    },
  },
});
