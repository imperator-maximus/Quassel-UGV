import { chromium } from "playwright";

const baseUrl = process.env.UGV_BASE_URL || "http://raspberrycan";
const headless = process.env.UGV_HEADLESS !== "0";

const browser = await chromium.launch({ headless });
const page = await browser.newPage();
const browserErrors = [];
const failedRequests = [];

page.on("pageerror", error => {
  browserErrors.push(error.message);
});

page.on("console", message => {
  if (message.type() === "error") {
    browserErrors.push(message.text());
  }
});

page.on("requestfailed", request => {
  failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`.trim());
});

try {
  await page.goto(baseUrl, { waitUntil: "networkidle", timeout: 30000 });

  const mappingScript = await page.locator('script[src="/static/js/mapping_editor.js"]').count();
  if (mappingScript !== 1) {
    throw new Error(`Expected one mapping_editor.js script tag, found ${mappingScript}`);
  }

  const scriptResponse = await page.request.get(`${baseUrl}/static/js/mapping_editor.js`);
  if (!scriptResponse.ok()) {
    throw new Error(`mapping_editor.js returned HTTP ${scriptResponse.status()}`);
  }

  await page.getByRole("button", { name: "Karten" }).click();
  await page.locator("#mapEditor").waitFor({ state: "visible", timeout: 10000 });
  await page.locator("#mapSelect").waitFor({ state: "visible", timeout: 10000 });
  await page.getByRole("button", { name: "OSM" }).waitFor({ state: "visible", timeout: 10000 });
  await page.getByRole("button", { name: "Bahnen anzeigen" }).waitFor({ state: "visible", timeout: 10000 });

  const exportedFunctions = await page.evaluate(() => [
    "initMapEditor",
    "refreshMapList",
    "loadSelectedMap",
    "generateLanePreview",
    "clearLanePreview",
    "updateLaneProgress",
  ].filter(name => typeof window[name] !== "function"));
  if (exportedFunctions.length) {
    throw new Error(`Missing mapping globals: ${exportedFunctions.join(", ")}`);
  }
  const facadeFunctions = await page.evaluate(() => [
    "initMapEditor",
    "refreshMapList",
    "loadSelectedMap",
    "generateLanePreview",
    "clearLanePreview",
    "updateLaneProgress",
  ].filter(name => typeof window.MappingEditor?.[name] !== "function"));
  if (facadeFunctions.length) {
    throw new Error(`Missing MappingEditor facade functions: ${facadeFunctions.join(", ")}`);
  }

  const mapInitialized = await page.evaluate(() => Boolean(window.mapEditor));
  if (!mapInitialized) {
    throw new Error("Map editor did not initialize");
  }

  if (browserErrors.length) {
    throw new Error(`Browser errors:\n${browserErrors.join("\n")}`);
  }
  if (failedRequests.length) {
    throw new Error(`Failed requests:\n${failedRequests.join("\n")}`);
  }

  console.log(`Mapping UI smoke test passed: ${baseUrl}`);
} finally {
  await browser.close();
}
