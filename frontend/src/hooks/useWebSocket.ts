import { useCallback, useEffect, useRef, useState } from 'react';
import { api, getToken } from '../api';
import type { WSFrame } from '../types';

/**
 * WebSocket hook with exponential-backoff reconnect.
 * Handlers are registered via on(handler); frames are parsed once and
 * dispatched to every registered handler. Handler errors never break the socket.
 */
export function useWebSocket(enabled: boolean) {
  const [connected, setConnected] = useState(false);
  const handlers = useRef(new Set<(f: WSFrame) => void>());
  const retryRef = useRef(0);
  const wsRef = useRef<WebSocket | null>(null);
  const closedRef = useRef(false);

  const on = useCallback((h: (f: WSFrame) => void) => {
    handlers.current.add(h);
    return () => {
      handlers.current.delete(h);
    };
  }, []);

  const send = useCallback((data: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  }, []);

  useEffect(() => {
    if (!enabled || !getToken()) return;
    closedRef.current = false;
    let pingTimer: number | undefined;
    let retryTimer: number | undefined;

    const connect = () => {
      if (closedRef.current) return;
      const scheduleRetry = () => {
        if (closedRef.current) return;
        const backoff = Math.min(1000 * 2 ** retryRef.current, 15000);
        retryRef.current += 1;
        retryTimer = window.setTimeout(connect, backoff);
      };
      let ws: WebSocket;
      try {
        ws = new WebSocket(api.wsUrl());
      } catch {
        scheduleRetry();
        return;
      }
      wsRef.current = ws;
      ws.onopen = () => {
        setConnected(true);
        retryRef.current = 0;
        pingTimer = window.setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send('ping');
        }, 25000);
      };
      ws.onmessage = (ev) => {
        try {
          const frame = JSON.parse(ev.data as string) as WSFrame;
          handlers.current.forEach((h) => {
            try {
              h(frame);
            } catch {
              /* handler errors must not break the socket */
            }
          });
        } catch {
          /* non-JSON keep-alive echoes are ignored */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (pingTimer) window.clearInterval(pingTimer);
        scheduleRetry();
      };
      ws.onerror = () => {
        try {
          ws.close();
        } catch {
          /* noop */
        }
      };
    };
    connect();
    return () => {
      closedRef.current = true;
      if (pingTimer) window.clearInterval(pingTimer);
      if (retryTimer) window.clearTimeout(retryTimer);
      try {
        wsRef.current?.close();
      } catch {
        /* noop */
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  return { connected, on, send };
}

export type WSApi = ReturnType<typeof useWebSocket>;
