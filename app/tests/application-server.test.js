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

test("allows creating, toggling risk, and deleting courses through API", async () => {
  // Create course
  const createRes = await fetch(`${baseUrl}/api/courses`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      name: "Quantum Mechanics",
      day_of_week: 3,
      start_time: "11:00",
      end_time: "12:30"
    })
  });
  const createData = await createRes.json();
  assert.equal(createRes.status, 201);
  assert.equal(createData.course.name, "Quantum Mechanics");
  const courseId = createData.course.id;

  // Toggle risk
  const riskRes = await fetch(`${baseUrl}/api/courses/${courseId}/risk`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ is_risky: true })
  });
  const riskData = await riskRes.json();
  assert.equal(riskRes.status, 200);
  assert.equal(riskData.course.is_risky, true);

  // Delete course
  const deleteRes = await fetch(`${baseUrl}/api/courses/${courseId}`, {
    method: "DELETE"
  });
  const deleteData = await deleteRes.json();
  assert.equal(deleteRes.status, 200);
  assert.equal(deleteData.course.id, courseId);
});

test("risk state persists through the injected personal-data capability", async () => {
  const selectedCourse = runtime.listCourses().find((course) => course.id !== "course-systems-design");
  assert.equal(selectedCourse.is_risky, false);

  const toggled = runtime.toggleCourseRisk(selectedCourse.id, true);
  assert.equal(toggled.is_risky, true);

  const { createClassAlarmRuntime } = await import("../runtime.js");
  const restartedRuntime = createClassAlarmRuntime({ scheduleDailyRefresh: false });
  assert.equal(
    restartedRuntime.listCourses().find((course) => course.id === selectedCourse.id).is_risky,
    true,
  );

  restartedRuntime.toggleCourseRisk(selectedCourse.id, false);
  restartedRuntime.stop();
});

test("routes generic extension state and actions through the runtime host", async () => {
  const initialResponse = await fetch(`${baseUrl}/api/extensions/weekly-goals`);
  const initial = await initialResponse.json();
  assert.equal(initialResponse.status, 200);
  assert.ok(Array.isArray(initial.state));

  const addResponse = await fetch(`${baseUrl}/api/extensions/weekly-goals`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ action: "add", input: { title: "Test engine route" } }),
  });
  const added = await addResponse.json();
  assert.equal(addResponse.status, 200);
  assert.equal(added.result.at(-1).title, "Test engine route");

  const deleteResponse = await fetch(`${baseUrl}/api/extensions/weekly-goals`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ action: "delete", input: { id: added.result.at(-1).id } }),
  });
  assert.equal(deleteResponse.status, 200);
});
