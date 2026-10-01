/**
 * FleetGuard Pulse — Enterprise API TypeScript Definitions.
 * Strictly aligned with FastAPI schemas from services/api/schemas/.
 */

export type VehicleStatus = 'ACTIVE' | 'MAINTENANCE' | 'INACTIVE' | 'DECOMMISSIONED';
export type VehicleType = 'ICE' | 'HEV' | 'BEV';
export type HealthStatus = 'NOMINAL' | 'WARNING' | 'CRITICAL';
export type AlertSeverity = 'INFO' | 'WARNING' | 'CRITICAL';
export type WorkOrderPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type WorkOrderStatus = 'PENDING' | 'SCHEDULED' | 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED';

export interface VehicleModel {
  model_id: number;
  make: string;
  model_name: string;
  year: number;
  vehicle_type: VehicleType;
  engine_displacement_l?: number | null;
  battery_capacity_kwh?: number | null;
  curb_weight_kg?: number | null;
}

export interface VehicleListItem {
  vehicle_id: string;
  vin: string;
  license_plate: string;
  status: VehicleStatus;
  manufacture_year: number;
  fleet_id: string;
  fleet_name: string;
  fleet_code: string;
  depot_id: string;
  depot_name: string;
  depot_code: string;
  model: VehicleModel;
}

export interface PaginationMetadata {
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface VehicleListResponse {
  items: VehicleListItem[];
  pagination: PaginationMetadata;
}

export interface TransientVehicleState {
  vin: string;
  speed_kmh?: number | null;
  odometer_km?: number | null;
  vibration?: number | null;
  health_status?: HealthStatus | null;
  latitude?: number | null;
  longitude?: number | null;
  sequence_number?: number | null;
  timestamp?: string | null;
  dtc_codes?: string[];
  coolant_temp_c?: number | null;
  oil_pressure_kpa?: number | null;
  engine_rpm?: number | null;
  battery_voltage_v?: number | null;
  soc_pct?: number | null;
  pack_voltage_v?: number | null;
  cell_temp_delta_c?: number | null;
}

export interface AuthoritativeVehicleMetadata {
  vehicle_id: string;
  vin: string;
  license_plate: string;
  status: VehicleStatus;
  manufacture_year: number;
  initial_odometer_km: number;
  created_at: string;
  fleet: {
    fleet_id: string;
    name: string;
    code: string;
    description?: string;
  };
  depot: {
    depot_id: string;
    name: string;
    code: string;
    city: string;
    state: string;
    latitude?: number;
    longitude?: number;
  };
  model: VehicleModel;
}

export interface VehicleDetailResponse {
  vin: string;
  authoritative: AuthoritativeVehicleMetadata;
  transient_state?: TransientVehicleState | null;
}

export interface RiskFactorExplanation {
  feature_name: string;
  feature_value?: number | null;
  standardized_value: number;
  coefficient: number;
  contribution: number;
  direction: 'INCREASES_RISK' | 'REDUCES_RISK';
}

export interface VehicleRiskResponse {
  vin: string;
  probability_7d: number;
  predicted_maintenance_required: boolean;
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  decision_threshold: number;
  top_risk_factors: RiskFactorExplanation[];
  protective_factors: RiskFactorExplanation[];
  model_version: string;
  prediction_timestamp: string;
  disclaimer: string;
}

export interface AlertRecord {
  alert_id: string;
  vin: string;
  vehicle_id?: string;
  severity: AlertSeverity;
  fault_type: string;
  message: string;
  sequence_number?: number;
  is_acknowledged: boolean;
  created_at: string;
  telemetry_event_id?: string;
}

export interface AlertListResponse {
  items: AlertRecord[];
  pagination: PaginationMetadata;
}

export interface FleetHealthResponse {
  fleet_id: string;
  fleet_name: string;
  fleet_code: string;
  total_vehicles: number;
  vehicles_by_status: Record<string, number>;
  vehicles_by_type: Record<string, number>;
  health_status_counts: Record<string, number>;
  critical_alert_count: number;
  high_risk_vehicle_count: number;
  work_orders_summary: Record<string, number>;
}

export interface DiagnosticSignatureMatch {
  signature_id: string;
  fault_type: string;
  vehicle_type: string;
  description: string;
  cosine_distance: number;
  similarity_score: number;
  feature_schema_version: string;
}

export interface DiagnosticSimilarityResponse {
  query_vector_dimension: number;
  matches: DiagnosticSignatureMatch[];
  methodology: string;
}

export interface CreateWorkOrderPayload {
  vin: string;
  type_id: number;
  priority: WorkOrderPriority;
  scheduled_at?: string;
  assigned_technician_id?: string;
  notes?: string;
}

export interface WorkOrderResponse {
  work_order_id: string;
  tenant_id: string;
  vehicle_id: string;
  vin: string;
  type_id: number;
  priority: WorkOrderPriority;
  status: WorkOrderStatus;
  assigned_technician_id?: string;
  scheduled_at?: string;
  created_at: string;
  updated_at: string;
}

export interface FleetItem {
  fleet_id: string;
  name: string;
  code: string;
  description?: string;
  vehicle_count?: number;
}
