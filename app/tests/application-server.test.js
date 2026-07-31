import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";

const temporaryRoot = await mkdtemp(join(tmpdir(), "darwin-app-"));
process.env.CLASS_ALARM_DB_PATH = join(temporaryRoot, "application.db");

const { createClassAlarmRuntime } = await import("../runtime.js");
const { createApplicationServer } = await import("../server.js");

const runtime = createClassAlarmRuntime({
  scheduleDailyRefresh: false,
});
const application = await createApplicationServer({
  runtime,
  development: false,
  enableFrontend: false,
});
let baseUrl;

before(async () => {
  const address = await application.listen({
    host: "127.0.0.1",
    port: 0,
  });
  baseUrl = address.url;
});

after(async () => {
  await application.close();
  assert.ok(temporaryRoot.startsWith(tmpdir()));
  await rm(temporaryRoot, { recursive: true, force: true });
});

test("exposes the runnable course and alarm state", async () => {
  const response = await fetch(`${baseUrl}/api/bootstrap`);
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(body.runtime.status, "running");
  assert.equal(body.courses.length, 4);
  assert.equal(
    body.courses.some((course) => course.is_risky),
    true,
  );
});

test("delivers a test alarm through the composed formatter", async () => {
  const bootstrapResponse = await fetch(`${baseUrl}/api/bootstrap`);
  const bootstrap = await bootstrapResponse.json();
  const selectedCourse = bootstrap.courses.find((course) => course.is_risky);

  const response = await fetch(`${baseUrl}/api/alarms/test`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: JSON.stringify({
      courseId: selectedCourse.id,
    }),
  });
  const body = await response.json();

  assert.equal(response.status, 201);
  assert.equal(body.notification.courseId, selectedCourse.id);
  assert.equal(body.notification.source, "test");
  assert.match(body.notification.body, /Risky to skip/);

  const refreshedResponse = await fetch(`${baseUrl}/api/bootstrap`);
  const refreshed = await refreshedResponse.json();
  assert.equal(
    refreshed.runtime.recentNotifications[0].id,
    body.notification.id,
  );
});
