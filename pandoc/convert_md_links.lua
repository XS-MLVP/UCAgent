-- Lua filter for Pandoc to convert .md file links to internal section references
-- This allows proper internal linking in PDF output

local file_to_id = {}
local processed_headers = {}
local html_anchors = {}  -- Store HTML anchor IDs

-- Extract filename without extension and path
local function extract_basename(path)
  local without_ext = path:gsub("%.md$", "")
  local basename = without_ext:match("([^/]+)$") or without_ext
  return basename
end

-- Normalize text to create an ID (handles Chinese and English)
-- Matches Pandoc's auto ID generation behavior
local function normalize_text_to_id(text)
  if type(text) == "table" then
    text = pandoc.utils.stringify(text)
  end
  
  -- Convert to lowercase
  local id = text:lower()
  -- Replace spaces with hyphens
  id = id:gsub("%s+", "-")
  -- Remove characters that Pandoc removes (but keep underscores, hyphens, and UTF-8)
  -- Pandoc keeps: alphanumeric, hyphens, underscores, periods, Chinese chars
  id = id:gsub("[^%w%.%-_\128-\255]+", "")
  return id
end

-- Extract HTML anchor IDs from RawInline elements
local function extract_html_anchor(raw_html)
  -- Match <a id="..."> or <a id='...'>
  local id = raw_html:match('<a%s+id%s*=%s*"([^"]+)"') or 
             raw_html:match("<a%s+id%s*=%s*'([^']+)'")
  return id
end

-- Process the entire document
function Pandoc(doc)
  local blocks = doc.blocks
  local input_files = PANDOC_STATE.input_files or {}
  local file_index = 1
  
  -- First pass: assign IDs to all headers and map files to H1 IDs
  -- Also extract HTML anchors
  local current_section_id = nil  -- Track current section for list items
  
  for i, block in ipairs(blocks) do
    if block.t == "Header" then
      local header_text = pandoc.utils.stringify(block.content)
      local id = normalize_text_to_id(header_text)
      
      if block.level == 1 then
        -- Ensure unique IDs for H1
        local base_id = id
        local counter = 1
        while processed_headers[id] do
          id = base_id .. "-" .. counter
          counter = counter + 1
        end
        
        block.identifier = id
        processed_headers[id] = true
        current_section_id = id
        
        -- Map current input file to this H1 ID
        if file_index <= #input_files then
          local filepath = input_files[file_index]
          local basename = extract_basename(filepath)
          local content_path = filepath:gsub("^docs/content/", "")
          
          -- Register all path variants
          file_to_id[basename] = id
          file_to_id[filepath] = id
          file_to_id[content_path] = id
          
          file_index = file_index + 1
        end
      else
        -- For H2+ headers, keep Pandoc's auto-generated ID if it exists
        if not block.identifier or block.identifier == "" then
          local base_id = id
          local counter = 1
          while processed_headers[id] do
            id = base_id .. "-" .. counter
            counter = counter + 1
          end
          block.identifier = id
        end
        -- Record all header IDs to avoid duplicates
        processed_headers[block.identifier] = true
        current_section_id = block.identifier
      end
      
      -- Check if this header contains HTML anchors
      for _, inline in ipairs(block.content) do
        if inline.t == "RawInline" and inline.format == "html" then
          local anchor_id = extract_html_anchor(inline.text)
          if anchor_id then
            io.stderr:write(string.format("Found HTML anchor in header: %s -> %s\n", 
              anchor_id, block.identifier or id))
            html_anchors[anchor_id] = block.identifier or id
          end
        end
      end
    elseif block.t == "OrderedList" or block.t == "BulletList" then
      -- Check list items for HTML anchors and inject span elements
      local function process_list_content(content)
        if type(content) == "table" then
          for _, item in ipairs(content) do
            if type(item) == "table" then
              for _, subblock in ipairs(item) do
                if subblock.t == "Plain" or subblock.t == "Para" then
                  local new_content = {}
                  for idx, inline in ipairs(subblock.content) do
                    if inline.t == "RawInline" and inline.format == "html" then
                      local anchor_id = extract_html_anchor(inline.text)
                      if anchor_id then
                        -- Register this anchor ID
                        html_anchors[anchor_id] = anchor_id
                        processed_headers[anchor_id] = true
                        -- Insert a Span with ID before the HTML anchor
                        table.insert(new_content, pandoc.Span({}, {id = anchor_id}))
                        -- Remove the HTML anchor itself (don't add it to new_content)
                      else
                        table.insert(new_content, inline)
                      end
                    else
                      table.insert(new_content, inline)
                    end
                  end
                  subblock.content = new_content
                end
              end
            end
          end
        end
      end
      process_list_content(block.content)
    end
  end
  
  -- Second pass: convert .md links to section references
  return doc:walk({
    Link = function(el)
      local target = el.target
      
      -- Skip external links
      if target:match("^https?://") or target:match("^ftp://") or target:match("^mailto:") then
        return el
      end
      
      -- Process markdown file links
      if target:match("%.md") then
        -- Clean up target
        target = target:gsub("^%./", "")
        
        -- Extract file and anchor parts
        local file_part, anchor_part = target:match("^(.-)/?#(.+)$")
        if not file_part then
          file_part = target
          anchor_part = nil
        end
        
        -- Remove ../ but keep folder structure
        file_part = file_part:gsub("%.%./", "")
        
        -- Get basename
        local basename = extract_basename(file_part)
        
        -- Try multiple lookup strategies
        local section_id = file_to_id[basename] or file_to_id[file_part]
        
        -- Try matching by basename in all registered files
        if not section_id then
          for registered_path, id in pairs(file_to_id) do
            if extract_basename(registered_path) == basename then
              section_id = id
              break
            end
          end
        end
        
        if anchor_part then
          -- Check if this is an HTML anchor first
          if html_anchors[anchor_part] then
            el.target = "#" .. html_anchors[anchor_part]
          else
            -- Use normalized anchor
            local anchor_id = normalize_text_to_id(anchor_part)
            el.target = "#" .. anchor_id
          end
        elseif section_id then
          -- Link to the file's H1 section
          el.target = "#" .. section_id
        else
          -- Fallback: use filename-based ID
          local fallback_id = basename:gsub("_", "-"):lower()
          el.target = "#" .. fallback_id
        end
      end
      
      return el
    end
  })
end
