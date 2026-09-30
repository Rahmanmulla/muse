import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
    plugins: [react()],
    server: {
        proxy: {
            '/auth': 'http://127.0.0.1:8772',
            '/users': 'http://127.0.0.1:8772',
            '/conversations': 'http://127.0.0.1:8772',
            '/media': 'http://127.0.0.1:8772',
            '/catalog': 'http://127.0.0.1:8772',
            '/inventory': 'http://127.0.0.1:8772',
            '/collection': 'http://127.0.0.1:8772',
            '/favorites': 'http://127.0.0.1:8772',
            '/loadouts': 'http://127.0.0.1:8772',
            '/wallet': 'http://127.0.0.1:8772',
            '/shop': 'http://127.0.0.1:8772',
            '/gifts': 'http://127.0.0.1:8772',
            '/rewards': 'http://127.0.0.1:8772',
            '/streaks': 'http://127.0.0.1:8772',
            '/notifications': 'http://127.0.0.1:8772',
            '/events': 'http://127.0.0.1:8772',
            '/achievements': 'http://127.0.0.1:8772',
            '/profile': 'http://127.0.0.1:8772',
            '/flags': 'http://127.0.0.1:8772',
            '/reports': 'http://127.0.0.1:8772',
            '/admin': 'http://127.0.0.1:8772',
            '/ws': { target: 'http://127.0.0.1:8772', ws: true },
        },
    },
});
