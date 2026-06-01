import { describe, expect, it, vi } from "vitest";

import { createRouteKeyClient } from "../src/client.js";
import type { CausewayClient, RouteDescriptor, RouteMeta } from "../src/types.js";

const ROUTES: Record<string, RouteDescriptor> = {
  getUser: {
    method: "GET",
    path: "/users/{user_id}",
    routeKey: "GET /users/$user_id",
    params: [{ name: "userId", alias: "user_id", in: "path" }],
  },
  createPost: {
    method: "POST",
    path: "/posts",
    routeKey: "POST /posts",
    params: [{ name: "data", alias: "data", in: "body" }],
  },
  search: {
    method: "GET",
    path: "/search",
    routeKey: "GET /search",
    params: [
      { name: "q", alias: "q", in: "query" },
      { name: "limit", alias: "limit", in: "query" },
    ],
  },
  login: {
    method: "POST",
    path: "/login",
    routeKey: "POST /login",
    params: [
      { name: "email", alias: "email", in: "body", embed: true },
      { name: "password", alias: "password", in: "body", embed: true },
    ],
  },
  orphan: {
    method: "GET",
    path: "/orphan",
    routeKey: "GET /orphan",
    result: true,
  },
  createVersion: {
    method: "POST",
    path: "/versions",
    routeKey: "POST /versions",
    params: [{ name: "body", alias: "body", in: "body" }],
    opaqueRequestPaths: ["definition"],
    opaqueResponsePaths: ["definition"],
  },
  showVersion: {
    method: "GET",
    path: "/versions/{id}",
    routeKey: "GET /versions/$id",
    params: [{ name: "id", alias: "id", in: "path" }],
    result: true,
    opaqueResponsePaths: ["data.definition"],
  },
};

const ROUTE_META: RouteMeta[] = Object.entries(ROUTES).map(([id, route]) => ({
  id,
  routeKey: route.routeKey,
  method: route.method,
  path: route.path,
  ...((route.params?.length ?? 0) > 0 ? { hasArgs: true } : {}),
  ...(route.streams ? { streams: true } : {}),
}));

function makeFetch(responder: () => Response) {
  return vi.fn<typeof fetch>(async () => responder());
}

function createTestClient(config: {
  baseUrl?: string;
  fetch?: typeof fetch;
  headers?: Record<string, string>;
  loadRoute?: (id: string) => RouteDescriptor | Promise<RouteDescriptor>;
}): CausewayClient {
  return createRouteKeyClient({
    ...config,
    routeMeta: ROUTE_META,
    loadRoute:
      config.loadRoute ??
      ((id) => {
        const route = ROUTES[id];
        if (route === undefined) throw new Error(id);
        return route;
      }),
  });
}

