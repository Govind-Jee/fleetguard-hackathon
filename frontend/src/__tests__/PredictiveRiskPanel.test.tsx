import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { PredictiveRiskPanel } from '../components/vehicles/PredictiveRiskPanel';
import { VehicleRiskResponse } from '../types/api';

const mockRiskData: VehicleRiskResponse = {
  vin: '1HGCR2F83HA000001',
  probability_7d: 0.384,
  predicted_maintenance_required: true,
  risk_level: 'HIGH',
  decision_threshold: 0.35,
  top_risk_factors: [
    {
      feature_name: 'coolant_temp_c',
      feature_value: 104.2,
      standardized_value: 2.15,
      coefficient: 0.85,
      contribution: 1.827,
      direction: 'INCREASES_RISK',
    },
    {
      feature_name: 'vibration_std',
      feature_value: 0.14,
      standardized_value: 1.65,
      coefficient: 0.62,
      contribution: 1.023,
      direction: 'INCREASES_RISK',
    },
  ],
  protective_factors: [
    {
      feature_name: 'oil_pressure_kpa',
      feature_value: 320.0,
      standardized_value: -0.45,
      coefficient: -0.55,
      contribution: -0.247,
      direction: 'REDUCES_RISK',
    },
  ],
  model_version: 'logreg-v1-purged',
  prediction_timestamp: '2026-03-31T12:00:00Z',
  disclaimer:
    'Estimated 7-day maintenance risk probability based on historical telemetry patterns. This prediction is probabilistic and does not constitute a guaranteed mechanical failure.',
};

describe('PredictiveRiskPanel', () => {
  it('renders probability percentage and decision threshold prominently', () => {
    render(<PredictiveRiskPanel riskData={mockRiskData} isLoading={false} />);

    // Probability 0.384 -> 38.4%
    expect(screen.getByText('38.4%')).toBeInTheDocument();
    // Decision threshold 0.35 -> 35%
    expect(screen.getByText('(Decision Threshold: 35%)')).toBeInTheDocument();
    // Model version
    expect(screen.getByText('logreg-v1-purged')).toBeInTheDocument();
  });

  it('displays the mandatory probabilistic disclaimer', () => {
    render(<PredictiveRiskPanel riskData={mockRiskData} isLoading={false} />);

    expect(
      screen.getByText(/This prediction is probabilistic and does not constitute a guaranteed mechanical failure/)
    ).toBeInTheDocument();
  });

  it('renders top risk factors and protective factors breakdown', () => {
    render(<PredictiveRiskPanel riskData={mockRiskData} isLoading={false} />);

    expect(screen.getByText('coolant_temp_c')).toBeInTheDocument();
    expect(screen.getByText('+1.827')).toBeInTheDocument();
    expect(screen.getByText('oil_pressure_kpa')).toBeInTheDocument();
    expect(screen.getByText('-0.247')).toBeInTheDocument();
  });

  it('invokes work order callback when Dispatch button is clicked', () => {
    const handleWorkOrder = vi.fn();
    render(
      <PredictiveRiskPanel
        riskData={mockRiskData}
        isLoading={false}
        onOpenWorkOrder={handleWorkOrder}
      />
    );

    const button = screen.getByText('Dispatch Work Order');
    fireEvent.click(button);
    expect(handleWorkOrder).toHaveBeenCalledTimes(1);
  });

  it('renders loading skeleton when isLoading is true', () => {
    const { container } = render(
      <PredictiveRiskPanel riskData={null} isLoading={true} />
    );
    expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
  });
});
