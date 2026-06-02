import { describe, expect, it, vi } from "vitest";

import { createRouteKeyClient } from "../src/client.js";
import type { RouteDescriptor, RouteMeta } from "../src/types.js";

const routes: Record<string, RouteDescriptor> = {
  getCustomer: {
    method: "GET",
    path: "/customers/{id}",
    routeKey: "GET /customers/$id",
    params: [{ name: "id", alias: "id", in: "path" }],
  },
  screenCustomer: {
    method: "POST",
    path: "/customers/{id}/screen",
    routeKey: "POST /customers/$id/screen",
    params: [{ name: "id", alias: "id", in: "path" }],
    refreshes: ["GET /customers/$id"],
  },
  getTeams: {
    method: "GET",
    path: "/staff/teams",
    routeKey: "GET /staff/teams",
  },
  createTeam: {
    method: "POST",
    path: "/staff/teams",
    routeKey: "POST /staff/teams",
    params: [{ name: "body", alias: "body", in: "body" }],
    refreshes: ["GET /staff/teams"],
  },
  getExport: {
    method: "GET",
    path: "/exports/{id}",
    routeKey: "GET /exports/$id",
    params: [{ name: "id", alias: "id", in: "path" }],
  },
  createExport: {
    method: "POST",
    path: "/exports",
    routeKey: "POST /exports",
    params: [{ name: "body", alias: "body", in: "body" }],
    refreshes: ["GET /exports/$id"],
  },
};

const routeMeta: RouteMeta[] = Object.entries(routes).map(([id, route]) => ({
  id,
  routeKey: route.routeKey,
  method: route.method,
  path: route.path,
  refreshes: route.refreshes,
  hasArgs: true,
}));

function makeClient(fetch: typeof globalThis.fetch) {
  return createRouteKeyClient({
    baseUrl: "https://api.test",
    fetch,
    routeMeta,
    loadRoute: (id) => {
      const route = routes[id];
      if (route === undefined) throw new Error(id);
      return route;
    },
  });
}

