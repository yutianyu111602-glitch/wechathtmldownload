const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");

function pageHarness(filename, requestApi, options = {}) {
  let pageConfig = null;
  const wxBase = {
    getStorageSync() {
      return "";
    },
    setStorageSync() {},
    navigateBack() {},
    navigateTo() {},
    setClipboardData(options) {
      if (options.success) options.success();
    },
    showToast() {},
  };
  const sandbox = {
    console,
    Page(config) {
      pageConfig = config;
    },
    require(request) {
      if (request.endsWith("/api")) return { requestApi };
      if (request.endsWith("/clubOverviews")) {
        return {
          getClubOverviewsForVenue: () => [],
        };
      }
      if (request.endsWith("/format")) {
        return {
          compactItem: (item) => item,
          atlasEventToWeeklyItem: (event, options = {}) => ({
            id: event.eventId || "atlas-event",
            event_id: event.eventId || "atlas-event",
            displayTitle: event.title || "",
            title: event.title || "",
            dateLabel: event.date || "",
            event_date_start: event.date || "",
            lineupLabel: event.djName || "",
            venueLabel: options.venueName || event.venueName || "",
            sourceHash: event.sourceHash || event.sourceRefId || "",
            sourceRefId: event.sourceRefId || "",
            source_title: event.sourceTitle || "",
            sourceTitle: event.sourceTitle || "",
            source_account_name: event.sourceAccountName || "",
            sourceAccountName: event.sourceAccountName || "",
            source_published_at: event.sourcePublishedAt || "",
            sourcePublishedAt: event.sourcePublishedAt || "",
            isAtlasEvent: true,
          }),
        };
      }
      if (request.endsWith("/i18n")) {
        return {
          applyLanguageChrome: () => {},
          localizeItems: (items) => items,
          localizedSourceArticles: (items) => items,
          normalizeLang: (value) => (value === "en" ? "en" : "zh"),
          text: () => ({
            addressCopied: "地址已复制",
            loadFailed: "加载失败",
            relatedEvents: "相关活动",
            weeklyEvents: "本周活动",
          }),
        };
      }
      if (request.endsWith("/sourceAction")) {
        return {
          openSourceByHash: (hash, lang) => {
            if (options.sourceCalls) options.sourceCalls.push({ hash, lang });
          },
          openSourceUrl: () => false,
        };
      }
      if (request.endsWith("/sourceArticles")) return require(path.join(root, "utils", "sourceArticles.js"));
      if (request.endsWith("/atlasContract")) return require(path.join(root, "utils", "atlasContract.js"));
      if (request.endsWith("/share")) {
        return {
          buildNamedPageShare: () => ({}),
          buildNamedPageTimeline: () => ({}),
          enableShareMenu: () => {},
        };
      }
      throw new Error(`unexpected require ${request}`);
    },
    wx: { ...wxBase, ...(options.wx || {}) },
  };
  const code = fs.readFileSync(filename, "utf8");
  vm.runInNewContext(code, sandbox, { filename });
  return pageConfig;
}

function bindPage(config, data = {}) {
  return {
    ...config,
    data: { ...(config.data || {}), t: { loadFailed: "加载失败" }, ...data },
    setData(next) {
      this.data = { ...this.data, ...next };
    },
  };
}

test("venue profile still resolves by club name when the carried organizer key is stale", async () => {
  const filename = path.join(root, "pages", "venue", "venue.js");
  const pageConfig = pageHarness(filename, async () => ({
    items: [
      {
        id: "evt-1",
        venueLabel: "wigwam",
        cardLocationLabel: "wigwam",
        organizerKey: "fresh-wigwam-key",
        displayTitle: "Weekly Listening",
        dateLabel: "2026-05-26",
        lineupLabel: "A / B",
        sourceArticles: [],
      },
    ],
    page: { nextCursor: null },
  }));
  const page = bindPage(pageConfig);
  page.name = "wigwam";
  page.key = "stale-wigwam-key";
  page.lang = "zh";

  await pageConfig.loadVenue.call(page);

  // Name resolution is the point here; the 2026-05-26 show is past so it lands
  // in pastEvents after the upcoming/past split.
  const resolved = [...page.data.events, ...page.data.pastEvents];
  assert.equal(resolved.length, 1);
  assert.equal(resolved[0].id, "evt-1");
});

