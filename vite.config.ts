import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("/node_modules/react") || id.includes("/node_modules/scheduler")) return "react";
          if (id.includes("/node_modules/antd/es/")) {
            const component = id.split("/node_modules/antd/es/")[1]?.split("/")[0] || "core";
            return `antd-${component.replace(/^_/, "internal-")}`;
          }
          if (id.includes("/node_modules/@ant-design/")) return "ant-design";
          if (id.includes("/node_modules/@rc-component/") || id.includes("/node_modules/rc-")) return "rc-components";
          if (id.includes("/node_modules/lucide-react/")) return "icons";
          if (id.includes("/node_modules/dompurify/")) return "dompurify";
        }
      }
    }
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000"
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts"
  }
});
