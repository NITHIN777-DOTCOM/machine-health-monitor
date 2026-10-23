import { describe, expect, it } from "vitest";
import { chartGrid } from "./grid";

describe("chartGrid", () => {
  it("puts 4 sensors + health in one row on a 1920 px screen", () => {
    expect(chartGrid(5, 1850)).toEqual({ cols: 5, lastSpan: 1 });
  });

  it("stretches the last chart instead of leaving a gap at 1366 px", () => {
    expect(chartGrid(5, 1300)).toEqual({ cols: 3, lastSpan: 2 });
  });

  it("balances rows: 4 charts in 3 possible columns -> 2 x 2", () => {
    expect(chartGrid(4, 1100)).toEqual({ cols: 2, lastSpan: 1 });
  });

  it("falls back to one column on narrow screens and handles no charts", () => {
    expect(chartGrid(5, 300)).toEqual({ cols: 1, lastSpan: 1 });
    expect(chartGrid(0, 1000)).toEqual({ cols: 1, lastSpan: 1 });
  });
});
