import { describe, expect, it } from "vitest";
import { fmtAgo, fmtTime, groupBy } from "./format";

describe("format helpers", () => {
  it("renders a dash for missing or invalid timestamps", () => {
    expect(fmtTime(null)).toBe("—");
    expect(fmtTime("not a date")).toBe("—");
  });

  it("describes elapsed time", () => {
    const now = Date.parse("2026-01-01T12:00:00Z");
    expect(fmtAgo(null, now)).toBe("never");
    expect(fmtAgo("2026-01-01T11:59:30Z", now)).toBe("30s ago");
    expect(fmtAgo("2026-01-01T11:50:00Z", now)).toBe("10 min ago");
    expect(fmtAgo("2026-01-01T09:00:00Z", now)).toBe("3 h ago");
    expect(fmtAgo("2025-12-30T12:00:00Z", now)).toBe("2 d ago");
  });

  it("groups items by key", () => {
    const g = groupBy([{ k: "a", v: 1 }, { k: "b", v: 2 }, { k: "a", v: 3 }], (x) => x.k);
    expect(g.a.map((x) => x.v)).toEqual([1, 3]);
    expect(g.b).toHaveLength(1);
  });
});
