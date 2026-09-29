const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

test("formatting stays identical and selecting stocks preserves table nodes", () => {
  const elements = new Map();
  const rows = ["KR:005930", "KR:000660", "KR:005930"].map((id) => ({
    dataset: { id }, selected: false,
    classList: { toggle(_name, selected) { this.owner.selected = selected; } },
  }));
  rows.forEach((row) => { row.classList.owner = row; });
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, { innerHTML: "original", addEventListener() {} });
      return elements.get(id);
    },
    querySelectorAll: (selector) => selector === "tr[data-id]" ? rows : [],
  };
  let formatsCreated = 0;
  function NumberFormat(...args) { formatsCreated++; return new Intl.NumberFormat(...args); }
  const context = vm.createContext({ document, Intl: { NumberFormat }, window: { addEventListener() {} },
    fetch: () => new Promise(() => {}) });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../site/app.js"), "utf8"), context);
  for (const digits of [0, 1, 2, 4]) {
    for (const value of [-1234.56789, 0, 1234.56789, "12.345", Infinity]) {
      assert.equal(context.fmt(value, digits), Number(value).toLocaleString(undefined, { maximumFractionDigits: digits }));
    }
  }
  for (const value of [null, undefined, NaN]) assert.equal(context.fmt(value), "-");
  for (let i = 0; i < 1000; i++) context.fmt(i, 2);
  assert.equal(formatsCreated, 5);
  assert.equal(context.compact(1234567), new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 2 }).format(1234567));
  context.drawSpark = () => {};
  const row = { id: "KR:005930", country: "KR", returns: {}, components: {} };
  context.selectStock(row);
  assert.deepEqual(rows.map((r) => r.selected), [true, false, true]);
  context.selectStock({ ...row, id: "KR:000660" });
  assert.deepEqual(rows.map((r) => r.selected), [false, true, false]);
  for (const id of ["rankBody", "krTopBody", "recommendationBody"]) {
    assert.equal(elements.get(id).innerHTML, "original");
  }
});

test("ask endpoint retains input validation and offline fallback", async () => {
  const { handler } = require("../netlify/functions/ask.js");
  assert.equal((await handler({ httpMethod: "GET" })).statusCode, 405);
  assert.equal((await handler({ httpMethod: "POST", body: "{" })).statusCode, 400);
  assert.equal((await handler({ httpMethod: "POST", body: "{}" })).statusCode, 400);
  const previous = process.env.OPENAI_API_KEY;
  delete process.env.OPENAI_API_KEY;
  try {
    const response = await handler({ httpMethod: "POST", body: '{"question":"요약"}', headers: {} });
    assert.equal(response.statusCode, 200);
    assert.equal(JSON.parse(response.body).mode, "local");
  } finally {
    if (previous !== undefined) process.env.OPENAI_API_KEY = previous;
  }
});

test("public Q&A never calls paid APIs even when an API key exists", async () => {
  const { handler } = require("../netlify/functions/ask.js");
  const previousKey = process.env.OPENAI_API_KEY;
  const previousFetch = global.fetch;
  process.env.OPENAI_API_KEY = "synthetic-test-value";
  global.fetch = () => { throw new Error("Network must not be used"); };
  try {
    const response = await handler({ httpMethod: "POST", body: JSON.stringify({question: "요약"}), headers: {host: "untrusted.invalid"} });
    assert.equal(response.statusCode, 200);
    assert.equal(JSON.parse(response.body).mode, "local");
    assert.match(JSON.parse(response.body).answer, /합성/);
    for (const question of [null, 123, {}, " ", "a".repeat(2001)]) {
      assert.equal((await handler({ httpMethod: "POST", body: JSON.stringify({question}) })).statusCode, 400);
    }
    assert.equal((await handler({ httpMethod: "POST", body: "a".repeat(8193) })).statusCode, 413);
  } finally {
    global.fetch = previousFetch;
    if (previousKey === undefined) delete process.env.OPENAI_API_KEY;
    else process.env.OPENAI_API_KEY = previousKey;
  }
});

test("synthetic dashboard boots, filters and answers without external calls", async () => {
  const elements = new Map();
  const drawing = new Proxy({}, { get: () => () => {} });
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, {
        value: id === "marketFilter" ? "ALL" : id === "minScore" ? "0" : "",
        textContent: "", innerHTML: "", addEventListener() {},
        getBoundingClientRect: () => ({width: 400}), getContext: () => drawing,
      });
      return elements.get(id);
    },
    querySelectorAll: () => [],
  };
  const requests = [];
  const context = vm.createContext({document, Intl, window: {devicePixelRatio: 1, addEventListener() {}},
    fetch: async (url) => {
      requests.push(url);
      assert.ok(["./demo-data/scores.json", "./demo-data/research/latest.json"].includes(url));
      return {ok: true, json: async () => JSON.parse(fs.readFileSync(path.join(__dirname, "../site", url), "utf8"))};
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../site/app.js"), "utf8"), context);
  await new Promise(setImmediate);
  assert.match(elements.get("resultCount").textContent, /^6 matches/);
  assert.match(elements.get("researchSummary").textContent, /합성/);
  elements.get("searchInput").value = "DEMO01";
  context.applyFilters();
  assert.match(elements.get("resultCount").textContent, /^1 matches/);
  assert.equal(elements.get("detailName").textContent, "가상테크");
  context.askResearch("어떤 이슈가 있나요?");
  assert.match(elements.get("askAnswer").textContent, /가상 산업/);
  assert.equal(requests.length, 2);
});
