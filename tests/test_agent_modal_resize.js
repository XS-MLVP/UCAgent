#!/usr/bin/env node

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const html = fs.readFileSync(
  path.join(__dirname, "..", "ucagent", "interfaces", "server", "templates", "agent.html"),
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

// File content must use the available flex height even before any saved resize
// exists. Measuring a Loading placeholder used to freeze the body at a tiny size.
const contentStart=script.indexOf('function _resizeModalContent');
const contentEnd=script.indexOf('function _applyStoredModalResize',contentStart);
const resizeContent=new Function(`${script.slice(contentStart,contentEnd)}\nreturn _resizeModalContent;`)();
const fileBody={id:'view-body',style:{height:'60px',maxHeight:'60px'}};
resizeContent({querySelector:selector=>selector==='.modal-body'?fileBody:null});
assert.equal(fileBody.style.height,'');
assert.equal(fileBody.style.maxHeight,'');

const resetStart=script.indexOf('function resetFileViewSize');
const resetEnd=script.indexOf('function showErr',resetStart);
const sizes={'view-modal':{w:450,h:260},'edit-modal':{w:900,h:600}};
const positions={'view-modal':{x:12,y:15},'edit-modal':{x:20,y:30}};
const box={style:{width:'450px',height:'260px',maxWidth:'none',maxHeight:'none',left:'12px',top:'15px',transform:'none'}};
const stored=new Map();let reopened;
const reset=new Function('_modalResizeState','_modalDragState','localStorage','qs','openModal',
  `${script.slice(resetStart,resetEnd)}\nreturn resetFileViewSize;`)(sizes,positions,
  {setItem:(key,value)=>stored.set(key,value)},()=>box,id=>{reopened=id;});
reset();
assert.equal(reopened,'view-modal');
assert(!sizes['view-modal']&&!positions['view-modal']);
assert.deepEqual(sizes['edit-modal'],{w:900,h:600});
assert.deepEqual(positions['edit-modal'],{x:20,y:30});
assert(Object.values(box.style).every(value=>value===''));
assert(!JSON.parse(stored.get('ucagent.modal.resize'))['view-modal']);
console.log('File viewer initial layout and scoped reset tests passed');
