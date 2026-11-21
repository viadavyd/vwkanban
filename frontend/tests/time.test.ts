import { expect, it } from "vitest";
import { timeAgo } from "../src/lib/time";

it("formats relative times", () => {
  const now = Date.parse("2026-11-21T12:00:00Z");
  const ago = (s: number) => timeAgo(new Date(now - s * 1000).toISOString(), now);
  expect(ago(5)).toBe("just now");
  expect(ago(-30)).toBe("just now"); // clock skew
  expect(ago(3 * 60)).toBe("3 min ago");
  expect(ago(5 * 3600)).toBe("5 h ago");
  expect(ago(2 * 86400)).toBe("2 d ago");
  expect(ago(40 * 86400)).toBe("2026-10-12");
});
