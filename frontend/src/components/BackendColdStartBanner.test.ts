import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import BackendColdStartBanner from './BackendColdStartBanner';

describe('BackendColdStartBanner Component', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('is exported as a function/component', () => {
    expect(typeof BackendColdStartBanner).toBe('function');
  });
});
