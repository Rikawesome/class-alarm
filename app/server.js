import { createReadStream, existsSync } from "node:fs";
import { createServer } from "node:http";
import { extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { closeCourseDatabase } from "../locked/core-data/db.js";
import { createClassAlarmRuntime } from "./runtime.js";

const ROOT = resolve(fileURLToPath(new URL("..", import.meta.url)));
const WEB_ROOT = resolve(ROOT, "web");
const DIST_ROOT = resolve(ROOT, "dist");
const JSON_HEADERS = {
  "cache-control": "no-store",
  "content-type": "application/json; charset=utf-8",
};
const MIME_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
};

function sendJson(response, statusCode, body) {
  response.writeHead(statusCode, JSON_HEADERS);
  response.end(JSON.stringify(body));
}

async function readJsonBody(request) {
  const chunks = [];

  for await (const chunk of request) {
    chunks.push(chunk);
  }

  if (chunks.length === 0) {
    return {};
  }

  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function serveProductionFile(pathname, response) {
  const requestedPath =
    pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
  const candidate = resolve(DIST_ROOT, requestedPath);
  const safeCandidate = candidate.startsWith(DIST_ROOT)
    ? candidate
    : resolve(DIST_ROOT, "index.html");
  const filePath = existsSync(safeCandidate)
    ? safeCandidate
    : resolve(DIST_ROOT, "index.html");

  if (!existsSync(filePath)) {
    sendJson(response, 503, {
      error: "Frontend build not found. Run npm run build or start in development mode.",
    });
    return;
  }

  response.writeHead(200, {
    "content-type": MIME_TYPES[extname(filePath)] ?? "application/octet-stream",
  });
  createReadStream(filePath).pipe(response);
}

export async function createApplicationServer({
  runtime = createClassAlarmRuntime(),
  development = true,
  enableFrontend = true,
} = {}) {
  let vite = null;

  if (enableFrontend && development) {
    const { createServer: createViteServer } = await import("vite");
    vite = await createViteServer({
      root: WEB_ROOT,
      server: {
        middlewareMode: true,
      },
      appType: "spa",
    });
  }

  const eventClients = new Set();
  const removeNotificationListener = runtime.onNotification((notification) => {
    const message = `event: alarm\ndata: ${JSON.stringify(notification)}\n\n`;

    for (const client of eventClients) {
      client.write(message);
    }
  });

  const server = createServer(async (request, response) => {
    const requestUrl = new URL(request.url, "http://127.0.0.1");
    const pathname = requestUrl.pathname.replace(/\/+$/, "") || "/";

    try {
      if (request.method === "GET" && pathname === "/api/health") {
        sendJson(response, 200, {
          status: "ok",
          runtime: runtime.getSnapshot().status,
        });
        return;
      }

      if (request.method === "GET" && pathname === "/api/bootstrap") {
        sendJson(response, 200, {
          courses: runtime.listCourses(),
          runtime: runtime.getSnapshot(),
        });
        return;
      }

      if (request.method === "GET" && pathname === "/api/events") {
        response.writeHead(200, {
          "cache-control": "no-cache",
          connection: "keep-alive",
          "content-type": "text/event-stream",
        });
        response.write(
          `event: connected\ndata: ${JSON.stringify(runtime.getSnapshot())}\n\n`,
        );
        eventClients.add(response);

        request.on("close", () => {
          eventClients.delete(response);
        });
        return;
      }

      if (
        request.method === "POST" &&
        pathname === "/api/alarms/test"
      ) {
        const body = await readJsonBody(request);
        const notification = runtime.triggerTestAlarm(body.courseId);
        sendJson(response, 201, { notification });
        return;
      }


      if (
        request.method === "POST" &&
        pathname === "/api/courses/import"
      ) {
        const body = await readJsonBody(request);
        const imported = runtime.importCourses(body.courses ?? []);
        sendJson(response, 201, {
          imported,
          courses: runtime.listCourses(),
          runtime: runtime.getSnapshot(),
        });
        return;
      }

      if (
        request.method === "POST" &&
        pathname.match(/^\/api\/courses\/[^\/]+\/risk$/)
      ) {
        const parts = pathname.split("/");
        const courseId = parts[3];
        const body = await readJsonBody(request);
        const course = runtime.toggleCourseRisk(courseId, Boolean(body.is_risky));
        sendJson(response, 200, {
          course,
          courses: runtime.listCourses(),
          runtime: runtime.getSnapshot(),
        });
        return;
      }

      if (
        request.method === "POST" &&
        pathname === "/api/courses"
      ) {
        const body = await readJsonBody(request);
        const course = runtime.addCourse({
          name: body.name,
          day_of_week: Number(body.day_of_week),
          start_time: body.start_time,
          end_time: body.end_time,
          recurrence: body.recurrence,
        });
        sendJson(response, 201, {
          course,
          courses: runtime.listCourses(),
          runtime: runtime.getSnapshot(),
        });
        return;
      }

      if (
        request.method === "DELETE" &&
        pathname.startsWith("/api/courses/")
      ) {
        const courseId = pathname.split("/")[3];
        const course = runtime.removeCourse(courseId);
        sendJson(response, 200, {
          course,
          courses: runtime.listCourses(),
          runtime: runtime.getSnapshot(),
        });
        return;
      }


      if (pathname.startsWith("/api/")) {
        sendJson(response, 404, { error: "API endpoint not found." });
        return;
      }

      if (!enableFrontend) {
        sendJson(response, 404, { error: "Frontend disabled." });
        return;
      }

      if (vite) {
        vite.middlewares(request, response, (error) => {
          if (error) {
            sendJson(response, 500, { error: error.message });
          }
        });
        return;
      }

      serveProductionFile(pathname, response);
    } catch (error) {
      const statusCode =
        error instanceof SyntaxError || error.message.includes("No course")
          ? 400
          : 500;
      sendJson(response, statusCode, { error: error.message });
    }
  });

  async function listen({
    port = Number(process.env.PORT ?? 4173),
    host = process.env.HOST ?? "127.0.0.1",
  } = {}) {
    runtime.start();

    await new Promise((resolveListen, rejectListen) => {
      server.once("error", rejectListen);
      server.listen(port, host, resolveListen);
    });

    const address = server.address();
    return {
      host,
      port: typeof address === "object" ? address.port : port,
      url: `http://${host}:${typeof address === "object" ? address.port : port}`,
    };
  }

  async function close() {
    removeNotificationListener();
    runtime.stop();
    closeCourseDatabase();

    for (const client of eventClients) {
      client.end();
    }
    eventClients.clear();

    await vite?.close();

    if (server.listening) {
      await new Promise((resolveClose, rejectClose) => {
        server.close((error) => {
          if (error) {
            rejectClose(error);
            return;
          }
          resolveClose();
        });
      });
    }
  }

  return {
    close,
    listen,
    server,
  };
}

const isEntryPoint =
  process.argv[1] &&
  fileURLToPath(import.meta.url) === resolve(process.argv[1]);

if (isEntryPoint) {
  const development = !process.argv.includes("--production");
  const application = await createApplicationServer({ development });
  const address = await application.listen();

  console.log(`Class Alarm is running at ${address.url}`);

  const shutdown = async () => {
    await application.close();
    process.exit(0);
  };

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}


