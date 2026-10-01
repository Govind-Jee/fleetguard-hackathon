import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { HealthBadge, RiskBadge, PowertrainBadge, SeverityBadge } from '../components/common/Badge';

describe('Badge Components', () => {
  it('renders HealthBadge with NOMINAL status', () => {
    render(<HealthBadge status="NOMINAL" />);
    expect(screen.getByText('NOMINAL')).toBeInTheDocument();
  });

  it('renders HealthBadge with CRITICAL status and red styling', () => {
    render(<HealthBadge status="CRITICAL" />);
    expect(screen.getByText('CRITICAL')).toBeInTheDocument();
  });

  it('renders HealthBadge fallback when status is null', () => {
    render(<HealthBadge status={null} />);
    expect(screen.getByText('UNKNOWN')).toBeInTheDocument();
  });

  it('renders RiskBadge with LOW, MEDIUM, HIGH, and CRITICAL levels', () => {
    const { rerender } = render(<RiskBadge level="LOW" />);
    expect(screen.getByText('LOW')).toBeInTheDocument();

    rerender(<RiskBadge level="MEDIUM" />);
    expect(screen.getByText('MEDIUM')).toBeInTheDocument();

    rerender(<RiskBadge level="HIGH" />);
    expect(screen.getByText('HIGH')).toBeInTheDocument();

    rerender(<RiskBadge level="CRITICAL" />);
    expect(screen.getByText('CRITICAL')).toBeInTheDocument();
  });

  it('renders PowertrainBadge correctly for ICE, HEV, and BEV', () => {
    const { rerender } = render(<PowertrainBadge type="ICE" />);
    expect(screen.getByText('ICE (Diesel)')).toBeInTheDocument();

    rerender(<PowertrainBadge type="HEV" />);
    expect(screen.getByText('HEV (Hybrid)')).toBeInTheDocument();

    rerender(<PowertrainBadge type="BEV" />);
    expect(screen.getByText('BEV (Electric)')).toBeInTheDocument();
  });

  it('renders SeverityBadge for CRITICAL, WARNING, INFO', () => {
    const { rerender } = render(<SeverityBadge severity="CRITICAL" />);
    expect(screen.getByText('CRITICAL')).toBeInTheDocument();

    rerender(<SeverityBadge severity="WARNING" />);
    expect(screen.getByText('WARNING')).toBeInTheDocument();

    rerender(<SeverityBadge severity="INFO" />);
    expect(screen.getByText('INFO')).toBeInTheDocument();
  });
});
