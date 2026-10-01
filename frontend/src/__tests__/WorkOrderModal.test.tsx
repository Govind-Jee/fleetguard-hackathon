import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { WorkOrderModal } from '../components/maintenance/WorkOrderModal';
import { api } from '../services/api';

vi.mock('../services/api', () => ({
  api: {
    createWorkOrder: vi.fn(),
  },
}));

describe('WorkOrderModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('does not render when isOpen is false', () => {
    const { container } = render(
      <WorkOrderModal isOpen={false} onClose={vi.fn()} vin="1HGCR2F83HA000001" />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders form inputs when isOpen is true', () => {
    render(
      <WorkOrderModal isOpen={true} onClose={vi.fn()} vin="1HGCR2F83HA000001" />
    );

    expect(screen.getByText('Dispatch Maintenance Work Order')).toBeInTheDocument();
    expect(screen.getByText('VIN: 1HGCR2F83HA000001')).toBeInTheDocument();
    expect(screen.getByLabelText(/Maintenance Service Type/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Priority/i)).toBeInTheDocument();
  });

  it('submits work order and shows success state', async () => {
    const mockCreated = {
      work_order_id: 'wo-12345-uuid',
      tenant_id: 'ten-metro',
      vehicle_id: 'veh-01',
      vin: '1HGCR2F83HA000001',
      type_id: 1,
      priority: 'CRITICAL',
      status: 'PENDING',
      created_at: '2026-03-31T12:00:00Z',
      updated_at: '2026-03-31T12:00:00Z',
    };

    (api.createWorkOrder as any).mockResolvedValueOnce(mockCreated);
    const handleSuccess = vi.fn();

    render(
      <WorkOrderModal
        isOpen={true}
        onClose={vi.fn()}
        vin="1HGCR2F83HA000001"
        initialPriority="CRITICAL"
        onSuccess={handleSuccess}
      />
    );

    const submitBtn = screen.getByText('Create Work Order');
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(api.createWorkOrder).toHaveBeenCalledWith(
        expect.objectContaining({
          vin: '1HGCR2F83HA000001',
          priority: 'CRITICAL',
          type_id: 1,
        })
      );
    });

    await waitFor(() => {
      expect(screen.getByText('Work Order Successfully Dispatched')).toBeInTheDocument();
      expect(screen.getByText('wo-12345-uuid')).toBeInTheDocument();
      expect(handleSuccess).toHaveBeenCalledWith(mockCreated);
    });
  });
});
