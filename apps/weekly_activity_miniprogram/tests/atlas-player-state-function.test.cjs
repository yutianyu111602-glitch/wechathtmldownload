const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const functionPath = path.resolve(__dirname, "../cloudfunctions/atlasPlayerState/index.js");
const atlasPlayerState = require(functionPath);

function createFakeDb(seed = []) {
  const rows = seed.slice();
  const writes = [];
  const collection = {
    where(query) {
      return {
        limit() {
          return {
            async get() {
              return {
                data: rows.filter((row) => (
                  row.schemaVersion === query.schemaVersion && row.ownerKey === query.ownerKey
                )).slice(0, 1),
              };
            },
          };
        },
      };
    },
    doc(id) {
      return {
        async update(payload) {
          writes.push({ type: "update", id, payload });
          const index = rows.findIndex((row) => row._id === id);
          if (index >= 0) rows[index] = { ...rows[index], ...payload.data };
          return { updated: 1 };
        },
      };
    },
    async add(payload) {
      const id = `doc-${rows.length + 1}`;
      writes.push({ type: "add", id, payload });
      rows.push({ _id: id, ...payload.data });
      return { _id: id };
    },
  };
  return {
    db: {
      collection(name) {
        assert.equal(name, "atlas_player_state");
        return collection;
      },
    },
    rows,
    writes,
  };
}

test("atlas player state function saves and loads by owner key", async () => {
  const fake = createFakeDb();
  const context = { OPENID: "openid-user-1" };

  const saved = await atlasPlayerState.__test.handle({
    action: "save",
    playerKey: "atlas-local-key",
    state: {
      fuel: 77,
      xp: 33,
      objectiveKey: "archive",
      objectiveProgress: 1,
      objectiveClaims: 3,
      resupplies: 2,
    },
    meta: { action: "scan", updatedAt: "2026-06-13T00:00:00.000Z" },
  }, context, { db: fake.db });

  assert.equal(saved.ok, true);
  assert.equal(saved.source, "cloud-function");
  assert.equal(fake.writes.length, 1);
  assert.equal(fake.rows[0].lastAction, "scan");
  assert.equal(fake.rows[0].state.fuel, 77);
  assert.equal(fake.rows[0].state.objectiveKey, "archive");
  assert.equal(fake.rows[0].state.objectiveProgress, 1);
  assert.equal(fake.rows[0].state.resupplies, 2);
  assert.ok(fake.rows[0].ownerKey.startsWith("wx_"));
  assert.notEqual(fake.rows[0].ownerKey, "openid-user-1");

  const loaded = await atlasPlayerState.__test.handle({
    action: "load",
    playerKey: "atlas-local-key",
  }, context, { db: fake.db });

  assert.equal(loaded.ok, true);
  assert.equal(loaded.source, "cloud-function");
  assert.equal(loaded.docId, saved.docId);
  assert.equal(loaded.state.xp, 33);
  assert.equal(loaded.state.objectiveKey, "archive");
});

test("atlas player state function does not load another user's row", async () => {
  const ownerKey = atlasPlayerState.__test.ownerKeyFor({ playerKey: "same-local-key" }, { OPENID: "user-a" });
  const fake = createFakeDb([{
    _id: "doc-a",
    schemaVersion: "atlas_universe_game_state.v1",
    ownerKey,
    state: { fuel: 10 },
  }]);

  const loaded = await atlasPlayerState.__test.handle({
    action: "load",
    playerKey: "same-local-key",
  }, { OPENID: "user-b" }, { db: fake.db });

  assert.equal(loaded.ok, true);
  assert.equal(loaded.source, "cloud-function-empty");
  assert.equal(loaded.state, null);
});

test("atlas player state function supports local player key when openid is absent", async () => {
  const fake = createFakeDb();
  const saved = await atlasPlayerState.__test.handle({
    action: "save",
    playerKey: "atlas-local-only",
    state: { credits: 5 },
  }, {}, { db: fake.db });

  assert.equal(saved.ok, true);
  assert.ok(fake.rows[0].ownerKey.startsWith("local_"));
  assert.equal(fake.rows[0].state.credits, 5);
});
