import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 개발 서버가 /query 요청을 FastAPI 백엔드(uvicorn, 8000번)로 넘긴다. 백엔드 CORS 설정은 필요 없다.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/query': 'http://127.0.0.1:8000',
    },
  },
})
