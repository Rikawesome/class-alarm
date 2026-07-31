import assert from "node:assert/strict";
import test from "node:test";

import {
  getDefaultAlarmDisplayData,
  getSafeAlarmDisplayData,
} from "../alarm-display.js";

const course = {
  id: "course-1",
  name: "Distributed Systems",
};

test("uses locked display data when no formatter is provided", () => {
  assert.deepEqual(getSafeAlarmDisplayData(course), {
    title: "Distributed Systems",
    body: "Distributed Systems now",
  });
});

test("accepts valid display data from an injected formatter", () => {
  const result = getSafeAlarmDisplayData(course, () => ({
    title: "High-risk class",
    body: "Distributed Systems starts now",
  }));

  assert.deepEqual(result, {
    title: "High-risk class",
    body: "Distributed Systems starts now",
  });
});

test("falls back when an evolvable formatter throws", () => {
  const result = getSafeAlarmDisplayData(course, () => {
    throw new Error("evolvable feature failed");
  });

  assert.deepEqual(result, getDefaultAlarmDisplayData(course));
});

test("falls back when an evolvable formatter returns invalid data", () => {
  const result = getSafeAlarmDisplayData(course, () => ({
    title: "Missing body",
  }));

  assert.deepEqual(result, getDefaultAlarmDisplayData(course));
});
