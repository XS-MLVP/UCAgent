---
name: formal-lib
description: Internal support skill for formal verification workspaces. This folder carries shared Python helpers and templates used by other formal skills and is not intended for direct user invocation.
---

# Formal Shared Library

This is an internal packaging skill.

It exists so the workspace skill copy step includes this directory and makes the shared helpers under `formal/lib/` available to the other formal skills.

Do not select this skill for standalone task execution unless you are specifically maintaining the shared formal helper library.
