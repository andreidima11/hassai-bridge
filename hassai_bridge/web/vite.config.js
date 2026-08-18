import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../app/static",
    emptyOutDir: false,
    assetsDir: "assets/chat",
  },
});
