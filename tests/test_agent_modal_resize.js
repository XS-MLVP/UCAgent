#!/usr/bin/env node

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const html = fs.readFileSync(
  path.join(__dirname, "..", "ucagent", "server", "templates", "agent.html"),
  "utf8",
);
const scriptMatch = html.match(/<script>\s*"use strict";([\s\S]*?)<\/script>/);
assert(scriptMatch, "dashboard main script was not found");

const script = scriptMatch[1];
const helperStart = script.indexOf("function _clampModalValue");
const helperEnd = script.indexOf("function _setModalRect", helperStart);
assert(helperStart >= 0 && helperEnd > helperStart, "modal resize helpers were not found");

const helpers = new Function(
  `${script.slice(helperStart, helperEnd)}\nreturn {_fitModalRect,_calculateModalResizeRect};`,
)();
const limits = {
  left: 8,
  top: 8,
  right: 1192,
  bottom: 792,
  minW: 400,
  minH: 260,
  maxW: 1184,
  maxH: 784,
};
const start = {left: 200, top: 150, width: 800, height: 500};

assert.deepEqual(helpers._calculateModalResizeRect("e", start, 100, 0, limits), {
  left: 200, top: 150, width: 900, height: 500,
});
assert.deepEqual(helpers._calculateModalResizeRect("w", start, -100, 0, limits), {
  left: 100, top: 150, width: 900, height: 500,
});
assert.deepEqual(helpers._calculateModalResizeRect("n", start, 0, -50, limits), {
  left: 200, top: 100, width: 800, height: 550,
});
assert.deepEqual(helpers._calculateModalResizeRect("s", start, 0, 100, limits), {
  left: 200, top: 150, width: 800, height: 600,
});
assert.deepEqual(helpers._calculateModalResizeRect("nw", start, -50, -60, limits), {
  left: 150, top: 90, width: 850, height: 560,
});
assert.deepEqual(helpers._calculateModalResizeRect("ne", start, 100, -50, limits), {
  left: 200, top: 100, width: 900, height: 550,
});
assert.deepEqual(helpers._calculateModalResizeRect("sw", start, -100, 100, limits), {
  left: 100, top: 150, width: 900, height: 600,
});
assert.deepEqual(helpers._calculateModalResizeRect("se", start, 9999, 9999, limits), {
  left: 200, top: 150, width: 992, height: 642,
});
assert.deepEqual(helpers._calculateModalResizeRect("w", start, 9999, 0, limits), {
  left: 600, top: 150, width: 400, height: 500,
});
assert.deepEqual(helpers._calculateModalResizeRect("n", start, 0, 9999, limits), {
  left: 200, top: 390, width: 800, height: 260,
});

const mobileLimits = {
  left: 4,
  top: 4,
  right: 356,
  bottom: 636,
  minW: 240,
  minH: 160,
  maxW: 352,
  maxH: 632,
};
assert.deepEqual(
  helpers._fitModalRect({left: 900, top: -20, width: 860, height: 900}, mobileLimits),
  {left: 4, top: 4, width: 352, height: 632},
);

assert.deepEqual(
  [...html.matchAll(/<div class="modal-resize-handle" data-resize-direction="se"/g)].length,
  3,
  "each resizable modal should provide its initial southeast handle",
);
assert.match(script, /\['n','ne','e','se','s','sw','w','nw'\]/);
assert.match(script, /addEventListener\('pointercancel',onUp\)/);
assert.match(html, /@media \(pointer:coarse\),\(max-width:600px\)/);

console.log("Agent modal resize geometry tests passed");
