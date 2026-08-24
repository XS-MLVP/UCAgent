#!/usr/bin/env node

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const marked = require(path.join(
  __dirname,
  "..",
  "ucagent",
  "server",
  "static",
  "marked.min.js",
));

const html = fs.readFileSync(
  path.join(__dirname, "..", "ucagent", "server", "templates", "agent.html"),
  "utf8",
);
const scriptMatch = html.match(/<script>\s*"use strict";([\s\S]*?)<\/script>/);
assert(scriptMatch, "dashboard main script was not found");

const script = scriptMatch[1];
const helperStart = script.indexOf("function _collapseMarkdownYamlBlocks");
const helperEnd = script.indexOf("function _renderViewMarkdown", helperStart);
assert(helperStart >= 0 && helperEnd > helperStart, "YAML collapse helper was not found");
assert.match(marked.parse("```yaml\nkey: value\n```"), /class="language-yaml"/);
assert.match(marked.parse("```yml\nkey: value\n```"), /class="language-yml"/);

class FakeClassList {
  constructor(element, classNames = []) {
    this.element = element;
    this.values = new Set(classNames);
  }

  contains(className) {
    return this.values.has(className);
  }

  setFromString(value) {
    this.values = new Set(String(value).split(/\s+/).filter(Boolean));
  }
}

class FakeElement {
  constructor(tagName, classNames = []) {
    this.tagName = tagName.toUpperCase();
    this.classList = new FakeClassList(this, classNames);
    this.parentElement = null;
    this.children = [];
    this.textContent = "";
    this.open = false;
  }

  set className(value) {
    this.classList.setFromString(value);
  }

  get className() {
    return [...this.classList.values].join(" ");
  }

  append(...children) {
    for (const child of children) {
      if (child.parentElement) {
        const index = child.parentElement.children.indexOf(child);
        if (index >= 0) child.parentElement.children.splice(index, 1);
      }
      child.parentElement = this;
      this.children.push(child);
    }
  }

  replaceWith(replacement) {
    const parent = this.parentElement;
    assert(parent, "replaceWith requires a parent");
    const index = parent.children.indexOf(this);
    assert(index >= 0, "element was not found in its parent");
    parent.children[index] = replacement;
    replacement.parentElement = parent;
    this.parentElement = null;
  }

  querySelectorAll(selector) {
    assert.equal(selector, "pre > code");
    const matches = [];
    const visit = element => {
      if (element.tagName === "CODE" && element.parentElement?.tagName === "PRE") {
        matches.push(element);
      }
      element.children.forEach(visit);
    };
    visit(this);
    return matches;
  }
}

const document = {createElement: tagName => new FakeElement(tagName)};
const {_collapseMarkdownYamlBlocks} = new Function(
  "document",
  `${script.slice(helperStart, helperEnd)}\nreturn {_collapseMarkdownYamlBlocks};`,
)(document);

const root = new FakeElement("div");
const blocks = [
  new FakeElement("code", ["language-yaml"]),
  new FakeElement("code", ["language-yml"]),
  new FakeElement("code", ["language-json"]),
];
for (const code of blocks) {
  const pre = new FakeElement("pre");
  pre.append(code);
  root.append(pre);
}

_collapseMarkdownYamlBlocks(root);

for (const index of [0, 1]) {
  const details = root.children[index];
  assert.equal(details.tagName, "DETAILS");
  assert(details.classList.contains("md-yaml-block"));
  assert.equal(details.open, false, "YAML blocks must be collapsed by default");
  assert.equal(details.children[0].tagName, "SUMMARY");
  assert.equal(details.children[0].textContent, "YAML");
  assert.equal(details.children[1].tagName, "PRE");
}
assert.equal(root.children[2].tagName, "PRE", "non-YAML blocks must remain unchanged");

_collapseMarkdownYamlBlocks(root);
assert.equal(root.children[0].children[1].tagName, "PRE", "reprocessing must not nest details");
assert.equal(root.children[1].children[1].tagName, "PRE", "reprocessing must not nest details");

assert.match(html, /_collapseMarkdownYamlBlocks\(el\);/);
assert.match(html, /#view-md details\.md-yaml-block>summary/);

console.log("Agent Markdown YAML collapse tests passed");
