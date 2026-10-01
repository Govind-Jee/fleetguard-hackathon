-- ==============================================================================
-- FleetGuard Pulse - Migration 001: 3NF Relational Fleet Domain Schema
-- ==============================================================================

-- 1. Tenants (Root multi-tenant isolation boundary)
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Roles (Controlled RBAC roles: ADMIN, DISPATCHER, TECHNICIAN)
CREATE TABLE IF NOT EXISTS roles (
    role_id SMALLINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    role_name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Users (Tenant-scoped operational users)
CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL UNIQUE,
    full_name VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL, -- Development-only local credential field; production authentication uses OIDC/Keycloak and application does not store user passwords
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. User Roles (3NF normalized M:N user-to-role mapping)
CREATE TABLE IF NOT EXISTS user_roles (
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role_id SMALLINT NOT NULL REFERENCES roles(role_id) ON DELETE RESTRICT,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);

-- 5. Depots (Physical operations and maintenance centers belonging to a tenant)
CREATE TABLE IF NOT EXISTS depots (
    depot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL,
    address VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(100),
    postal_code VARCHAR(20),
    latitude NUMERIC(9, 6),
    longitude NUMERIC(9, 6),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_depots_tenant_code UNIQUE (tenant_id, code)
);

-- 6. Fleets (Organizational grouping of vehicles belonging to a tenant)
CREATE TABLE IF NOT EXISTS fleets (
    fleet_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fleets_tenant_code UNIQUE (tenant_id, code)
);

-- 7. Vehicle Models (3NF catalog of manufacturer specifications; NOT duplicated in vehicles)
CREATE TABLE IF NOT EXISTS vehicle_models (
    model_id INT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    make VARCHAR(100) NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    year SMALLINT NOT NULL,
    vehicle_type VARCHAR(10) NOT NULL CHECK (vehicle_type IN ('ICE', 'HEV', 'BEV')),
    engine_displacement_l NUMERIC(4, 2),
    battery_capacity_kwh NUMERIC(6, 2),
    curb_weight_kg INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_vehicle_models UNIQUE (make, model_name, year, vehicle_type)
);

-- 8. Vehicles (Concrete physical assets referencing fleet, depot, and model in 3NF)
CREATE TABLE IF NOT EXISTS vehicles (
    vehicle_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vin VARCHAR(17) NOT NULL UNIQUE,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    fleet_id UUID NOT NULL REFERENCES fleets(fleet_id) ON DELETE RESTRICT,
    depot_id UUID NOT NULL REFERENCES depots(depot_id) ON DELETE RESTRICT,
    model_id INT NOT NULL REFERENCES vehicle_models(model_id) ON DELETE RESTRICT,
    license_plate VARCHAR(30),
    manufacture_year SMALLINT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'MAINTENANCE', 'DECOMMISSIONED', 'INACTIVE')),
    initial_odometer_km NUMERIC(10, 2) NOT NULL DEFAULT 0.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 9. Maintenance Types (Standard catalog of maintenance operations)
CREATE TABLE IF NOT EXISTS maintenance_types (
    type_id INT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    recommended_interval_km INT,
    recommended_interval_days INT,
    target_vehicle_type VARCHAR(10) NOT NULL DEFAULT 'ALL' CHECK (target_vehicle_type IN ('ALL', 'ICE', 'HEV', 'BEV')),
    estimated_duration_hours NUMERIC(4, 2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 10. Maintenance Records (Historical audit log of executed maintenance operations)
CREATE TABLE IF NOT EXISTS maintenance_records (
    record_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    vehicle_id UUID NOT NULL REFERENCES vehicles(vehicle_id) ON DELETE CASCADE,
    type_id INT NOT NULL REFERENCES maintenance_types(type_id) ON DELETE RESTRICT,
    performed_at TIMESTAMPTZ NOT NULL,
    odometer_km NUMERIC(10, 2) NOT NULL,
    technician_notes TEXT,
    cost_parts NUMERIC(10, 2) DEFAULT 0.0,
    cost_labor NUMERIC(10, 2) DEFAULT 0.0,
    performed_by_user_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 11. Work Orders (Actionable scheduling and dispatch tasks for technicians)
CREATE TABLE IF NOT EXISTS work_orders (
    work_order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    vehicle_id UUID NOT NULL REFERENCES vehicles(vehicle_id) ON DELETE CASCADE,
    type_id INT NOT NULL REFERENCES maintenance_types(type_id) ON DELETE RESTRICT,
    priority VARCHAR(20) NOT NULL CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')),
    assigned_technician_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    scheduled_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cancellation_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 12. Alerts (Authoritative durable maintenance and vehicle health alerts)
CREATE TABLE IF NOT EXISTS alerts (
    alert_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    vehicle_id UUID NOT NULL REFERENCES vehicles(vehicle_id) ON DELETE CASCADE,
    telemetry_event_id UUID NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('WARNING', 'CRITICAL')),
    fault_type VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    sequence_number BIGINT NOT NULL,
    is_acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by_user_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    resolution_work_order_id UUID REFERENCES work_orders(work_order_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 13. Audit Logs (System compliance and actor audit trail)
CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    actor_user_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    entity_id VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    details JSONB
);

-- Baseline B-Tree Indexes for Foreign Keys & Core Queries
CREATE INDEX IF NOT EXISTS idx_vehicles_tenant_id ON vehicles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_vehicles_fleet_id ON vehicles(fleet_id);
CREATE INDEX IF NOT EXISTS idx_vehicles_depot_id ON vehicles(depot_id);
CREATE INDEX IF NOT EXISTS idx_vehicles_model_id ON vehicles(model_id);
CREATE INDEX IF NOT EXISTS idx_vehicles_status ON vehicles(status);

CREATE INDEX IF NOT EXISTS idx_maintenance_records_vehicle_performed ON maintenance_records(vehicle_id, performed_at);
CREATE INDEX IF NOT EXISTS idx_work_orders_vehicle_status ON work_orders(vehicle_id, status);
CREATE INDEX IF NOT EXISTS idx_work_orders_tenant_status ON work_orders(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_work_orders_composite_dispatch ON work_orders(tenant_id, status, priority, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_alerts_tenant_created ON alerts(tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_alerts_vehicle_unack ON alerts(vehicle_id, is_acknowledged);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_timestamp ON audit_logs(tenant_id, timestamp);

