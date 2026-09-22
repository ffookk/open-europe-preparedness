"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const {pathToFileURL} = require("node:url");
const {spawnSync} = require("node:child_process");
const engines = require("playwright");
let scenario = "setup";

function python(request) {
  const result = spawnSync("python3", [path.join(__dirname, "fixtures.py")], {
    encoding: "utf8", input: JSON.stringify(request), maxBuffer: 4 * 1024 * 1024, timeout: 15000
  });
  assert.equal(result.status, 0, "Fictional fixture generation or Python artifact verification failed.");
  return JSON.parse(result.stdout);
}

async function run(engine) {
  const directory = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), "preparedness-browser-")));
  let browser;
  let checks = 0;
  const check = (condition, message) => { assert.ok(condition, message); checks++; };
  try {
    const pages = python({mode: "generate"});
    await fs.writeFile(path.join(directory, "catalog.html"), pages.catalog_html, {flag: "wx", mode: 0o600});
    await fs.writeFile(path.join(directory, "maintenance.html"), pages.maintenance_html, {flag: "wx", mode: 0o600});
    browser = await engines[engine].launch({headless: true});
    for (const name of ["catalog", "maintenance"]) {
      scenario = engine + ": " + name;
      const context = await browser.newContext({offline: true, acceptDownloads: true, viewport: {width: 1365, height: 900}});
      const page = await context.newPage();
      const requests = [], errors = [];
      page.on("request", request => {if (!request.url().startsWith("file:")) requests.push(true);});
      page.on("pageerror", () => errors.push(true));
      page.on("dialog", async dialog => {errors.push(true); await dialog.dismiss();});
      await context.route("**/*", route => route.request().url().startsWith("file:") ? route.continue() : route.abort());
      const cards = page.locator("#records details.card");
      const count = async expected => {
        await page.waitForFunction(value => document.querySelectorAll("#records details.card").length === value, expected);
        check(await cards.count() === expected, "Expected visible record count.");
      };
      const download = async (button, filename, suggested) => {
        const pending = page.waitForEvent("download");
        await page.locator(button).click();
        const result = await pending;
        check(result.suggestedFilename() === suggested, "Expected fixed download filename.");
        await result.saveAs(path.join(directory, filename));
      };
      const exportButton = name === "catalog" ? "#export-json" : "#download-current";
      const exportName = name === "catalog" ? "catalog-filtered.json" : "maintenance-current-records.json";
      await page.goto(pathToFileURL(path.join(directory, name + ".html")).href);
      await count(name === "catalog" ? 3 : 4);
      const labels = await page.locator("#jurisdiction option").evaluateAll(options => options.slice(1).map(option => [option.value, option.textContent]));
      check(JSON.stringify(labels) === JSON.stringify([["Fictional Area", "Fictional Area"], ["Fictional_Area", "Fictional_Area"]]), "Exact distinct jurisdiction labels.");
      if (name === "catalog") {
        const facets = await page.locator("#facets section").first().textContent();
        check(facets.includes("Fictional_Area: 1") && facets.includes("Fictional Area: 2"), "Exact facet labels and counts.");
      } else {
        const publishers = await page.locator("#publisher-filter option").evaluateAll(options => options.slice(1).map(option => [option.value, option.textContent]));
        check(JSON.stringify(publishers) === JSON.stringify([["Example A", "Example A"], ["Example_A", "Example_A"]]), "Exact distinct publisher labels.");
      }
      for (const [value, suffix] of [["Fictional_Area", "underscore"], ["Fictional Area", "space"]]) {
        await page.locator("#jurisdiction").selectOption(value);
        await page.locator("#search").fill("Fictional inert text");
        await count(name === "catalog" && suffix === "underscore" ? 1 : 2);
        await download(exportButton, name + "-" + suffix + ".json", exportName);
        await page.locator("#reset").click();
        await count(name === "catalog" ? 3 : 4);
        check(await page.locator("#search").inputValue() === "", "Reset clears combined search.");
      }
      await download(exportButton, name + "-all.json", exportName);
      if (name === "catalog") {
        await page.locator("#max-review-age").fill("0");
        await count(1);
        await download(exportButton, "catalog-fresh.json", exportName);
        await page.locator("#reset").click();
        await page.locator("#date-from").fill("2024-01-05");
        await page.locator("#date-to").fill("2024-01-03");
        check(await page.locator("#error").isVisible() && await page.locator(exportButton).isDisabled(), "Invalid range disables export.");
      } else {
        await page.locator("#publisher-filter").selectOption("Example_A");
        await page.locator("#transition-filter").selectOption("source_evidence_changed");
        await count(1);
        check((await cards.textContent()).includes("synthetic-a"), "Combined source and transition filters.");
        await page.locator("#reset").click();
        await page.locator("#view-queue").click();
        await count(2);
        await page.locator("#reset").click();
        await page.locator("#change-filter").selectOption("removed");
        await count(1);
        check(await page.locator(exportButton).isDisabled(), "Removed-only view cannot export current records.");
        await download("#download-selection", "removed.json", "maintenance-selection.json");
        await page.locator("#reset").click();
        await download("#download-report", "report.json", "maintenance-report.json");
        await page.locator("#snapshot-context summary").click();
        await download("#download-before", "before.json", "catalog-before-snapshot.json");
        await download("#download-after", "after.json", "catalog-after-snapshot.json");
      }
      await page.locator("#reset").click();
      await page.locator("#search").fill("no matching fictional text");
      await count(0);
      check(await page.locator("#empty").isVisible() && await page.locator(exportButton).isDisabled(), "Empty matches disable export.");
      await page.locator("#reset").click();
      await page.locator("#records details.card summary").first().click();
      check((await cards.first().textContent()).includes('</script><img src=x onerror=alert("fictional")>'), "Hostile fixture remains literal text.");
      check(await page.locator("img").count() === 0, "No injected image element.");
      check(await page.evaluate(() => localStorage.length === 0 && sessionStorage.length === 0), "No browser storage.");
      await page.setViewportSize({width: 390, height: 844});
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Narrow layout has no horizontal overflow.");
      check(errors.length === 0 && requests.length === 0, "No page errors, dialogs or external request attempts.");
      await context.close();
    }
    scenario = engine + ": Python download verification";
    const downloads = {};
    for (const filename of ["catalog-underscore.json", "catalog-space.json", "catalog-all.json", "catalog-fresh.json",
      "maintenance-underscore.json", "maintenance-space.json", "maintenance-all.json", "report.json", "before.json", "after.json", "removed.json"]) {
      downloads[filename] = JSON.parse(await fs.readFile(path.join(directory, filename), "utf8"));
    }
    assert.deepEqual(python({mode: "verify", downloads}), {verified_exports: 11});
    console.log(JSON.stringify({engine, version: browser.version(), checks, verified_exports: 11, fixtures: "fictional", external_requests: 0}));
  } finally {
    if (browser) await browser.close();
    await fs.rm(directory, {recursive: true, force: true});
  }
}

(async () => {
  const requested = process.argv.slice(2);
  const names = requested.length ? requested : ["chromium", "firefox"];
  assert.ok(names.length > 0 && names.every(name => ["chromium", "firefox"].includes(name)), "Supported browser engine required.");
  for (const engine of names) await run(engine);
})().catch(() => {console.error("Browser regression failed during " + scenario + ". No fixture content or local paths are printed."); process.exitCode = 1;});
