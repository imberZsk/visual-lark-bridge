import { describe, expect, it } from "vitest";
import { expandHomePath } from "../../electron/serviceManager.js";

describe("expandHomePath", () => {
  it("expands only a leading home marker", () => {
    expect(expandHomePath("~/bridge/config.json", "/Users/test")).toBe(
      "/Users/test/bridge/config.json",
    );
    expect(expandHomePath("/tmp/~/config.json", "/Users/test")).toBe(
      "/tmp/~/config.json",
    );
  });
});
