import { describe, it, expect } from 'vitest';
import { WSAlertPayload } from '../types/ws';

describe('Alerts Stream Deduplication and Bounded Buffer Logic', () => {
  it('deduplicates alerts by alert_id using sliding set', () => {
    const seenAlertIds = new Set<string>();
    const alertBuffer: WSAlertPayload[] = [];
    const MAX_BUFFER = 50;

    const processIncomingAlert = (alert: WSAlertPayload) => {
      if (seenAlertIds.has(alert.alert_id)) {
        return false; // Deduplicated
      }
      seenAlertIds.add(alert.alert_id);
      alertBuffer.unshift(alert);
      if (alertBuffer.length > MAX_BUFFER) {
        alertBuffer.pop();
      }
      return true;
    };

    const alert1: WSAlertPayload = {
      alert_id: 'alert-001',
      vin: '1HGCR2F83HA000001',
      tenant_id: 'ten-metro',
      severity: 'CRITICAL',
      fault_type: 'ENGINE_OVERHEAT',
      message: 'Coolant temperature threshold exceeded',
    };

    // First arrival accepted
    expect(processIncomingAlert(alert1)).toBe(true);
    expect(alertBuffer).toHaveLength(1);

    // Duplicate arrival discarded
    expect(processIncomingAlert(alert1)).toBe(false);
    expect(alertBuffer).toHaveLength(1);

    // New alert accepted
    const alert2: WSAlertPayload = {
      alert_id: 'alert-002',
      vin: '1HGCR2F83HA000002',
      tenant_id: 'ten-metro',
      severity: 'CRITICAL',
      fault_type: 'BRAKE_PRESSURE_LOSS',
      message: 'Hydraulic line pressure low',
    };
    expect(processIncomingAlert(alert2)).toBe(true);
    expect(alertBuffer).toHaveLength(2);
    expect(alertBuffer[0].alert_id).toBe('alert-002');
  });

  it('bounds maximum alert history size to 50 items', () => {
    const seenAlertIds = new Set<string>();
    const alertBuffer: WSAlertPayload[] = [];
    const MAX_BUFFER = 50;

    for (let i = 0; i < 75; i++) {
      const alert: WSAlertPayload = {
        alert_id: `alert-${i}`,
        vin: `VIN-${i}`,
        tenant_id: 'ten-metro',
        severity: 'CRITICAL',
        fault_type: 'ANOMALY',
        message: `Alert message ${i}`,
      };
      if (!seenAlertIds.has(alert.alert_id)) {
        seenAlertIds.add(alert.alert_id);
        alertBuffer.unshift(alert);
        if (alertBuffer.length > MAX_BUFFER) {
          alertBuffer.pop();
        }
      }
    }

    expect(alertBuffer).toHaveLength(50);
    // Newest is alert-74
    expect(alertBuffer[0].alert_id).toBe('alert-74');
    // Oldest retained is alert-25
    expect(alertBuffer[49].alert_id).toBe('alert-25');
  });
});
