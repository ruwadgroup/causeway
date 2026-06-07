# minimal-crud

A working CRUD endpoint set in ~80 lines. One resource (`users`), in-memory
storage, file-based routing, typed errors, msgspec request/response models.

## Layout

```
minimal-crud/
├── pyproject.toml
├── causeway.toml
├── app/
│   ├── __init__.py
│   ├── app.py            # `app = create_app("app/routes")`
│   ├── store.py          # in-memory dict-backed user store
│   └── routes/
│       └── users/
│           ├── index.py  # GET /users · POST /users
│           └── $id.py   # GET/PATCH/DELETE /users/{id}
└── tests/
    └── test_users.py
```

## Run

```bash
cd examples/minimal-crud
uv sync
uv run uvicorn app.app:app --reload
```

## Exercise it

```bash
curl http://127.0.0.1:8000/users
# → []

curl -X POST http://127.0.0.1:8000/users \
  -H 'content-type: application/json' \
  -d '{"name":"ada","email":"a@x"}'
# → {"ok":true,"data":{"id":1,"name":"ada","email":"a@x"}}

curl http://127.0.0.1:8000/users/1
# → {"ok":true,"data":{"id":1,"name":"ada","email":"a@x"}}

curl -X PATCH http://127.0.0.1:8000/users/1 \
  -H 'content-type: application/json' \
  -d '{"name":"grace"}'

curl -X DELETE http://127.0.0.1:8000/users/1
# → {"ok":true,"data":{"deleted":true}}

curl http://127.0.0.1:8000/users/1
# → {"ok":false,"error":{"kind":"NotFound","message":"user 1 not found","detail":{}}}
```

## Tests

```bash
uv run pytest
```

## What's interesting

- **One file per HTTP shape.** `index.py` owns `GET`/`POST` on the
  collection; `$id.py` owns the item.
- **Typed errors flow to the client.** `@raises(NotFound)` /
  `@raises(BadRequest)` tell Causeway's codegen that the generated TS
  client should expose those branches in its `Result<T, E>` union. The
  HTTP response is always 200; success/failure lives inside the envelope
  (`{"ok": true, "data": ...}` vs `{"ok": false, "error": {...}}`).
  Handlers without `@raises` return the bare value.
- **No request-model boilerplate.** The handler signature is the wire
  schema. `data: NewUser` validates the body; `id: int` parses the path.
