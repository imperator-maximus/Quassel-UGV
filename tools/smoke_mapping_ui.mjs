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

  const mappingScript = await page.locator('script[src^="/static/js/mapping_editor.js"]').count();
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
  await page.getByRole("button", { name: "Pfad berechnen" }).waitFor({ state: "visible", timeout: 10000 });
  const simulationButton = page.locator("#planSimulateBtn");
  await simulationButton.waitFor({ state: "attached", timeout: 10000 });
  if (await simulationButton.isVisible()) {
    throw new Error("Simulation button must stay hidden until a plan is loaded");
  }
  await page.locator("#planSelect").waitFor({ state: "visible", timeout: 10000 });
  await page.waitForFunction(() => (
    [...document.querySelectorAll("#planSelect option")].some(option => option.value)
  ), null, { timeout: 10000 });
  const planValue = await page.locator("#planSelect option").evaluateAll(options => (
    options.find(option => option.value)?.value || ""
  ));
  await page.locator("#planSelect").selectOption(planValue);
  await page.locator("#planLoadBtn").click();
  await simulationButton.waitFor({ state: "visible", timeout: 15000 });
  await page.locator("#activePlanLabel").waitFor({ state: "visible", timeout: 10000 });
  await page.locator("#laneProgressSlider").waitFor({ state: "visible", timeout: 10000 });
  await page.locator("#simulationUseCurrentPose").waitFor({ state: "visible", timeout: 10000 });
  await page.locator("#simulationScope").waitFor({ state: "visible", timeout: 10000 });
  if (await page.locator("#simulationScope").inputValue() !== "3") {
    throw new Error("Local simulation scope must default to three plan segments");
  }
  await page.waitForFunction(() => !document.querySelector("#planPlayBtn")?.disabled, null, {
    timeout: 15000,
  });
  const playStatus = await page.locator("#planPlayStatus").textContent();
  if (!playStatus?.includes("Simulation optional")) {
    throw new Error(`Play must not require simulation: ${playStatus}`);
  }

  const exportedFunctions = await page.evaluate(() => [
    "initMapEditor",
    "refreshMapList",
    "loadSelectedMap",
    "generateLanePreview",
    "simulateLanePlan",
    "toggleLaneSimulationPause",
    "stopLaneSimulation",
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
    "simulateLanePlan",
    "toggleLaneSimulationPause",
    "stopLaneSimulation",
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

  await page.locator("#laneProgressSlider").evaluate(element => {
    element.value = "81.1";
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.locator("#simulationUseCurrentPose").check();
  const simulationResponsePromise = page.waitForResponse(response => (
    response.url().includes("/plan/simulate") && response.request().method() === "POST"
  ), { timeout: 30000 });
  await simulationButton.click();
  const simulationResponse = await simulationResponsePromise;
  const simulationPayload = await simulationResponse.json();
  if (!simulationResponse.ok() || !simulationPayload.success || !(simulationPayload.trajectory?.length > 2)) {
    throw new Error(`Controller simulation failed: ${JSON.stringify(simulationPayload)}`);
  }
  await page.waitForFunction(() => {
    const text = document.querySelector("#planSimulationStatus")?.textContent || "";
    return text.includes("Reglersimulation läuft")
      || text.includes("Reglersimulation abgeschlossen")
      || text.includes("Reglersimulation STOP");
  }, null, { timeout: 10000 });

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
