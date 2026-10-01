-- ==============================================================================
-- FleetGuard Pulse - Migration 003: Deterministic Seed Data
-- ==============================================================================

-- 1. Tenants
INSERT INTO tenants (tenant_id, name) VALUES
('a0000000-0000-0000-0000-000000000001', 'Metro Transit Authority'),
('a0000000-0000-0000-0000-000000000002', 'Apex Logistics Corp')
ON CONFLICT (tenant_id) DO NOTHING;

-- 2. Roles
INSERT INTO roles (role_name, description) VALUES
('ADMIN', 'System and fleet administration with full operational control'),
('DISPATCHER', 'Fleet vehicle dispatch, active alert monitoring, and driver routing'),
('TECHNICIAN', 'Maintenance facility technician executing work orders and inspections')
ON CONFLICT (role_name) DO NOTHING;

-- 3. Users
INSERT INTO users (user_id, tenant_id, email, full_name, password_hash, is_active) VALUES
('b0000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', 'admin@metrotransit.com', 'Elena Rostova', '$2b$12$e8Y5T.placeholder_hash_for_dev_admin', TRUE),
('b0000000-0000-0000-0000-000000000002', 'a0000000-0000-0000-0000-000000000001', 'dispatch@metrotransit.com', 'Marcus Chen', '$2b$12$e8Y5T.placeholder_hash_for_dev_dispatch', TRUE),
('b0000000-0000-0000-0000-000000000003', 'a0000000-0000-0000-0000-000000000001', 'tech.john@metrotransit.com', 'John Miller', '$2b$12$e8Y5T.placeholder_hash_for_dev_tech1', TRUE),
('b0000000-0000-0000-0000-000000000004', 'a0000000-0000-0000-0000-000000000001', 'tech.sarah@metrotransit.com', 'Sarah Connor', '$2b$12$e8Y5T.placeholder_hash_for_dev_tech2', TRUE)
ON CONFLICT (user_id) DO NOTHING;

-- 4. User Roles
INSERT INTO user_roles (user_id, role_id)
SELECT 'b0000000-0000-0000-0000-000000000001'::uuid, role_id FROM roles WHERE role_name = 'ADMIN'
ON CONFLICT DO NOTHING;

INSERT INTO user_roles (user_id, role_id)
SELECT 'b0000000-0000-0000-0000-000000000002'::uuid, role_id FROM roles WHERE role_name = 'DISPATCHER'
ON CONFLICT DO NOTHING;

INSERT INTO user_roles (user_id, role_id)
SELECT 'b0000000-0000-0000-0000-000000000003'::uuid, role_id FROM roles WHERE role_name = 'TECHNICIAN'
ON CONFLICT DO NOTHING;

INSERT INTO user_roles (user_id, role_id)
SELECT 'b0000000-0000-0000-0000-000000000004'::uuid, role_id FROM roles WHERE role_name = 'TECHNICIAN'
ON CONFLICT DO NOTHING;

-- 5. Depots
INSERT INTO depots (depot_id, tenant_id, name, code, address, city, state, postal_code, latitude, longitude) VALUES
('c0000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', 'Central Operations Hub', 'DEPOT-CENTRAL', '100 Industrial Parkway', 'Chicago', 'IL', '60607', 41.878113, -87.629799),
('c0000000-0000-0000-0000-000000000002', 'a0000000-0000-0000-0000-000000000001', 'North Maintenance Facility', 'DEPOT-NORTH', '450 Northway Blvd', 'Evanston', 'IL', '60201', 42.045072, -87.687697)
ON CONFLICT (depot_id) DO NOTHING;

-- 6. Fleets
INSERT INTO fleets (fleet_id, tenant_id, name, code, description) VALUES
('d0000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', 'Express Regional Delivery', 'FLEET-EXPRESS', 'Regional haul and short-distance freight routes'),
('d0000000-0000-0000-0000-000000000002', 'a0000000-0000-0000-0000-000000000001', 'Urban Clean Transit', 'FLEET-URBAN', 'Urban public transit and municipal hybrid/EV shuttle routes')
ON CONFLICT (fleet_id) DO NOTHING;

-- 7. Vehicle Models
INSERT INTO vehicle_models (make, model_name, year, vehicle_type, engine_displacement_l, battery_capacity_kwh, curb_weight_kg) VALUES
('Freightliner', 'Cascadia Heavy', 2023, 'ICE', 12.8, NULL, 8200),
('Volvo', 'VNL 760 Long Haul', 2022, 'ICE', 13.0, NULL, 8350),
('Toyota', 'Sienna Hybrid Commercial', 2024, 'HEV', 2.5, 1.9, 2150),
('Ford', 'F-150 PowerBoost Hybrid', 2023, 'HEV', 3.5, 1.5, 2500),
('Tesla', 'Semi Long Range', 2024, 'BEV', NULL, 850.0, 11500),
('Ford', 'E-Transit Cargo 350', 2023, 'BEV', NULL, 68.0, 2400)
ON CONFLICT (make, model_name, year, vehicle_type) DO NOTHING;

