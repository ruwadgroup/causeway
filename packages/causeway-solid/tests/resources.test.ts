import { createRoot } from "solid-js";
import { describe, expect, it, vi } from "vitest";

import { createClient, CausewayError } from "@causewayjs/client";

import { createCausewayResources } from "../src/index.js";
import type { RouteDescriptor, RouteMeta } from "@causewayjs/client";

interface Issue {
  id: number;
  title: string;
}

declare module "@causewayjs/client" {
  interface Register {
    routeKey: "GET /issues/$issue_id" | "POST /issues";
    queryRouteKey: "GET /issues/$issue_id";
    mutationRouteKey: "POST /issues";
    routeInput: {
      "GET /issues/$issue_id": { issueId: number };
      "POST /issues": { data: { title: string } };
    };
    routeData: {
      "GET /issues/$issue_id": Issue;
      "POST /issues": Issue;
    };
    routeError: {
      "GET /issues/$issue_id": CausewayError;
      "POST /issues": CausewayError;
    };
  }
}

const routes: Record<string, RouteDescriptor> = {
  getIssue: {
    method: "GET",
    path: "/issues/{issue_id}",
    routeKey: "GET /issues/$issue_id",
    params: [{ name: "issueId", alias: "issue_id", in: "path" }],
    result: true,
  },
  createIssue: {
    method: "POST",
    path: "/issues",
    routeKey: "POST /issues",
    params: [{ name: "data", alias: "data", in: "body" }],
    result: true,
  },
};

const routeMeta: RouteMeta[] = Object.entries(routes).map(([id, route]) => ({
  id,
  routeKey: route.routeKey,
  method: route.method,
  path: route.path,
  hasArgs: true,
}));

function createTestClient(fetch: typeof globalThis.fetch) {
  return createClient({
    fetch,
    routeMeta,
    loadRoute: (id) => {
      const route = routes[id];
      if (route === undefined) throw new Error(id);
      return route;
    },
  });
}

function wait(): Promise<void> {
  return new Promise((r) => setTimeout(r, 0));
}

describe("query resource", () => {
  function TypeProbe() {
    const resources = createCausewayResources(createTestClient(fetch));
    const issue = resources.query("GET /issues/$issue_id", () => ({ issueId: 1 }));
    issue.data()?.title.toUpperCase();

    const create = resources.mutation("POST /issues");
    void create.mutate({ data: { title: "new" } }).then((data) => data.id.toFixed());

    // @ts-expect-error input is inferred from the route key
    resources.query("GET /issues/$issue_id", () => ({ id: 1 }));
    // @ts-expect-error query resources only accept GET route keys
    resources.query("POST /issues", { data: { title: "new" } });
    // @ts-expect-error mutation input is inferred from the route key
    void create.mutate({ title: "new" });
    // @ts-expect-error mutation resources only accept non-GET route keys
    resources.mutation("GET /issues/$issue_id");

    return null;
  }
  void TypeProbe;

  it("loads route-key query data", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify({ ok: true, data: { id: 1, title: "hi" } }), {
          headers: { "content-type": "application/json" },
        }),
    );
    await createRoot(async (dispose) => {
      const resources = createCausewayResources(createTestClient(fetch));
      const q = resources.query("GET /issues/$issue_id", () => ({
        issueId: 1,
      }));

      await wait();
      await wait();
      await q.refresh();
      expect(q.data()).toEqual({ id: 1, title: "hi" });
      dispose();
    });
  });

  it("surfaces typed errors via the error signal", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(
          JSON.stringify({
            ok: false,
            error: { issue_id: 99, kind: "IssueNotFound" },
          }),
          { headers: { "content-type": "application/json" } },
        ),
    );
    await createRoot(async (dispose) => {
      const resources = createCausewayResources(createTestClient(fetch));
      const r = resources.query("GET /issues/$issue_id", () => ({
        issueId: 99,
      }));

      void r.refresh();
      await wait();
      await wait();
      expect(r.error()).toMatchObject({ issueId: 99, kind: "IssueNotFound" });
      dispose();
    });
  });
});

describe("mutation resource", () => {
  it("calls mutate and tracks state", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify({ ok: true, data: { id: 7, title: "new" } }), {
          headers: { "content-type": "application/json" },
        }),
    );
    await createRoot(async (dispose) => {
      const resources = createCausewayResources(createTestClient(fetch));
      const m = resources.mutation("POST /issues");
      const result = await m.mutate({ data: { title: "new" } });

      expect(result).toEqual({ id: 7, title: "new" });
      expect(m.data()).toEqual({ id: 7, title: "new" });
      expect(m.pending()).toBe(false);
      dispose();
    });
  });
});
