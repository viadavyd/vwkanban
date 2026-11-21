import { expect, test } from "@playwright/test";
import { ORIGIN, STATE } from "./helpers";

// Plan §7 on a 500-card board, with a 4× CPU throttle (CDP):
//   keypress → next animation frame, p95 < 50 ms over 200 presses of j/k/h/l/Space
//   holding j at 30 Hz: no long task > 50 ms
//   interactive (all cards rendered) < 1 s
// Report-only unless VWK_PERF_ENFORCE=1 (shared CI runners are noisy).
test.use({ storageState: STATE });

const ENFORCE = process.env.VWK_PERF_ENFORCE === "1";
const CARDS = 500;

const p95 = (xs: number[]) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length * 0.95)];

test("500-card board navigation", async ({ page }) => {
  test.setTimeout(240_000);
  const api = page.request;
  const headers = { Origin: ORIGIN };

  const board = await (
    await api.post("/api/boards", { data: { title: `perf ${Date.now()}` }, headers })
  ).json();
  try {
    const detail = await (await api.get(`/api/boards/${board.id}`)).json();
    const statuses: { id: string }[] = detail.statuses;
    for (let i = 0; i < CARDS; i += 25) {
      // 25 at a time; each op is its own transaction on the server.
      await Promise.all(
        Array.from({ length: Math.min(25, CARDS - i) }, (_, k) =>
          api.post(`/api/boards/${board.id}/ops`, {
            headers,
            data: {
              client_id: crypto.randomUUID(),
              op: {
                op_id: crypto.randomUUID(),
                kind: "card.create",
                base_seq: 0,
                data: {
                  id: crypto.randomUUID(),
                  status_id: statuses[(i + k) % statuses.length].id,
                  title: `Card ${i + k} with a typical length title`,
                  tags: ["ui", `t${(i + k) % 7}`],
                },
              },
            },
          }),
        ),
      );
    }

    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });

    // Interactive: navigation start → every card rendered.
    await page.goto(`/b/${board.id}`);
    await expect(page.locator("[data-card]")).toHaveCount(CARDS);
    const interactive = await page.evaluate(() => performance.now());

    // keydown → next rAF, measured in the page.
    await page.evaluate(() => {
      const w = window as unknown as { __lat: number[] };
      w.__lat = [];
      window.addEventListener(
        "keydown",
        (e) => {
          const t0 = e.timeStamp;
          requestAnimationFrame(() => w.__lat.push(performance.now() - t0));
        },
        { capture: true },
      );
    });
    const keys = ["j", "j", "j", "l", "j", "Space", "k", "h", "j", "Space"];
    for (let i = 0; i < 200; i++) await page.keyboard.press(keys[i % keys.length]);
    await page.waitForTimeout(200);
    const lat: number[] = await page.evaluate(() => (window as any).__lat);

    // Holding j at 30 Hz with a long-task observer.
    await page.evaluate(() => {
      const w = window as unknown as { __long: number[] };
      w.__long = [];
      new PerformanceObserver((list) => {
        for (const e of list.getEntries()) w.__long.push(e.duration);
      }).observe({ type: "longtask" });
    });
    for (let i = 0; i < 90; i++) {
      await page.keyboard.press(i < 60 ? "j" : "k");
      await page.waitForTimeout(33);
    }
    await page.waitForTimeout(200);
    const long: number[] = await page.evaluate(() => (window as any).__long);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });

    const report = {
      cards: CARDS,
      cpuThrottle: 4,
      interactiveMs: Math.round(interactive),
      keyToFrameP95Ms: Math.round(p95(lat) * 10) / 10,
      presses: lat.length,
      longTasksOver50Ms: long.filter((d) => d > 50).map(Math.round),
    };
    console.log(`perf: ${JSON.stringify(report)}`);
    test.info().annotations.push({ type: "perf", description: JSON.stringify(report) });
    expect(lat.length).toBe(200);
    if (ENFORCE) {
      expect(report.keyToFrameP95Ms).toBeLessThan(50);
      expect(report.longTasksOver50Ms).toEqual([]);
      expect(report.interactiveMs).toBeLessThan(1000);
    }
  } finally {
    await api.delete(`/api/boards/${board.id}`, { headers });
  }
});
