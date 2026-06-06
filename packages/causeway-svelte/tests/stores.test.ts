import { describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

import { createClient, CausewayError } from "@causewayjs/client";

import { createCausewayStores } from "../src/index.js";
import type { RouteDescriptor, RouteMeta } from "@causewayjs/client";

interface Issue {
  id: number;
  title: string;
}

interface IssueEvent {
  kind: "tick";
  n: number;
}

declare module "@causewayjs/client" {
  interface Register {
    routeKey: "GET /issues/$issue_id" | "POST /issues" | "GET /events";
    queryRouteKey: "GET /issues/$issue_id" | "GET /events";
    mutationRouteKey: "POST /issues";
    routeInput: {
      "GET /issues/$issue_id": { issueId: number };
      "POST /issues": { data: { title: string } };
      "GET /events": { topic: string };
    };
    routeData: {
      "GET /issues/$issue_id": Issue;
      "POST /issues": Issue;
      "GET /events": IssueEvent;
    };
    routeError: {
      "GET /issues/$issue_id": CausewayError;
      "POST /issues": CausewayError;
      "GET /events": Error;
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
  events: {
    method: "GET",
    path: "/events",
    routeKey: "GET /events",
    params: [{ name: "topic", alias: "topic", in: "query" }],
    streams: true,
  },
};

const routeMeta: RouteMeta[] = Object.entries(routes).map(([id, route]) => ({
  id,
  routeKey: route.routeKey,
  method: route.method,
  path: route.path,
  ...((route.params?.length ?? 0) > 0 ? { hasArgs: true } : {}),
  ...(route.streams ? { streams: true } : {}),
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

function stream(frames: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame));
      controller.close();
    },
  });
}

describe("query store", () => {
  function typeProbe() {
    const stores = createCausewayStores(createTestClient(fetch));
    const issue = stores.query("GET /issues/$issue_id", { issueId: 1 });
    issue.subscribe((value) => value.data?.title.toUpperCase());

    const create = stores.mutation("POST /issues");
    create.subscribe((value) => {
      void value.mutate({ data: { title: "new" } }).then((data) => data.id.toFixed());
    });

    stores.subscription("GET /events", { topic: "x" }, (event) => event.n.toFixed());

    // @ts-expect-error input is inferred from the route key
    stores.query("GET /issues/$issue_id", { id: 1 });
    // @ts-expect-error query stores only accept GET route keys
    stores.query("POST /issues", { data: { title: "new" } });
    // @ts-expect-error mutation input is inferred from the route key
    create.subscribe((value) => void value.mutate({ title: "new" }));
    // @ts-expect-error mutation stores only accept non-GET route keys
    stores.mutation("GET /issues/$issue_id");
  }
  void typeProbe;

  it("loads route-key query data", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify({ ok: true, data: { id: 1, title: "hi" } }), {
          headers: { "content-type": "application/json" },
        }),
    );
    const stores = createCausewayStores(createTestClient(fetch));
    const store = stores.query("GET /issues/$issue_id", { issueId: 1 });

    await wait();
    await wait();
    const val = get(store);
    expect(val.pending).toBe(false);
    expect(val.data).toEqual({ id: 1, title: "hi" });
    expect(val.error).toBeUndefined();
  });

  it("passes typed errors through .error on rejection", async () => {
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
    const stores = createCausewayStores(createTestClient(fetch));
    const store = stores.query("GET /issues/$issue_id", { issueId: 99 });

    await wait();
    await wait();
    const val = get(store);
    expect(val.pending).toBe(false);
    expect(val.error).toBeInstanceOf(CausewayError);
    expect(val.error).toMatchObject({ issueId: 99, kind: "IssueNotFound" });
  });

  it("does not fetch when enabled=false", () => {
    const fetch = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify({ ok: true, data: { id: 1, title: "x" } }), {
          headers: { "content-type": "application/json" },
        }),
    );
    const stores = createCausewayStores(createTestClient(fetch));
    stores.query("GET /issues/$issue_id", { issueId: 1 }, { enabled: false });
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("mutation store", () => {
  it("calls mutate and exposes data", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify({ ok: true, data: { id: 5, title: "new" } }), {
          headers: { "content-type": "application/json" },
        }),
    );
    const stores = createCausewayStores(createTestClient(fetch));
    const store = stores.mutation("POST /issues");

    const out = await get(store).mutate({ data: { title: "new" } });
    expect(out).toEqual({ id: 5, title: "new" });
    expect(get(store).pending).toBe(false);
  });
});

describe("subscription store", () => {
  it("forwards stream events to onEvent and closes cleanly", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(
          stream([
            'data: {"kind":"tick","n":1}\n\n',
            'data: {"kind":"tick","n":2}\n\n',
            "event: done\ndata: {}\n\n",
          ]),
          { headers: { "content-type": "text/event-stream" } },
        ),
    );
    const seen: number[] = [];
    const stores = createCausewayStores(createTestClient(fetch));
    const store = stores.subscription("GET /events", { topic: "x" }, (ev) => seen.push(ev.n));
    const unsub = store.subscribe(() => {});

    await wait();
    await wait();
    await wait();
    expect(seen).toEqual([1, 2]);
    expect(get(store).status).toBe("closed");
    unsub();
  });
});
