import type { CapacitorConfig } from '@capacitor/cli';

// The backend URL is baked in at build time via VITE_API_URL
// (see frontend/src/api.ts). For a local dev server on your machine:
//   VITE_API_URL=http://<your-lan-ip>:8772 bun run build
// The GitHub Actions workflow builds the APK with the URL you give it.
const config: CapacitorConfig = {
  appId: 'com.stip.app',
  appName: 'STIP',
  webDir: 'dist',
  server: {
    // http (not https) so ws:// realtime + http:// API URLs are not
    // treated as mixed content inside the WebView.
    androidScheme: 'http',
  },
};

export default config;