test("artist profile loads recent performance history instead of current-only events", async () => {
  const filename = path.join(root, "pages", "artist", "artist.js");
  const calls = [];
  const pageConfig = pageHarness(filename, async (apiPath, params) => {
    calls.push({ path: apiPath, params: params || {} });
    if (apiPath.includes("/atlas/artist")) return { found: false };
    return {
      items: params && params.lookbackDays
        ? [
            {
              id: "hist-1",
              lineupItems: ["DJ Spell"],
              displayTitle: "Archive Night",
              dateLabel: "2026-05-20",
              cardLocationLabel: "wigwam",
            },
          ]
        : [],
      page: { nextCursor: null },
    };
  });
  const page = bindPage(pageConfig);
  page.name = "DJ Spell";
  page.lang = "zh";

  await pageConfig.loadArtist.call(page);

  const currentCalls = calls.filter((call) => call.path === "/api/v1/weekly/current");
  assert.equal(currentCalls.length, 1);
  assert.equal(currentCalls.some((call) => call.params.lookbackDays === 45), true);
  assert.equal(page.data.events.length, 1);
  assert.equal(page.data.events[0].id, "hist-1");
});

test("artist profile keeps Atlas collaborators and frequent venues when weekly list is empty", async () => {
  const filename = path.join(root, "pages", "artist", "artist.js");
  const pageConfig = pageHarness(filename, async (apiPath) => {
    if (apiPath.includes("/atlas/dj-profile") || apiPath.includes("/atlas/artist")) {
      return {
        found: true,
        profile: { displayName: "Ozone", eventCount: 20, venueCount: 2 },
        events: [
          {
            eventId: "atlas-1",
            title: "Archive Night",
            date: "2025-12-20",
            venueName: "OIL",
            city: "深圳",
            sourceRefId: "src:archive-1",
            sourceHash: "hash-archive-1",
          },
        ],
        collaborators: [{ djId: "dj:b", displayName: "DJ B", sameEventCount: 3 }],
        venues: [{ venueId: "venue:oil", venueName: "OIL", eventCount: 5 }],
      };
    }
    return { items: [], page: { nextCursor: null } };
  });
  const page = bindPage(pageConfig);
  page.name = "Ozone";
  page.lang = "zh";

  await pageConfig.loadArtist.call(page);

  assert.equal(page.data.events.length, 0);
  assert.equal(page.data.atlasEvents.length, 1);
  assert.equal(page.data.atlasCollaborators.length, 1);
  assert.equal(page.data.atlasCollaborators[0].sameEventCount, 3);
  assert.equal(page.data.atlasVenues.length, 1);
  assert.equal(page.data.atlasVenues[0].venueName, "OIL");
});

test("venue profile restores Atlas historical source articles", async () => {
  const filename = path.join(root, "pages", "venue", "venue.js");
  const pageConfig = pageHarness(filename, async (apiPath) => {
    if (apiPath.includes("/atlas/venue")) {
      return {
        found: true,
        profile: { displayName: "Club A" },
        residentDJs: [],
        events: [
          {
            eventId: "atlas-event-1",
            title: "Archive Night",
            date: "2025-12-20",
            djName: "DJ A",
            sourceRefId: "activity_src:archive-1",
            sourceHash: "hash-archive-1",
            sourceTitle: "Archive source title",
            sourceAccountName: "Club A",
            sourcePublishedAt: "2025-12-01",
          },
        ],
      };
    }
    return { items: [], page: { nextCursor: null } };
  });
  const page = bindPage(pageConfig);
  page.name = "Club A";
  page.key = "";
  page.lang = "zh";

  await pageConfig.loadVenue.call(page);

  // Historical atlas event is past -> pastEvents bucket.
  assert.equal([...page.data.events, ...page.data.pastEvents].some((event) => event.id === "atlas-event-1"), true);
  assert.equal(page.data.sourceArticles.length, 1);
  assert.equal(page.data.sourceArticles[0].hash, "activity_src:archive-1");
  assert.equal(page.data.sourceArticles[0].title, "Archive source title");
});

