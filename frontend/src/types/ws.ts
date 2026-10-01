/**
 * FleetGuard Pulse — WebSocket Protocol Types (/ws/alerts).
 */

import { AlertSeverity } from './api';

export type WSConnectionStatus = 'CONNECTING' | 'CONNECTED' | 'DISCONNECTED' | 'RECONNECTING' | 'ERROR';

export interface WSAlertPayload {
  alert_id: string;
  vin: string;
  tenant_id: string;
  severity: AlertSeverity;
  fault_type: string;
  message: string;
  sequence_number?: number;
  telemetry_event_id?: string;
  timestamp?: string;
  created_at?: string;
}

export type WSIncomingFrame =
  | {
      type: 'CONNECTION_ESTABLISHED';
      tenant_id: string;
      timestamp: string;
    }
  | {
      type: 'CRITICAL_ALERT';
      alert: WSAlertPayload;
    }
  | {
      type: 'PONG';
    };

export type WSOutgoingFrame =
  | {
      type: 'PING';
    };
