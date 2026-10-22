-- Lua filter for Pandoc: strip decorative emoji/symbol chars in LaTeX/PDF output.
-- This avoids xeLaTeX missing glyph warnings when the selected CJK font lacks emoji glyphs.

if not FORMAT:match("latex") then
  return {}
end

local blocked = {
  [0xFE0F] = true, -- variation selector-16
  [0x1F680] = true, -- rocket
  [0x1F3D7] = true, -- building construction
  [0x2699] = true,  -- gear
  [0x1F4DD] = true, -- memo
  [0x1F6E0] = true, -- hammer and wrench
  [0x1F4DA] = true, -- books
  [0x2705] = true,  -- check mark button
  [0x1F3AF] = true, -- bullseye
  [0x1F4D6] = true, -- open book
  [0x1F4BB] = true, -- laptop
  [0x1F393] = true, -- graduation cap
  [0x1F41B] = true, -- bug
  [0x1F4A1] = true, -- light bulb
  [0x274C] = true,  -- cross mark
  [0x1F449] = true, -- backhand index pointing right
  [0x279C] = true,  -- heavy round-tipped rightwards arrow
}

local function strip_blocked_chars(s)
  local out = {}
  for _, codepoint in utf8.codes(s) do
    if not blocked[codepoint] then
      out[#out + 1] = utf8.char(codepoint)
    end
  end
  return table.concat(out)
end

function Str(el)
  local stripped = strip_blocked_chars(el.text)
  if stripped == el.text then
    return nil
  end
  if stripped == "" then
    return {}
  end
  return pandoc.Str(stripped)
end