-- 8. Representative Vehicles
INSERT INTO vehicles (vehicle_id, vin, tenant_id, fleet_id, depot_id, model_id, license_plate, manufacture_year, status, initial_odometer_km) VALUES
('e0000000-0000-0000-0000-000000000001', '1HGCR2F83HA000001', 'a0000000-0000-0000-0000-000000000001', 'd0000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000001', 1, 'IL-TRK-101', 2023, 'ACTIVE', 45000.0),
('e0000000-0000-0000-0000-000000000002', '1HGCR2F83HA000002', 'a0000000-0000-0000-0000-000000000001', 'd0000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000001', 1, 'IL-TRK-102', 2023, 'MAINTENANCE', 68200.0),
('e0000000-0000-0000-0000-000000000003', '1HGCR2F83HA000003', 'a0000000-0000-0000-0000-000000000001', 'd0000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000002', 2, 'IL-TRK-201', 2022, 'ACTIVE', 120500.0),
('e0000000-0000-0000-0000-000000000004', '3VW2B7AJ5HM000001', 'a0000000-0000-0000-0000-000000000001', 'd0000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000001', 3, 'IL-HYB-301', 2024, 'ACTIVE', 18400.0),
('e0000000-0000-0000-0000-000000000005', '3VW2B7AJ5HM000002', 'a0000000-0000-0000-0000-000000000001', 'd0000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000002', 4, 'IL-HYB-302', 2023, 'ACTIVE', 34100.0),
('e0000000-0000-0000-0000-000000000006', '5YJSA1E28HF000001', 'a0000000-0000-0000-0000-000000000001', 'd0000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000001', 5, 'IL-EV-501', 2024, 'ACTIVE', 22100.0),
('e0000000-0000-0000-0000-000000000007', '5YJSA1E28HF000002', 'a0000000-0000-0000-0000-000000000001', 'd0000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000002', 6, 'IL-EV-502', 2023, 'MAINTENANCE', 41800.0)
ON CONFLICT (vin) DO NOTHING;

-- 9. Maintenance Types
INSERT INTO maintenance_types (code, name, description, recommended_interval_km, recommended_interval_days, target_vehicle_type, estimated_duration_hours) VALUES
('PM-OIL-CHANGE', 'Engine Lubrication & Filter Replacement', 'Full synthetic oil drain and filter element replacement with torque checks', 15000, 90, 'ICE', 1.5),
('PM-HYBRID-SERVICE', 'Hybrid Powertrain & Inverter Service', 'Dual-circuit cooling system check, inverter fluid check, and hybrid battery fan inspection', 25000, 180, 'HEV', 2.5),
('PM-EV-BATTERY-CHECK', 'HV Battery Pack & Thermal Loop Diagnostic', 'High-voltage isolation test, cell balance verification, and glycol loop pressure test', 30000, 180, 'BEV', 3.0),
('PM-BRAKE-SERVICE', 'Pneumatic / Hydraulic Brake System Overhaul', 'Friction lining inspection, rotor micrometer check, and brake fluid moisture analysis', 40000, 365, 'ALL', 4.0),
('EM-OVERHEAT-REPAIR', 'Cooling System Emergency Overhaul', 'Radiator core replacement, thermostat renewal, and head gasket integrity test', NULL, NULL, 'ICE', 6.0),
('EM-THERMAL-RUNAWAY', 'High-Voltage Battery Module Isolation', 'Emergency battery module quarantine, contactor replacement, and cell delta troubleshooting', NULL, NULL, 'BEV', 8.0)
ON CONFLICT (code) DO NOTHING;

-- 10. Work Orders
INSERT INTO work_orders (work_order_id, tenant_id, vehicle_id, type_id, priority, status, assigned_technician_id, scheduled_at)
VALUES
('f0000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000002', 5, 'CRITICAL', 'IN_PROGRESS', 'b0000000-0000-0000-0000-000000000003', NOW()),
('f0000000-0000-0000-0000-000000000002', 'a0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000007', 6, 'HIGH', 'SCHEDULED', 'b0000000-0000-0000-0000-000000000004', NOW() + INTERVAL '1 day')
ON CONFLICT (work_order_id) DO NOTHING;

-- 11. Maintenance Records
INSERT INTO maintenance_records (record_id, tenant_id, vehicle_id, type_id, performed_at, odometer_km, technician_notes, cost_parts, cost_labor, performed_by_user_id)
VALUES
('80000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000001', 1, NOW() - INTERVAL '30 days', 30000.0, 'Routine oil and filter completed. No metal shavings detected in filter element.', 145.50, 180.00, 'b0000000-0000-0000-0000-000000000003'),
('80000000-0000-0000-0000-000000000002', 'a0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000006', 3, NOW() - INTERVAL '15 days', 18000.0, 'HV battery pack thermal scan nominal. Max cell delta 1.1C.', 85.00, 240.00, 'b0000000-0000-0000-0000-000000000004')
ON CONFLICT (record_id) DO NOTHING;