describe("createRouteKeyClient", () => {
  it("rejects unknown route keys", async () => {
    const client = createTestClient({ fetch: makeFetch(() => new Response()) });

    await expect(client.query("GET /nope")).rejects.toThrow(/Unknown causeway route key/);
  });

  it("loads route descriptors lazily on first use", async () => {
    const fetchMock = makeFetch(
      () =>
        new Response(JSON.stringify({ id: 1 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    const loadRoute = vi.fn(async (id: string) => {
      const route = ROUTES[id];
      if (route === undefined) throw new Error(id);
      return route;
    });
    const client = createTestClient({
      baseUrl: "http://api.test",
      fetch: fetchMock,
      loadRoute,
    });

    expect(loadRoute).not.toHaveBeenCalled();
    await client.query("GET /users/$user_id", { userId: 42 });
    await client.query("GET /users/$user_id", { userId: 43 });

    expect(loadRoute).toHaveBeenCalledTimes(1);
    expect(loadRoute).toHaveBeenCalledWith("getUser");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://api.test/users/42");
    expect(fetchMock.mock.calls[1]?.[0]).toBe("http://api.test/users/43");
  });

  it("substitutes path params via alias", async () => {
    const fetchMock = makeFetch(
      () =>
        new Response(JSON.stringify({ id: 1 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    const client = createTestClient({
      baseUrl: "http://api.test",
      fetch: fetchMock,
    });

    const result = await client.query("GET /users/$user_id", { userId: 42 });

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("http://api.test/users/42");
    expect(init?.method).toBe("GET");
    expect(result).toEqual({ id: 1 });
  });

  it("enforces query and mutation route kinds", async () => {
    const fetchMock = makeFetch(() => new Response(JSON.stringify({ ok: true })));
    const client = createTestClient({ fetch: fetchMock });

    await expect(client.query("POST /posts", { data: {} })).rejects.toThrow(
      /query routes must be GET/,
    );
    await expect(client.mutate("GET /users/$user_id", { userId: 1 })).rejects.toThrow(
      /mutation routes must not be GET/,
    );
  });

  it("converts body keys camelCase → snake_case on the wire", async () => {
    const fetchMock = makeFetch(
      () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    const client = createTestClient({
      baseUrl: "http://api.test",
      fetch: fetchMock,
    });

    await client.mutate("POST /posts", { data: { titleText: "hi", bodyText: "world" } });

    const [, init] = fetchMock.mock.calls[0]!;
    expect(JSON.parse(init?.body as string)).toEqual({
      title_text: "hi",
      body_text: "world",
    });
  });

  it("embeds multiple body params under their snake_case aliases", async () => {
    const fetchMock = makeFetch(
      () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    const client = createTestClient({
      baseUrl: "http://api.test",
      fetch: fetchMock,
    });

    await client.mutate("POST /login", { email: "a@b.com", password: "secret" });

    const [, init] = fetchMock.mock.calls[0]!;
    expect(JSON.parse(init?.body as string)).toEqual({
      email: "a@b.com",
      password: "secret",
    });
  });

  it("encodes query params", async () => {
    const fetchMock = makeFetch(
      () =>
        new Response(JSON.stringify({ q: "hi" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    const client = createTestClient({
      baseUrl: "http://api.test",
      fetch: fetchMock,
    });

    await client.query("GET /search", { q: "hi", limit: 5 });

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toBe("http://api.test/search?q=hi&limit=5");
  });

  it("omits nullish query params", async () => {
    const fetchMock = makeFetch(
      () =>
        new Response(JSON.stringify({ q: "hi" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    const client = createTestClient({
      baseUrl: "http://api.test",
      fetch: fetchMock,
    });

    await client.query("GET /search", { q: null, limit: undefined });

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toBe("http://api.test/search");
  });

  it("camelCases response keys for snake_case payloads", async () => {
    const fetchMock = makeFetch(
      () =>
        new Response(JSON.stringify({ user_id: 7, full_name: "Ada" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    const client = createTestClient({ fetch: fetchMock });
    const got = await client.query("GET /users/$user_id", { userId: 7 });
    expect(got).toEqual({ userId: 7, fullName: "Ada" });
  });

  it("preserves opaque request-body subtrees verbatim", async () => {
    const fetchMock = makeFetch(
      () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    const client = createTestClient({ fetch: fetchMock });

    await client.mutate("POST /versions", {
      body: {
        changeNote: "init",
        definition: {
          trigger_type: "transaction-created",
          actions: { add_score: 25, create_alert: { severity: "high" } },
        },
      },
    });

    const [, init] = fetchMock.mock.calls[0]!;
    expect(JSON.parse(init?.body as string)).toEqual({
      change_note: "init",
      definition: {
        trigger_type: "transaction-created",
        actions: { add_score: 25, create_alert: { severity: "high" } },
      },
    });
  });

  it("preserves opaque response subtrees verbatim", async () => {
    const fetchMock = makeFetch(
      () =>
        new Response(
          JSON.stringify({
            id: "v1",
            change_note: "init",
            definition: {
              trigger_type: "transaction-created",
              actions: { add_score: 25, create_alert: { severity: "high" } },
            },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    );
    const client = createTestClient({ fetch: fetchMock });
    const got = await client.mutate("POST /versions", { body: { definition: {} } });

    expect(got).toEqual({
      id: "v1",
      changeNote: "init",
      definition: {
        trigger_type: "transaction-created",
        actions: { add_score: 25, create_alert: { severity: "high" } },
      },
    });
  });

  it("unwraps Result.ok data while preserving opaque paths under data", async () => {
    const fetchMock = makeFetch(
      () =>
        new Response(
          JSON.stringify({
            ok: true,
            data: {
              id: "v1",
              definition: { trigger_type: "transaction-created" },
            },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    );
    const client = createTestClient({ fetch: fetchMock });
    const got = await client.query("GET /versions/$id", { id: "v1" });

    expect(got).toEqual({
      id: "v1",
      definition: { trigger_type: "transaction-created" },
    });
  });

  it("throws CausewayError for typed Result errors", async () => {
    const envelope = { ok: false, error: { kind: "PostNotFound", post_id: 7 } };
    const fetchMock = makeFetch(
      () =>
        new Response(JSON.stringify(envelope), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    const client = createTestClient({ fetch: fetchMock });

    await expect(client.query("GET /orphan")).rejects.toMatchObject({
      kind: "PostNotFound",
      postId: 7,
    });
  });

  it("throws a CausewayError on non-2xx", async () => {
    const fetchMock = makeFetch(() => new Response("boom", { status: 500 }));
    const client = createTestClient({ fetch: fetchMock });

    await expect(client.query("GET /users/$user_id", { userId: 1 })).rejects.toMatchObject({
      name: "CausewayError",
      kind: "HttpError",
      status: 500,
      message: "HTTP 500",
    });
  });

  it("unwraps typed-error envelopes from 4xx responses as CausewayError", async () => {
    const envelope = {
      ok: false,
      error: { kind: "PostNotFound", post_id: 7, message: "post 7 missing" },
    };
    const fetchMock = makeFetch(
      () =>
        new Response(JSON.stringify(envelope), {
          status: 404,
          headers: { "content-type": "application/json" },
        }),
    );
    const client = createTestClient({ fetch: fetchMock });

    try {
      await client.query("GET /users/$user_id", { userId: 7 });
      throw new Error("expected rejection");
    } catch (error) {
      expect(error).toBeInstanceOf(Error);
      expect(error).toMatchObject({
        kind: "PostNotFound",
        message: "post 7 missing",
        name: "CausewayError",
        postId: 7,
        status: 404,
      });
    }
  });
});
