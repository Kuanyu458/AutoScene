import fs from "node:fs/promises";
import path from "node:path";
import { URL } from "node:url";
import { chromium } from "playwright";

const input = JSON.parse(await readStdin());
const allowedOps = new Set(["goto", "click", "fill", "select", "press", "scroll", "wait", "assert", "hold", "screenshot"]);

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => { data += chunk; });
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

function origin(value) {
  const parsed = new URL(value);
  if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password) {
    throw new Error(`blocked URL: ${value}`);
  }
  return parsed.origin.toLowerCase();
}

function resolveUrl(base, value) {
  return new URL(value || base, base).toString();
}

function safeScreenshot(recordingDir, relativePath) {
  if (!relativePath || path.isAbsolute(relativePath) || relativePath.split(/[\\/]/).includes("..")) {
    throw new Error("screenshot path must remain inside the recording directory");
  }
  return path.join(recordingDir, "screenshots", relativePath);
}

function assertAllowedFrames(page, baseOrigin, allowedOrigins) {
  for (const frame of page.frames()) {
    const frameUrl = frame.url();
    if (!frameUrl || frameUrl === "about:blank") continue;
    const frameOrigin = origin(frameUrl);
    if (frameOrigin !== baseOrigin && !allowedOrigins.has(frameOrigin)) {
      throw new Error(`cross-origin frame blocked: ${frameOrigin}`);
    }
  }
}

async function installCursor(page) {
  // Fixed runner-owned instrumentation for the Recordly-style cursor/ripple.
  // Job input cannot provide or alter this script; flow steps never evaluate JS.
  await page.addStyleTag({ content: `
    * { cursor: default !important; }
    #openmontage-cursor { position: fixed; z-index: 2147483647; width: 18px; height: 18px;
      border: 2px solid #0b6cff; border-radius: 50%; pointer-events: none; transform: translate(-50%, -50%);
      box-shadow: 0 0 0 3px rgba(11,108,255,.16); transition: left 80ms linear, top 80ms linear; }
    .openmontage-ripple { position: fixed; z-index: 2147483646; width: 12px; height: 12px; border: 2px solid #0b6cff;
      border-radius: 50%; pointer-events: none; transform: translate(-50%, -50%); animation: openmontage-ripple 500ms ease-out forwards; }
    @keyframes openmontage-ripple { from { opacity: .75; transform: translate(-50%, -50%) scale(.4); }
      to { opacity: 0; transform: translate(-50%, -50%) scale(3); } }
  `});
  await page.evaluate(() => {
    const cursor = document.createElement("div");
    cursor.id = "openmontage-cursor";
    document.documentElement.appendChild(cursor);
    document.addEventListener("mousemove", (event) => {
      cursor.style.left = `${event.clientX}px`;
      cursor.style.top = `${event.clientY}px`;
    }, { passive: true });
    document.addEventListener("click", (event) => {
      const ripple = document.createElement("div");
      ripple.className = "openmontage-ripple";
      ripple.style.left = `${event.clientX}px`;
      ripple.style.top = `${event.clientY}px`;
      document.documentElement.appendChild(ripple);
      setTimeout(() => ripple.remove(), 650);
    }, { passive: true });
  });
}

async function run() {
  const baseOrigin = origin(input.base_url);
  const allowedOrigins = new Set((input.allowed_origins || []).map(origin));
  const browser = await chromium.launch({ headless: true, slowMo: Number(input.slow_mo || 75) });
  const context = await browser.newContext({
    viewport: input.viewport || { width: 1920, height: 1080 },
    recordVideo: { dir: input.recording_dir, size: input.viewport || { width: 1920, height: 1080 } },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  const interactionEvents = [];
  const focusMap = [];
  const screenshotPaths = [];
  await page.goto(input.base_url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await installCursor(page);

  const navigate = async (target) => {
    const absolute = resolveUrl(input.base_url, target);
    const targetOrigin = origin(absolute);
    if (targetOrigin !== baseOrigin && !allowedOrigins.has(targetOrigin)) {
      throw new Error(`navigation leaves origin allow-list: ${targetOrigin}`);
    }
    await page.goto(absolute, { waitUntil: "domcontentloaded", timeout: 60000 });
    await installCursor(page);
  };

  for (const flow of input.flows || []) {
    for (const step of flow.steps || []) {
      if (!allowedOps.has(step.op)) throw new Error(`blocked operation: ${step.op}`);
      const selector = step.selector;
      const locator = selector ? page.locator(selector).first() : null;
      const timestamp = Number((Date.now() / 1000).toFixed(3));
      if (step.op === "goto") await navigate(step.url || input.base_url);
      else if (step.op === "click") {
        const box = await locator.boundingBox();
        await locator.click();
        const event = { flow: flow.name, op: step.op, selector, timestamp, x: box?.x ?? null, y: box?.y ?? null, width: box?.width ?? null, height: box?.height ?? null };
        interactionEvents.push(event);
        focusMap.push({ scene_id: flow.name, event: "click", selector, timestamp, anchor: event });
      } else if (step.op === "fill") await locator.fill(String(step.value ?? step.text ?? ""));
      else if (step.op === "select") await locator.selectOption(String(step.value));
      else if (step.op === "press") await locator.press(String(step.key || step.value));
      else if (step.op === "scroll") await page.mouse.wheel(Number(step.x || 0), Number(step.amount || step.y || 0));
      else if (step.op === "wait" || step.op === "hold") {
        if (step.op === "hold") await locator.hover();
        await page.waitForTimeout(Math.min(300000, Math.max(0, Number(step.seconds || 0) * 1000)));
      } else if (step.op === "assert") {
        await locator.waitFor({ state: "visible", timeout: 30000 });
        if (step.expected) {
          const text = await locator.textContent();
          if (!String(text || "").includes(String(step.expected))) throw new Error(`assertion failed for ${selector}`);
        }
      } else if (step.op === "screenshot") {
        const destination = safeScreenshot(input.recording_dir, step.path);
        await fs.mkdir(path.dirname(destination), { recursive: true });
        await page.screenshot({ path: destination, fullPage: false });
        screenshotPaths.push(destination);
      }
      const currentOrigin = origin(page.url());
      if (currentOrigin !== baseOrigin && !allowedOrigins.has(currentOrigin)) {
        throw new Error(`external redirect blocked: ${currentOrigin}`);
      }
      assertAllowedFrames(page, baseOrigin, allowedOrigins);
    }
  }

  const video = page.video();
  await context.close();
  const webmPath = video ? await video.path() : null;
  await browser.close();
  if (!webmPath) throw new Error("Playwright did not expose a WebM path");
  const result = {
    status: "recorded",
    webm_path: webmPath,
    focus_map: focusMap,
    interaction_events: interactionEvents,
    screenshot_paths: screenshotPaths,
    viewport: input.viewport,
  };
  await fs.writeFile(input.manifest_path, JSON.stringify(result, null, 2), "utf8");
  process.stdout.write(JSON.stringify(result));
}

try {
  await run();
} catch (error) {
  process.stderr.write(String(error?.stack || error));
  process.exitCode = 1;
}