-- 12. Alerts
INSERT INTO alerts (alert_id, tenant_id, vehicle_id, telemetry_event_id, severity, fault_type, message, sequence_number, is_acknowledged, resolution_work_order_id)
VALUES
('90000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000002', gen_random_uuid(), 'CRITICAL', 'ENGINE_OVERHEAT', 'Coolant temperature reached 118.5C exceeding critical threshold 115C', 1045, FALSE, 'f0000000-0000-0000-0000-000000000001'),
('90000000-0000-0000-0000-000000000002', 'a0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000007', gen_random_uuid(), 'WARNING', 'BATTERY_CELL_IMBALANCE', 'HV cell temperature delta reached 5.8C indicating potential thermal degradation', 2150, FALSE, 'f0000000-0000-0000-0000-000000000002')
ON CONFLICT (alert_id) DO NOTHING;

-- 13. Audit Logs
INSERT INTO audit_logs (audit_id, tenant_id, actor_user_id, action, entity_type, entity_id, details)
VALUES
('70000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', 'TENANT_INITIALIZATION', 'TENANT', 'a0000000-0000-0000-0000-000000000001', '{"source": "seed_migration", "status": "COMPLETED"}'),
('70000000-0000-0000-0000-000000000002', 'a0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000002', 'WORK_ORDER_DISPATCH', 'WORK_ORDER', 'f0000000-0000-0000-0000-000000000001', '{"priority": "CRITICAL", "assigned_to": "b0000000-0000-0000-0000-000000000003"}')
ON CONFLICT (audit_id) DO NOTHING;

-- 14. Diagnostic Signatures (pgvector)
-- 16-Dimensional normalized telemetry embeddings:
-- [vib_g, vib_z, vib_ewma, coolant_norm, coolant_z, oil_norm, oil_z, rpm_norm, pack_v_norm, soc_norm, cell_d_norm, cell_d_z, speed_norm, v12_norm, dtc_sev, type_flag]
INSERT INTO diagnostic_signatures (signature_id, fault_type, vehicle_type, description, embedding) VALUES
-- 1. Engine Overheat (ICE)
('60000000-0000-0000-0000-000000000001', 'ENGINE_OVERHEAT', 'ICE', 'Severe cooling loss: coolant > 118C with elevated vibration and low pressure ratio',
 '[0.65, 2.10, 0.60, 0.85, 3.80, 0.50, -1.20, 0.45, 0.00, 0.00, 0.00, 0.00, 0.55, 0.88, 1.00, 0.00]'),

-- 2. Oil Pressure Critical Loss (ICE)
('60000000-0000-0000-0000-000000000002', 'OIL_PRESSURE_CRITICAL_LOW', 'ICE', 'Catastrophic oil pump/line failure: pressure < 70 kPa with elevated engine RPM',
 '[0.70, 2.40, 0.68, 0.65, 1.20, 0.14, -3.90, 0.50, 0.00, 0.00, 0.00, 0.00, 0.50, 0.87, 1.00, 0.00]'),

-- 3. Traction Battery Thermal Runaway Risk (BEV)
('60000000-0000-0000-0000-000000000003', 'BATTERY_THERMAL_RUNAWAY_RISK', 'BEV', 'Severe cell imbalance: cell delta > 9.0C under high motor load',
 '[0.30, 0.50, 0.28, 0.00, 0.00, 0.00, 0.00, 0.00, 0.80, 0.45, 0.48, 4.10, 0.60, 0.89, 1.00, 1.00]'),

-- 4. Battery Cell Degradation / Imbalance (HEV)
('60000000-0000-0000-0000-000000000004', 'BATTERY_CELL_IMBALANCE', 'HEV', 'Moderate cell imbalance: cell delta > 5.5C with fluctuating SOC in hybrid cycle',
 '[0.40, 1.10, 0.38, 0.60, 0.80, 0.55, 0.10, 0.35, 0.65, 0.52, 0.28, 2.80, 0.45, 0.88, 0.50, 0.50]'),

-- 5. Excessive Driveline Vibration (ALL)
('60000000-0000-0000-0000-000000000005', 'EXCESSIVE_VIBRATION', 'ICE', 'Severe mechanical vibration: > 4.5G caused by driveshaft bearing or universal joint wear',
 '[0.92, 4.20, 0.88, 0.60, 0.20, 0.60, 0.00, 0.48, 0.00, 0.00, 0.00, 0.00, 0.65, 0.88, 1.00, 0.00]'),

-- 6. Electric Motor Inverter Performance Anomaly (BEV)
('60000000-0000-0000-0000-000000000006', 'INVERTER_DEGRADATION', 'BEV', 'Inverter switching distortion: sudden voltage fluctuations and moderate thermal delta',
 '[0.45, 1.80, 0.42, 0.00, 0.00, 0.00, 0.00, 0.00, 0.72, 0.60, 0.22, 2.10, 0.55, 0.84, 1.00, 1.00]')
ON CONFLICT (signature_id) DO NOTHING;
