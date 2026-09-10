import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// 백엔드 개발 서버 주소. 프론트(5173)와 오리진이 다르면 쿠키(SameSite=lax) 문제가 생기므로
// 브라우저에는 5173 한 오리진만 노출하고 `/auth` 요청만 여기로 넘긴다.
const BACKEND_ORIGIN = "http://localhost:8000";
const AUTH_PATH_PREFIX = "/auth";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // 백엔드에 CORS 미들웨어가 없어서, 크로스 오리진 대신 same-origin 프록시로 우회한다.
      [AUTH_PATH_PREFIX]: {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
      },
    },
  },
});
