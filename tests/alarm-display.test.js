import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  getDefaultAlarmDisplayData,
  getSafeAlarmDisplayData,
} from "../locked/alarm-engine/alarm-display.js";

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

test("locked modules do not import evolvable code", async () => {
  const lockedUrl = new URL("../locked/", import.meta.url);
  const entries = await readdir(fileURLToPath(lockedUrl), {
    recursive: true,
    withFileTypes: true,
  });
  const violations = [];

  for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith(".js")) {
      continue;
    }

    const source = await readFile(join(entry.parentPath, entry.name), "utf8");

    if (/(?:from\s+|import\s*\()["'][^"']*evolvable\//.test(source)) {
      violations.push(`${entry.parentPath}/${entry.name}`);
    }
  }

  assert.deepEqual(violations, []);
});
