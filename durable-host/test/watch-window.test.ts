import assert from "node:assert/strict";
import test from "node:test";
import { nextWatchUpdate } from "../src/watch-window.ts";

test("snapshot and empty window", () => {
  assert.deepEqual(nextWatchUpdate(undefined, [{ id: 2 }]), { entries: [{ id: 2 }], gap: false });
  assert.deepEqual(nextWatchUpdate(undefined, []), { entries: [], gap: false });
});
test("no new entries", () => {
  assert.deepEqual(nextWatchUpdate(2, [{ id: 1 }, { id: 2 }]), { entries: [], gap: false });
});
test("new entries retain oldest-to-newest order", () => {
  assert.deepEqual(nextWatchUpdate(2, [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }]), {
    entries: [{ id: 3 }, { id: 4 }], gap: false,
  });
});
test("missing last-sent entry signals a gap", () => {
  assert.deepEqual(nextWatchUpdate(2, [{ id: 4 }, { id: 5 }]), {
    entries: [{ id: 4 }, { id: 5 }], gap: true,
  });
});
