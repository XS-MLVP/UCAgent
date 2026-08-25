---
name: formal-lib
description: Internal support skill for formal verification workspaces. This folder carries shared Python helpers and templates used by other formal skills and is not intended for direct user invocation.
---

# Formal Shared Library

Markdown formatting contract: every generated ATX heading (`#` through `######`) is surrounded by a blank line; only a heading on the first line of a document or Markdown example may omit the preceding blank line. A tag, paragraph, list, table, nested heading, or closing fence must not directly follow a heading. The one exception is a machine anchor `<a id="..."></a>`, which must remain immediately before its target heading so the link stays valid.

This is an internal packaging skill.

It exists so the workspace skill copy step includes this directory and makes the shared helpers under `formal/lib/` available to the other formal skills.

Do not select this skill for standalone task execution unless you are specifically maintaining the shared formal helper library.