describe("createRouteKeyClient", () => {
  it("dedupes in-flight queries by route key and canonical input", async () => {
    const fetchMock = vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify({ id: "c_1" }), {
          headers: { "content-type": "application/json" },
        }),
    );
    const client = makeClient(fetchMock);

    const [a, b] = await Promise.all([
      client.query("GET /customers/$id", { id: "c_1" }),
      client.query("GET /customers/$id", { id: "c_1" }),
    ]);

    expect(a).toEqual({ id: "c_1" });
    expect(b).toEqual({ id: "c_1" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("passes abort signals through to fetch", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn<typeof fetch>(async (_url, init) => {
      expect(init?.signal).toBe(controller.signal);
      return new Response(JSON.stringify({ id: "c_1" }), {
        headers: { "content-type": "application/json" },
      });
    });
    const client = makeClient(fetchMock);

    await client.query("GET /customers/$id", { id: "c_1" }, { signal: controller.signal });
  });

  it("fails before fetch when a direct call is missing a path parameter", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    const client = makeClient(fetchMock);

    await expect(client.query("GET /customers/$id", {})).rejects.toThrow(
      'Missing path parameter "id"',
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("runs declared refreshes after a successful mutation", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (url, init) => {
      if (init?.method === "POST") {
        return new Response(JSON.stringify({ screened: true }), {
          headers: { "content-type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ id: String(url).split("/").pop(), screened: true }), {
        headers: { "content-type": "application/json" },
      });
    });
    const client = makeClient(fetchMock);

    await client.mutate("POST /customers/$id/screen", { id: "c_1" });

    expect(fetchMock.mock.calls.map(([url, init]) => [url, init?.method])).toEqual([
      ["https://api.test/customers/c_1/screen", "POST"],
      ["https://api.test/customers/c_1", "GET"],
    ]);
    expect(client.getData("GET /customers/$id", { id: "c_1" })).toEqual({
      id: "c_1",
      screened: true,
    });
  });

  it("projects mutation input to the refreshed query route input", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (_url, init) => {
      if (init?.method === "POST") {
        return new Response(JSON.stringify({ id: "team_1" }), {
          headers: { "content-type": "application/json" },
        });
      }
      return new Response(JSON.stringify([{ id: "team_1", name: "Platform" }]), {
        headers: { "content-type": "application/json" },
      });
    });
    const client = makeClient(fetchMock);

    await client.mutate("POST /staff/teams", { body: { name: "Platform" } });

    expect(fetchMock.mock.calls.map(([url, init]) => [url, init?.method, init?.body])).toEqual([
      ["https://api.test/staff/teams", "POST", JSON.stringify({ name: "Platform" })],
      ["https://api.test/staff/teams", "GET", undefined],
    ]);
    expect(client.getData("GET /staff/teams")).toEqual([{ id: "team_1", name: "Platform" }]);
    expect(client.getData("GET /staff/teams", { body: { name: "Platform" } })).toBeUndefined();
  });

  it("does not reject a successful mutation when an automatic refresh fails", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (_url, init) => {
      if (init?.method === "POST") {
        return new Response(JSON.stringify({ screened: true }), {
          headers: { "content-type": "application/json" },
        });
      }
      return new Response("Not Found", { status: 404 });
    });
    const client = makeClient(fetchMock);

    await expect(client.mutate("POST /customers/$id/screen", { id: "c_1" })).resolves.toEqual({
      screened: true,
    });

    expect(fetchMock.mock.calls.map(([url, init]) => [url, init?.method])).toEqual([
      ["https://api.test/customers/c_1/screen", "POST"],
      ["https://api.test/customers/c_1", "GET"],
    ]);
    expect(client.getQueryState("GET /customers/$id", { id: "c_1" }).error).toMatchObject({
      kind: "HttpError",
      status: 404,
    });
  });

  it("skips parameterized refreshes when the mutation input cannot fill the path", async () => {
    const fetchMock = vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify({ id: "export_1" }), {
          headers: { "content-type": "application/json" },
        }),
    );
    const client = makeClient(fetchMock);

    await client.mutate("POST /exports", { body: { kind: "customers" } });

    expect(fetchMock.mock.calls.map(([url, init]) => [url, init?.method])).toEqual([
      ["https://api.test/exports", "POST"],
    ]);
  });

  it("does not notify subscribers when hydrating an unchanged snapshot", async () => {
    const fetchMock = vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify({ id: "c_1" }), {
          headers: { "content-type": "application/json" },
        }),
    );
    const client = makeClient(fetchMock);
    const snapshot = {
      version: 1 as const,
      queries: [
        {
          routeKey: "GET /customers/$id",
          input: { id: "c_1" },
          scope: null,
          data: { id: "c_1" },
          updatedAt: 1,
        },
      ],
    };
    let calls = 0;
    client.subscribe("GET /customers/$id", { id: "c_1" }, () => {
      calls += 1;
    });

    client.hydrate(snapshot);
    client.hydrate(snapshot);

    expect(calls).toBe(1);
  });

  it("does not refresh after a failed mutation", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => new Response("boom", { status: 500 }));
    const client = makeClient(fetchMock);

    await expect(client.mutate("POST /customers/$id/screen", { id: "c_1" })).rejects.toMatchObject({
      kind: "HttpError",
      status: 500,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("dehydrates and hydrates cached query data", async () => {
    const fetchMock = vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify({ id: "c_1" }), {
          headers: { "content-type": "application/json" },
        }),
    );
    const client = makeClient(fetchMock);
    await client.query("GET /customers/$id", { id: "c_1" });

    const next = makeClient(fetchMock);
    next.hydrate(client.dehydrate());

    expect(next.getData("GET /customers/$id", { id: "c_1" })).toEqual({ id: "c_1" });
  });
});
