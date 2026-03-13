-- Pandoc Lua filter: force table columns to wrap by assigning relative widths
-- This makes LaTeX writer use p{<width>} columns instead of l/c/r, enabling line wrapping.

-- For each Table, set all column widths to equal fractions of \linewidth.
-- You can customize per-table by adding a class `.nowrap` on the table to skip.

local function parse_colwidths_attr(attr)
  if not attr or not attr.attributes then return nil end
  local raw = attr.attributes["colwidths"] or attr.attributes["data-colwidths"]
  if not raw or raw == '' then return nil end
  local widths = {}
  for part in raw:gmatch('[^,]+') do
    local v = tonumber(part)
    if not v then return nil end
    table.insert(widths, v)
  end
  return widths
end

local function total_inline_length(cell)
  local sum = 0
  for _, block in ipairs(cell.content) do
    local txt = pandoc.utils.stringify(block)
    sum = sum + #txt
  end
  return sum
end

local function compute_dynamic_widths(tbl)
  -- If user provided colwidths attribute, use it (normalized to <=0.95 total)
  local user = parse_colwidths_attr(tbl.attr)
  local n = #tbl.colspecs
  if user and #user == n then
    local total = 0
    for _, v in ipairs(user) do total = total + v end
    if total > 0 then
      local scale = 0.95 / total
      local res = {}
      for i,v in ipairs(user) do res[i] = v * scale end
      return res
    end
  end
  -- Auto: estimate per-column weight by summing text length of each body cell
  local weights = {}
  for i=1,n do weights[i] = 0 end
  local function row_cells(row)
    if row and row.cells then return row.cells end
    return row
  end
  if tbl.bodies then
    for _, body in ipairs(tbl.bodies) do
      for _, row in ipairs(body.body) do
        local cells = row_cells(row)
        for ci, cell in ipairs(cells) do
          weights[ci] = weights[ci] + total_inline_length(cell)
        end
      end
    end
  end
  -- Avoid zero weights: assign small epsilon
  local total = 0
  for i,w in ipairs(weights) do
    if w <= 2 then w = 2 end -- minimal base weight
    weights[i] = w
    total = total + w
  end
  local target_total = 0.94 -- leave slack
  local result = {}
  for i,w in ipairs(weights) do
    result[i] = (w / total) * target_total
  end
  return result
end

function Table(tbl)
  if tbl.attr and tbl.attr.classes then
    for _, cls in ipairs(tbl.attr.classes) do
      if cls == 'nowrap' then return tbl end
    end
  end
  local n = #tbl.colspecs
  if n == 0 then return tbl end
  -- Pandoc 3.x: each colspec is a ColSpec object (table-like: {alignment,width})
  if type(pandoc.ColSpec) == 'function' and type(pandoc.ColWidth) == 'function' then
    local dynamic = compute_dynamic_widths(tbl)
    for i, spec in ipairs(tbl.colspecs) do
      local align = spec[1]
      tbl.colspecs[i] = pandoc.ColSpec(align, pandoc.ColWidth(dynamic[i]))
    end
  else
    -- Older fallback
    for i, spec in ipairs(tbl.colspecs) do
      spec[2] = 1.0 / n
      tbl.colspecs[i] = spec
    end
  end
  return tbl
end

-- Insert soft break opportunities into long unbreakable tokens within table cells.
-- This primarily targets long code/paths/identifiers so they can wrap within p-columns.

local function needs_breaking(s)
  if not s or s:find("%s") then return false end
  local ok, utf8 = pcall(require, 'utf8')
  local len = ok and utf8.len(s) or #s
  -- lower threshold, and also break typical slash-separated forms
  if (len or #s) >= 20 then return true end
  if s:find("/") and ((len or #s) >= 16) then return true end
  return false
end

local seps_pattern = "[/:%-_.;]"

local function split_with_breaks(s)
  -- Return a list of Inlines: Str/Code segments with RawInline allowbreak after separators
  local inlines = {}
  local i = 1
  while i <= #s do
    local c = s:sub(i,i)
    if c:match(seps_pattern) then
      table.insert(inlines, pandoc.Str(c))
      table.insert(inlines, pandoc.RawInline('latex', '\\allowbreak{}'))
      i = i + 1
    else
      -- accumulate until next sep
      local j = i
      while j <= #s and not s:sub(j,j):match(seps_pattern) do j = j + 1 end
      table.insert(inlines, pandoc.Str(s:sub(i, j-1)))
      i = j
    end
  end
  return inlines
end

local function escape_tex(s)
  return s:gsub('[\\{}%$#&_%%^]', function(c)
    if c == '_' then return '\\_' end
    if c == '%' then return '\\%' end
    return '\\' .. c
  end)
end

local function code_inline(el)
  if needs_breaking(el.text) then
    -- Use seqsplit to allow breaks anywhere plus explicit allowbreak after separators
    local broken = el.text:gsub('([/:%-%.])', '%1\\allowbreak{}')
    broken = escape_tex(broken)
    return pandoc.RawInline('latex', '\\texttt{\\seqsplit{' .. broken .. '}}')
  end
  return nil
end

local function str_inline(el)
  if needs_breaking(el.text) then
    return split_with_breaks(el.text)
  end
  return nil
end

function traverse_table_cells(blocks)
  -- Only affect inline elements within table cells
  local function str_inline_table(el)
    local s = el.text or ''
    local ok, utf8 = pcall(require, 'utf8')
    local len = ok and utf8.len(s) or #s
    -- If it's a long alphanumeric token without separators, allow break anywhere via seqsplit
    if not s:find(seps_pattern) and (len or #s) >= 14 and s:match("[%w]+") == s then
      local tex = escape_tex(s)
      return pandoc.RawInline('latex', '\\seqsplit{' .. tex .. '}')
    end
    -- Otherwise insert soft breaks after typical separators
    return split_with_breaks(s)
  end
  local handlers = {
    Code = code_inline,
    Str = str_inline_table,
  }
  return pandoc.walk_block(pandoc.Div(blocks), handlers).content
end

return {
  -- Global inline handlers to ensure breaking even if table cell traversal misses some cases
  { Str = function(el)
      if needs_breaking(el.text) and not el.text:match('^https?://') then
        return str_inline(el)
      end
      return nil
    end,
    Code = code_inline
  },
  { Table = function(t)
      -- First, enforce column widths
      t = Table(t)
      -- Then, walk through all cells
      -- Bodies
      if t.bodies then
        for _, body in ipairs(t.bodies) do
          for _, row in ipairs(body.body) do
            local cells = row.cells or row
            for ci, cell in ipairs(cells) do
              cell.content = traverse_table_cells(cell.content)
              cells[ci] = cell
            end
            if row.cells then row.cells = cells end
          end
        end
      end
      -- Head
      if t.head then
        local rows = t.head.rows or t.head
        for _, row in ipairs(rows) do
          local cells = row.cells or row
          for ci, cell in ipairs(cells) do
            cell.content = traverse_table_cells(cell.content)
            cells[ci] = cell
          end
          if row.cells then row.cells = cells end
        end
      end
      -- Foot
      if t.foot then
        local rows = t.foot.rows or t.foot
        for _, row in ipairs(rows) do
          local cells = row.cells or row
          for ci, cell in ipairs(cells) do
            cell.content = traverse_table_cells(cell.content)
            cells[ci] = cell
          end
          if row.cells then row.cells = cells end
        end
      end
      return t
    end }
}
