import React, { useState } from 'react';
import { api } from '../../services/api';
import { WorkOrderPriority, WorkOrderResponse } from '../../types/api';
import { X, Wrench, CheckCircle2, AlertCircle } from 'lucide-react';

interface WorkOrderModalProps {
  isOpen: boolean;
  onClose: () => void;
  vin: string;
  initialPriority?: WorkOrderPriority;
  initialNotes?: string;
  onSuccess?: (workOrder: WorkOrderResponse) => void;
}

const SERVICE_TYPES = [
  { id: 1, name: 'Comprehensive Safety Inspection', desc: 'Standard 40-point vehicle safety and mechanical check' },
  { id: 2, name: 'Oil & Fluid Renewal', desc: 'Engine oil, transmission fluid, and coolant replacement' },
  { id: 3, name: 'Brake Rotor & Pad Replacement', desc: 'Friction components service and caliper calibration' },
  { id: 4, name: 'Battery & High-Voltage System Diagnostics', desc: 'BEV/HEV pack diagnostics, cell balancing check' },
  { id: 5, name: 'Powertrain & Mechanical Overhaul', desc: 'Major engine, transmission, or inverter remediation' },
];

export const WorkOrderModal: React.FC<WorkOrderModalProps> = ({
  isOpen,
  onClose,
  vin,
  initialPriority = 'HIGH',
  initialNotes = '',
  onSuccess,
}) => {
  const [typeId, setTypeId] = useState<number>(1);
  const [priority, setPriority] = useState<WorkOrderPriority>(initialPriority);
  const [notes, setNotes] = useState<string>(initialNotes);
  const [scheduledDate, setScheduledDate] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [createdOrder, setCreatedOrder] = useState<WorkOrderResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);

    try {
      const order = await api.createWorkOrder({
        vin,
        type_id: typeId,
        priority,
        scheduled_at: scheduledDate ? new Date(scheduledDate).toISOString() : undefined,
        notes: notes.trim() || undefined,
      });

      setCreatedOrder(order);
      if (onSuccess) {
        onSuccess(order);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to dispatch work order');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReset = () => {
    setCreatedOrder(null);
    setError(null);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-slate-750 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="px-6 py-4 border-b border-slate-800 bg-slate-950/80 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-cyan-950 border border-cyan-800 flex items-center justify-center">
              <Wrench className="w-4 h-4 text-cyan-400" />
            </div>
            <div>
              <h3 className="font-semibold text-sm text-slate-100">
                Dispatch Maintenance Work Order
              </h3>
              <p className="text-xs text-slate-400 font-mono">VIN: {vin}</p>
            </div>
          </div>
          <button
            onClick={handleReset}
            className="text-slate-400 hover:text-slate-200 p-1 rounded-lg hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6">
          {createdOrder ? (
            <div className="space-y-4 py-2">
              <div className="p-4 rounded-xl bg-emerald-950/60 border border-emerald-800/80 flex items-start gap-3">
                <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <h4 className="text-sm font-semibold text-emerald-200">
                    Work Order Successfully Dispatched
                  </h4>
                  <p className="text-xs text-emerald-300/80">
                    The work order has been committed to the 3NF relational database.
                  </p>
                </div>
              </div>

              <div className="bg-slate-950 border border-slate-800 rounded-xl p-4 space-y-2 text-xs">
                <div className="flex justify-between py-1 border-b border-slate-850">
                  <span className="text-slate-400">Order ID:</span>
                  <span className="font-mono text-slate-200">{createdOrder.work_order_id}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-850">
                  <span className="text-slate-400">VIN:</span>
                  <span className="font-mono text-slate-200">{createdOrder.vin}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-850">
                  <span className="text-slate-400">Priority:</span>
                  <span className="font-semibold text-rose-400">{createdOrder.priority}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-850">
                  <span className="text-slate-400">Status:</span>
                  <span className="font-mono text-cyan-400">{createdOrder.status}</span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-slate-400">Created:</span>
                  <span className="text-slate-400 font-mono">
                    {new Date(createdOrder.created_at).toLocaleString()}
                  </span>
                </div>
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  type="button"
                  onClick={handleReset}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold transition-colors"
                >
                  Close
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <div className="p-3 rounded-lg bg-rose-950/60 border border-rose-800 text-rose-300 text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {/* Service Type Selection */}
              <div>
                <label htmlFor="service-type-select" className="block text-xs font-semibold text-slate-300 mb-1.5">
                  Maintenance Service Type:
                </label>
                <select
                  id="service-type-select"
                  value={typeId}
                  onChange={(e) => setTypeId(Number(e.target.value))}
                  className="w-full bg-slate-950 border border-slate-750 text-xs text-slate-200 rounded-lg p-2.5 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                >
                  {SERVICE_TYPES.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name} (Type #{t.id})
                    </option>
                  ))}
                </select>
                <p className="text-[11px] text-slate-500 mt-1">
                  {SERVICE_TYPES.find((t) => t.id === typeId)?.desc}
                </p>
              </div>

              {/* Priority & Scheduling Grid */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="priority-select" className="block text-xs font-semibold text-slate-300 mb-1.5">
                    Priority:
                  </label>
                  <select
                    id="priority-select"
                    value={priority}
                    onChange={(e) => setPriority(e.target.value as WorkOrderPriority)}
                    className="w-full bg-slate-950 border border-slate-750 text-xs text-slate-200 rounded-lg p-2.5 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                  >
                    <option value="LOW">LOW</option>
                    <option value="MEDIUM">MEDIUM</option>
                    <option value="HIGH">HIGH</option>
                    <option value="CRITICAL">CRITICAL</option>
                  </select>
                </div>

                <div>
                  <label htmlFor="scheduled-date-input" className="block text-xs font-semibold text-slate-300 mb-1.5">
                    Schedule Target:
                  </label>
                  <input
                    id="scheduled-date-input"
                    type="datetime-local"
                    value={scheduledDate}
                    onChange={(e) => setScheduledDate(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-750 text-xs text-slate-200 rounded-lg p-2.5 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                  />
                </div>
              </div>

              {/* Dispatch Notes */}
              <div>
                <label htmlFor="work-order-notes" className="block text-xs font-semibold text-slate-300 mb-1.5">
                  Technician Notes / Context:
                </label>
                <textarea
                  id="work-order-notes"
                  rows={3}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Reason for maintenance dispatch, predicted failure indicators, or specific symptoms observed..."
                  className="w-full bg-slate-950 border border-slate-750 text-xs text-slate-200 rounded-lg p-2.5 focus:outline-none focus:ring-1 focus:ring-cyan-500 placeholder-slate-600"
                />
              </div>

              {/* Action buttons */}
              <div className="pt-2 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-5 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold shadow-sm disabled:opacity-50 transition-colors flex items-center gap-1.5"
                >
                  {isSubmitting ? (
                    'Dispatching...'
                  ) : (
                    <>
                      <Wrench className="w-3.5 h-3.5" />
                      Create Work Order
                    </>
                  )}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};
