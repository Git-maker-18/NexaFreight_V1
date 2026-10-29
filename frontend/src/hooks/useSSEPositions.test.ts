import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { buildSSEUrl, fetchStreamTicket, parsePositionPayload } from './useSSEPositions'

describe('useSSEPositions helper functions', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  describe('buildSSEUrl', () => {
    it('constructs correct SSE endpoint URL without token', () => {
      const url = buildSSEUrl('http://localhost:8000')
      expect(url).toBe('http://localhost:8000/api/map/positions/stream')
    })

    it('strips trailing slashes from base URL', () => {
      const url = buildSSEUrl('http://127.0.0.1:8000/')
      expect(url).toBe('http://127.0.0.1:8000/api/map/positions/stream')
    })

    it('appends ticket query param when ticket is provided', () => {
      const url = buildSSEUrl('http://localhost:8000', 'stream-ticket-abc')
      expect(url).toBe('http://localhost:8000/api/map/positions/stream?ticket=stream-ticket-abc')
    })

    it('path-prefix apiUrl builds a same-origin proxied URL (reverse-proxy deployments)', () => {
      ;(globalThis as Record<string, unknown>).window = {
        location: { origin: 'https://preview.example.app' },
      }
      try {
        const url = buildSSEUrl('/api/nexa', 'ticket-xyz')
        expect(url).toBe(
          'https://preview.example.app/api/nexa/map/positions/stream?ticket=ticket-xyz'
        )
      } finally {
        delete (globalThis as Record<string, unknown>).window
      }
    })
  })

  describe('fetchStreamTicket', () => {
    it('POSTs /api/map/positions/stream-ticket with Bearer token and returns ticket', async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ ticket: 'mock-ticket-999', expires_in: 60 }),
      })
      vi.stubGlobal('fetch', mockFetch)

      const ticket = await fetchStreamTicket('http://localhost:8000', 'user-jwt-token')

      expect(ticket).toBe('mock-ticket-999')
      expect(mockFetch).toHaveBeenCalledTimes(1)
      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/map/positions/stream-ticket',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: 'Bearer user-jwt-token',
          },
        }
      )
    })

    it('throws error when server returns non-ok status', async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
      })
      vi.stubGlobal('fetch', mockFetch)

      await expect(
        fetchStreamTicket('http://localhost:8000', 'bad-token')
      ).rejects.toThrow('Failed to obtain stream ticket: HTTP 401')
    })
  })

  describe('parsePositionPayload', () => {
    it('handles empty and heartbeat payloads gracefully', () => {
      expect(parsePositionPayload('')).toEqual({ updatedMap: {}, hasChanges: false })
      expect(parsePositionPayload('{}')).toEqual({ updatedMap: {}, hasChanges: false })
      expect(parsePositionPayload('[]')).toEqual({ updatedMap: {}, hasChanges: false })
      expect(parsePositionPayload('invalid-json')).toEqual({ updatedMap: {}, hasChanges: false })
    })

    it('parses array of PositionReport objects and keys by asset_id', () => {
      const payload = JSON.stringify([
        {
          asset_id: 'vessel-211281610',
          asset_type: 'SEA',
          latitude: 40.72,
          longitude: -2.13,
          speed_knots: 17.5,
          heading_deg: 67.2,
          provenance: 'REPLAYED',
          source: 'AIS_PARQUET_REPLAY',
          recorded_at: '2026-08-23T10:45:00Z',
        },
        {
          asset_id: 'truck-40',
          asset_type: 'ROAD',
          lat: 1.30,
          lon: 103.88,
          speed_knots: 32.4,
          heading_deg: 60.0,
          provenance: 'SIMULATED',
          source: 'ROAD_INTERPOLATION',
        },
      ])

      const { updatedMap, hasChanges } = parsePositionPayload(payload)
      expect(hasChanges).toBe(true)
      expect(Object.keys(updatedMap)).toHaveLength(2)

      const vessel = updatedMap['vessel-211281610']
      expect(vessel).toBeDefined()
      expect(vessel.asset_id).toBe('vessel-211281610')
      expect(vessel.asset_type).toBe('SEA')
      expect(vessel.lat).toBe(40.72)
      expect(vessel.lon).toBe(-2.13)
      expect(vessel.speed_knots).toBe(17.5)
      expect(vessel.provenance).toBe('REPLAYED')

      const truck = updatedMap['truck-40']
      expect(truck).toBeDefined()
      expect(truck.asset_id).toBe('truck-40')
      expect(truck.lat).toBe(1.30)
      expect(truck.lon).toBe(103.88)
    })

    it('overwrites previous position for the same asset_id rather than duplicating', () => {
      const initialPayload = JSON.stringify([
        {
          asset_id: 'vessel-1',
          lat: 10.0,
          lon: 20.0,
          speed_knots: 12.0,
        },
      ])

      const { updatedMap: firstMap } = parsePositionPayload(initialPayload, {})
      expect(firstMap['vessel-1'].lat).toBe(10.0)

      // Subsequent update with moving coordinates
      const updatePayload = JSON.stringify([
        {
          asset_id: 'vessel-1',
          lat: 10.5,
          lon: 20.6,
          speed_knots: 13.5,
        },
      ])

      const { updatedMap: secondMap, hasChanges } = parsePositionPayload(updatePayload, firstMap)
      expect(hasChanges).toBe(true)
      expect(Object.keys(secondMap)).toHaveLength(1)
      expect(secondMap['vessel-1'].lat).toBe(10.5)
      expect(secondMap['vessel-1'].lon).toBe(20.6)
      expect(secondMap['vessel-1'].speed_knots).toBe(13.5)
    })
  })
})
