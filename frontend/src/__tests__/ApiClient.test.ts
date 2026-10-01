import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api, ApiError } from '../services/api';

describe('Typed API Client', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('injects Authorization Bearer header into requests', async () => {
    let capturedHeaders: Headers | undefined;

    global.fetch = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      capturedHeaders = init.headers as Headers;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ items: [], pagination: { total: 0, limit: 10, offset: 0, has_more: false } }),
      });
    });

    await api.getVehicles({ limit: 10 });

    expect(capturedHeaders).toBeDefined();
    expect(capturedHeaders?.get('Authorization')).toMatch(/^Bearer /);
  });

  it('constructs correct query parameters for vehicle listing', async () => {
    let capturedUrl: string = '';

    global.fetch = vi.fn().mockImplementation((url: string) => {
      capturedUrl = url;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ items: [], pagination: { total: 0, limit: 25, offset: 50, has_more: false } }),
      });
    });

    await api.getVehicles({ limit: 25, offset: 50, vehicle_type: 'BEV', fleet_id: 'fleet-123' });

    expect(capturedUrl).toContain('/vehicles?');
    expect(capturedUrl).toContain('limit=25');
    expect(capturedUrl).toContain('offset=50');
    expect(capturedUrl).toContain('vehicle_type=BEV');
    expect(capturedUrl).toContain('fleet_id=fleet-123');
  });

  it('throws ApiError with structured details on HTTP 404', async () => {
    global.fetch = vi.fn().mockImplementation(() => {
      return Promise.resolve({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        json: () =>
          Promise.resolve({
            error: {
              code: 'VEHICLE_NOT_FOUND',
              message: 'Vehicle with VIN NON_EXISTENT not found in fleet',
            },
          }),
      });
    });

    await expect(api.getVehicleDetail('NON_EXISTENT')).rejects.toThrow(ApiError);
    await expect(api.getVehicleDetail('NON_EXISTENT')).rejects.toMatchObject({
      code: 'VEHICLE_NOT_FOUND',
      statusCode: 404,
    });
  });
});
