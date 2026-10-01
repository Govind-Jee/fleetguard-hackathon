/**
 * FleetGuard Pulse — Reconnecting Live Alerts WebSocket Hook.
 * Manages persistent connection to /ws/alerts, bounded alert buffer,
 * client-side deduplication, heartbeat pinging, and exponential backoff.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getAuthToken } from '../services/auth';
import { WSAlertPayload, WSConnectionStatus, WSIncomingFrame } from '../types/ws';

const MAX_ALERT_HISTORY = 50;
const INITIAL_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 15000;
const HEARTBEAT_INTERVAL_MS = 25000;

export function useAlertsWebSocket() {
  const [status, setStatus] = useState<WSConnectionStatus>('DISCONNECTED');
  const [alerts, setAlerts] = useState<WSAlertPayload[]>([]);
  const [latestAlert, setLatestAlert] = useState<WSAlertPayload | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const heartbeatIntervalRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const seenAlertIdsRef = useRef<Set<string>>(new Set());
  const isManuallyClosedRef = useRef<boolean>(false);

  const clearAlerts = useCallback(() => {
    setAlerts([]);
    setLatestAlert(null);
  }, []);

  const connect = useCallback(() => {
    // Clean up any existing connection
    if (socketRef.current) {
      try {
        socketRef.current.close();
      } catch {
        // ignore
      }
      socketRef.current = null;
    }

    if (reconnectTimeoutRef.current) {
      window.clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    isManuallyClosedRef.current = false;
    setStatus('CONNECTING');

    const token = getAuthToken();
    const envWsUrl = (import.meta as any).env?.VITE_WS_URL;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const baseWs = envWsUrl || `${protocol}//${window.location.host}/ws/alerts`;
    const wsUrl = `${baseWs}${baseWs.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`;

    try {
      const ws = new WebSocket(wsUrl);
      socketRef.current = ws;

      ws.onopen = () => {
        setStatus('CONNECTED');
        reconnectAttemptsRef.current = 0;

        // Start heartbeat ping
        if (heartbeatIntervalRef.current) {
          window.clearInterval(heartbeatIntervalRef.current);
        }
        heartbeatIntervalRef.current = window.setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'PING' }));
          }
        }, HEARTBEAT_INTERVAL_MS);
      };

      ws.onmessage = (event) => {
        try {
          const frame = JSON.parse(event.data) as WSIncomingFrame;

          if (frame.type === 'CRITICAL_ALERT') {
            const incomingAlert = frame.alert;

            // Client-side duplicate suppression
            if (incomingAlert.alert_id && seenAlertIdsRef.current.has(incomingAlert.alert_id)) {
              return;
            }

            if (incomingAlert.alert_id) {
              seenAlertIdsRef.current.add(incomingAlert.alert_id);
              // Bound seen set to prevent memory growth
              if (seenAlertIdsRef.current.size > 200) {
                const firstKey = seenAlertIdsRef.current.keys().next().value;
                if (firstKey) seenAlertIdsRef.current.delete(firstKey);
              }
            }

            setLatestAlert(incomingAlert);
            setAlerts((prev) => [incomingAlert, ...prev].slice(0, MAX_ALERT_HISTORY));
          }
        } catch (parseErr) {
          console.warn('Failed to parse WebSocket frame:', parseErr);
        }
      };

      ws.onerror = (err) => {
        console.error('WebSocket encountered an error:', err);
        setStatus('ERROR');
      };

      ws.onclose = () => {
        if (heartbeatIntervalRef.current) {
          window.clearInterval(heartbeatIntervalRef.current);
          heartbeatIntervalRef.current = null;
        }

        if (!isManuallyClosedRef.current) {
          setStatus('RECONNECTING');
          const delay = Math.min(
            INITIAL_RECONNECT_DELAY_MS * Math.pow(1.5, reconnectAttemptsRef.current),
            MAX_RECONNECT_DELAY_MS
          );
          reconnectAttemptsRef.current += 1;

          reconnectTimeoutRef.current = window.setTimeout(() => {
            connect();
          }, delay);
        } else {
          setStatus('DISCONNECTED');
        }
      };
    } catch (e) {
      console.error('Failed to construct WebSocket client:', e);
      setStatus('ERROR');
    }
  }, []);

  const disconnect = useCallback(() => {
    isManuallyClosedRef.current = true;
    if (heartbeatIntervalRef.current) {
      window.clearInterval(heartbeatIntervalRef.current);
      heartbeatIntervalRef.current = null;
    }
    if (reconnectTimeoutRef.current) {
      window.clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (socketRef.current) {
      socketRef.current.close();
      socketRef.current = null;
    }
    setStatus('DISCONNECTED');
  }, []);

  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  const dismissAlert = useCallback(() => {
    setLatestAlert(null);
  }, []);

  return {
    status,
    isConnected: status === 'CONNECTED',
    alerts,
    latestAlert,
    latestCriticalAlert: latestAlert,
    clearAlerts,
    dismissAlert,
    reconnect: connect,
    disconnect,
  };
}