test("venue profile keeps Atlas resident DJs when weekly list is empty", async () => {
  const filename = path.join(root, "pages", "venue", "venue.js");
  const pageConfig = pageHarness(filename, async (apiPath) => {
    if (apiPath.includes("/atlas/venue")) {
      return {
        found: true,
        profile: { displayName: "OIL" },
        events: [
          {
            eventId: "atlas-event-1",
            title: "Archive Night",
            date: "2025-12-20",
            djName: "Ozone",
            sourceRefId: "src:archive-1",
            sourceHash: "hash-archive-1",
          },
        ],
        residentDJs: [{ djId: "dj:ozone", displayName: "Ozone", eventCount: 8 }],
      };
    }
    return { items: [], page: { nextCursor: null } };
  });
  const page = bindPage(pageConfig);
  page.name = "OIL";
  page.key = "";
  page.lang = "zh";

  await pageConfig.loadVenue.call(page);

  // Weekly list empty; the lone atlas show (2025-12-20) is past -> pastEvents.
  assert.equal([...page.data.events, ...page.data.pastEvents].length, 1);
  assert.equal(page.data.atlasResidentDJs.length, 1);
  assert.equal(page.data.atlasResidentDJs[0].eventCount, 8);
});

test("venue Atlas historical event taps open source evidence instead of weekly detail", () => {
  const filename = path.join(root, "pages", "venue", "venue.js");
  const sourceCalls = [];
  const navCalls = [];
  const pageConfig = pageHarness(filename, async () => ({ items: [], page: { nextCursor: null } }), {
    sourceCalls,
    wx: {
      navigateTo(options) {
        navCalls.push(options.url);
      },
    },
  });
  const page = bindPage(pageConfig);
  page.lang = "zh";

  pageConfig.openDetail.call(page, {
    currentTarget: {
      dataset: {
        id: "event:archive",
        isAtlas: "true",
        sourceHash: "activity_src:archive-1",
      },
    },
  });

  assert.deepEqual(sourceCalls, [{ hash: "activity_src:archive-1", lang: "zh" }]);
  assert.deepEqual(navCalls, []);
});

test("artist Atlas history rows open their source evidence", () => {
  const filename = path.join(root, "pages", "artist", "artist.js");
  const sourceCalls = [];
  const pageConfig = pageHarness(filename, async () => ({ items: [], page: { nextCursor: null } }), { sourceCalls });
  const page = bindPage(pageConfig);
  page.lang = "zh";

  pageConfig.openAtlasEventSource.call(page, {
    currentTarget: {
      dataset: {
        sourceHash: "activity_src:artist-archive",
      },
    },
  });

  assert.deepEqual(sourceCalls, [{ hash: "activity_src:artist-archive", lang: "zh" }]);
});

test("venue address tap opens cached destination without requesting user location", async () => {
  const filename = path.join(root, "pages", "venue", "venue.js");
  let getLocationCalled = false;
  let openLocationPayload = null;
  const pageConfig = pageHarness(filename, async () => ({ items: [], page: { nextCursor: null } }), {
    wx: {
      getLocation() {
        getLocationCalled = true;
      },
      openLocation(payload) {
        openLocationPayload = payload;
      },
    },
  });
  const page = bindPage(pageConfig, {
    address: "上海市长宁区幸福路298号",
    mapLocation: { latitude: 31.208071, longitude: 121.431325 },
    mapLocationName: "EXIT Shanghai",
  });

  pageConfig.handleAddressTap.call(page);

  assert.equal(getLocationCalled, false);
  assert.equal(openLocationPayload.latitude, 31.208071);
  assert.equal(openLocationPayload.longitude, 121.431325);
});
