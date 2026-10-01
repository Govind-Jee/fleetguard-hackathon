/**
 * FleetGuard Pulse — Enterprise Typed API Client.
 * Connects to FastAPI endpoints in services/api/ with centralized auth headers,
 * JSON error handling, and type safety.
 */

import {
  AlertListResponse,
  CreateWorkOrderPayload,
  DiagnosticSimilarityResponse,
  FleetHealthResponse,
  FleetItem,
  VehicleDetailResponse,
  VehicleListResponse,
  VehicleRiskResponse,
  WorkOrderResponse,
} from '../types/api';
import { getAuthToken } from './auth';

// Environment-driven API Base URL (defaults to /api which Vite proxies in dev)
const API_BASE = (import.meta as any).env?.VITE_API_BASE_URL || '/api';

export class ApiError extends Error {
  code: string;
  statusCode: number;
  details?: Record<string, any>;

  constructor(message: string, code: string = 'UNKNOWN_ERROR', statusCode: number = 500, details?: Record<string, any>) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.statusCode = statusCode;
    this.details = details;
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = getAuthToken();
  const headers = new Headers(options.headers || {});
  headers.set('Accept', 'application/json');

  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  if (options.body && typeof options.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const url = `${API_BASE}${endpoint}`;

  let res: Response;
  try {
    res = await fetch(url, { ...options, headers });
  } catch (err: any) {
    throw new ApiError(`Network connection error: ${err.message || 'Server unreachable'}`, 'NETWORK_ERROR', 0);
  }

  if (!res.ok) {
    let errorCode = 'HTTP_ERROR';
    let errorMessage = `HTTP ${res.status}: ${res.statusText}`;
    let details: Record<string, any> | undefined;

    try {
      const errorJson = await res.json();
      if (errorJson.error) {
        errorCode = errorJson.error.code || errorCode;
        errorMessage = errorJson.error.message || errorMessage;
        details = errorJson.error.details;
      } else if (errorJson.detail) {
        errorMessage = typeof errorJson.detail === 'string' ? errorJson.detail : JSON.stringify(errorJson.detail);
      }
    } catch {
      // Body not JSON
    }

    throw new ApiError(errorMessage, errorCode, res.status, details);
  }

  return (await res.json()) as T;
}

export const api = {
  // Liveness / readiness
  async checkHealth(): Promise<{ status: string; environment?: string }> {
    return request<{ status: string }>('/health');
  },

  // Vehicles
  async getVehicles(params: {
    limit?: number;
    offset?: number;
    fleet_id?: string;
    vehicle_type?: string;
    status?: string;
  } = {}): Promise<VehicleListResponse> {
    const q = new URLSearchParams();
    if (params.limit !== undefined) q.set('limit', String(params.limit));
    if (params.offset !== undefined) q.set('offset', String(params.offset));
    if (params.fleet_id) q.set('fleet_id', params.fleet_id);
    if (params.vehicle_type) q.set('vehicle_type', params.vehicle_type);
    if (params.status) q.set('status', params.status);

    const queryStr = q.toString() ? `?${q.toString()}` : '';
    return request<VehicleListResponse>(`/vehicles${queryStr}`);
  },

  async getVehicleDetail(vin: string): Promise<VehicleDetailResponse> {
    return request<VehicleDetailResponse>(`/vehicles/${encodeURIComponent(vin)}`);
  },

  async getVehicleRisk(vin: string): Promise<VehicleRiskResponse> {
    return request<VehicleRiskResponse>(`/vehicles/${encodeURIComponent(vin)}/risk`);
  },

  // Fleets
  async getFleets(): Promise<{ items: FleetItem[] }> {
    return request<{ items: FleetItem[] }>('/fleets');
  },

  async getFleetHealth(fleetId: string): Promise<FleetHealthResponse> {
    return request<FleetHealthResponse>(`/fleets/${encodeURIComponent(fleetId)}/health`);
  },

  // Alerts
  async getAlerts(params: {
    limit?: number;
    offset?: number;
    severity?: string;
    vin?: string;
  } = {}): Promise<AlertListResponse> {
    const q = new URLSearchParams();
    if (params.limit !== undefined) q.set('limit', String(params.limit));
    if (params.offset !== undefined) q.set('offset', String(params.offset));
    if (params.severity) q.set('severity', params.severity);
    if (params.vin) q.set('vin', params.vin);

    const queryStr = q.toString() ? `?${q.toString()}` : '';
    return request<AlertListResponse>(`/alerts${queryStr}`);
  },

  // Diagnostic pgvector Search
  async getSimilarDiagnostics(params: {
    vector: string;
    limit?: number;
    vehicle_type?: string;
  }): Promise<DiagnosticSimilarityResponse> {
    const q = new URLSearchParams();
    q.set('vector', params.vector);
    if (params.limit) q.set('limit', String(params.limit));
    if (params.vehicle_type) q.set('vehicle_type', params.vehicle_type);

    return request<DiagnosticSimilarityResponse>(`/diagnostics/similar?${q.toString()}`);
  },

  // Maintenance Work Orders
  async createWorkOrder(payload: CreateWorkOrderPayload): Promise<WorkOrderResponse> {
    return request<WorkOrderResponse>('/maintenance/work-orders', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  // Analytics
  async getAnalyticsSummary(): Promise<any> {
    return request<any>('/analytics/summary');
  },
};
