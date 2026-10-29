import { describe, expect, it } from "vitest";
import { NAVIGATION, visibleSections } from "./nav";

const labels = (can: (p: string) => boolean) => visibleSections(can).flatMap((s) => s.items.map((i) => i.label));

describe("navigation", () => {
  it("always shows the overview and nothing else without permissions", () => {
    expect(labels(() => false)).toEqual(["Overview"]);
  });

  it("shows admin pages only for the permissions that unlock them", () => {
    expect(labels((p) => p === "audit.view")).toEqual(["Overview", "Audit Logs"]);
    expect(labels((p) => p === "users.view")).toContain("Users");
    expect(labels((p) => p === "users.view")).not.toContain("Roles & RBAC");
  });

  it("shows everything to a user who has every permission", () => {
    const all = NAVIGATION.flatMap((s) => s.items).map((i) => i.label);
    expect(labels(() => true)).toEqual(all);
  });

  it("drops empty sections", () => {
    expect(visibleSections(() => false).every((s) => s.items.length > 0)).toBe(true);
  });
});
