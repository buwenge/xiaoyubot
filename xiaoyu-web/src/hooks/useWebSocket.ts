"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { WsDownMessage } from "@/lib/types";

interface UseWebSocketOptions {
  url: string;
  secret: string;
  onMessage: (msg: WsDownMessage) => void;
}

export function useWebSocket({ url, secret, onMessage }: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;
  const retriesRef = useRef(0);
  const heartbeatRef = useRef<ReturnType<typeof setInterval>>();

  const connect = useCallback(() => {
    if (!url || !secret) return;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "auth", secret }));
    };

    ws.onmessage = (event) => {
      try {
        const msg: WsDownMessage = JSON.parse(event.data);
        if (msg.type === "auth_ok") {
          setIsConnected(true);
          retriesRef.current = 0;
          ws.send(JSON.stringify({ type: "get_history", channel: "xiaoyu" }));
          ws.send(JSON.stringify({ type: "get_history", channel: "sonnet" }));
          ws.send(JSON.stringify({ type: "get_history", channel: "group" }));
          ws.send(JSON.stringify({ type: "get_status" }));
          ws.send(JSON.stringify({ type: "get_logs", limit: 50 }));
          heartbeatRef.current = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: "ping" }));
            }
          }, 30000);
          return;
        }
        onMessageRef.current(msg);
      } catch {}
    };

    ws.onclose = () => {
      setIsConnected(false);
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      const delay = Math.min(1000 * 2 ** retriesRef.current, 30000);
      retriesRef.current++;
      setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [url, secret]);

  useEffect(() => {
    connect();
    return () => {
      retriesRef.current = Infinity; // prevent reconnect on unmount
      wsRef.current?.close();
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
    };
  }, [connect]);

  const send = useCallback((data: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  return { isConnected, send };
}
