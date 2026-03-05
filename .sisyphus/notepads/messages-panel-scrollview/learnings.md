# MessagesScrollView Previous Attempt Learnings

**Date**: 2026-03-05T00:00:00Z
**Task**: Review and extract patterns from failed MessagesScrollView implementation

## Key API Design from Previous Attempt

### Core Methods
- `append_text(text, newline=False)` - Flexible text append with optional newline
- `append_with_typewriter(text, speed, chars_per_tick)` - Animated character reveal
- `append_message(message)` - Thread-safe batch queue method

### Internal Data Structures
- `_lines` - List of rendered Text/Strip objects (line cache)
- `_text_history` - Full text history for reflow on resize
- Line-based rendering with Strip-based rich formatting

## What Worked Well (Worth Reusing)

1. **API Design**: The `append_text(text, newline=False)` pattern is intuitive
2. **Data Structures**: Dual tracking of `_lines` and `_text_history` enables both rendering and reflowing
3. **Feature Scope**: Basic text + colors + same-line append + animations are solid features
4. **Performance**: Line caching and batch processing patterns shown to be effective

## Likely Causes of Revert (Pitfalls to Avoid)

1. **Implementation Complexity**: Previous attempt had too many optimization layers
   - Line cache with LRU invalidation might be over-engineered
   - Batch message queue with 0.2s intervals adds unnecessary complexity
   - Window resize reflow logic could be fragile

2. **Possible Integration Issues**:
   - Custom render_line() method may conflict with Textual's rendering pipeline
   - AutoScrollMixin inheritance might have caused lifecycle issues
   - Threading/batch processing complexity could cause race conditions

3. **Testing Gap**: Only demo scripts, no unit tests found
   - Need to test multiline text handling more thoroughly
   - Same-line append edge cases not well covered
   - Color preservation during animations needs validation

## Recommendations for Wave 2

1. **Start Simple**: Implement only essential features first
   - Basic append + newline support
   - ANSI color preservation  
   - Auto-scroll behavior
   
2. **Defer Optimizations**: Add these only if performance is a problem:
   - Line caching
   - Batch processing queues
   - Complex reflow logic

3. **Build With Tests**: Create unit tests alongside implementation
   - Test multiline handling
   - Test same-line append correctness
   - Test ANSI color preservation

4. **Incremental Features**: Add in this order:
   1. Basic text rendering (solid foundation)
   2. Same-line append (moderately complex)
   3. Typewriter animation (nice-to-have)
   4. Optimizations (if needed)

## Code Patterns Observed

- Rich Text integration: `Text.from_ansi()` for ANSI parsing
- Custom rendering: Override `render_line()` for Strip-based output
- Textual composition: Standard `compose()` and `on_mount()` patterns
- Auto-scroll mixin: Provides inherited scroll management (worth keeping)


---

# Task 2: ScrollView render_line Contract Research

**Date**: 2026-03-05T17:20:00Z
**Task**: Research ScrollView render_line pattern from Textual source code
**Evidence**: .sisyphus/evidence/task-2-scrollview-check.txt

## ScrollView Class Contract

ScrollView is a base class for Line API widgets (in `/textual/scroll_view.py`):
- Inherits from `ScrollableContainer`
- Marked `ALLOW_MAXIMIZE = True`
- Default CSS: `overflow-y: auto; overflow-x: auto;`
- **Key Properties**: `is_scrollable` (always True), `is_container` (always False)

### Inherited render_line() Method

The `render_line(y: int) -> Strip` method is inherited from `Widget` base class:
```python
def render_line(self, y: int) -> Strip:
    """Render a line of content.
    
    Args:
        y: Y Coordinate of line.
    
    Returns:
        A rendered line.
    """
```

**Contract**: Receives widget-relative y coordinate (0 = first visible line of widget).

## RichLog render_line Implementation Pattern

RichLog (in `/textual/widgets/_rich_log.py`) implements the Line API via `ScrollView`:

### 1. render_line() Method (L301-307)
```python
def render_line(self, y: int) -> Strip:
    scroll_x, scroll_y = self.scroll_offset
    line = self._render_line(
        scroll_y + y, scroll_x, self.scrollable_content_region.width
    )
    strip = line.apply_style(self.rich_style)
    return strip
```

**Key Pattern**: 
- Receives widget-relative `y` (0 to height-1)
- Adds `scroll_y` offset to get content index: `scroll_y + y`
- Passes to `_render_line()` for cached rendering

### 2. _render_line() Helper (L309-319)
```python
def _render_line(self, y: int, scroll_x: int, width: int) -> Strip:
    if y >= len(self.lines):
        return Strip.blank(width, self.rich_style)
    
    key = (y + self._start_line, scroll_x, width, self._widest_line_width)
    if key in self._line_cache:
        return self._line_cache[key]
    
    line = self.lines[y].crop_extend(scroll_x, scroll_x + width, self.rich_style)
    
    self._line_cache[key] = line
    return line
```

**Cache Key Structure**:
- `y + self._start_line` - Absolute line index (handles line trimming)
- `scroll_x` - Horizontal scroll position
- `width` - Render width (for responsive caching)
- `self._widest_line_width` - Max line width (invalidates on resize)

**Horizontal Cropping**: `strip.crop_extend(scroll_x, scroll_x + width, style)` handles left scroll offset.

### 3. Rendering Pipeline (L251-253)

Text → RichLog is converted via:
1. `console.render(renderable, options)` → Segment iterator
2. `Segment.split_lines(segments)` → List[List[Segment]] (lines)
3. `Strip.from_lines(lines)` → List[Strip] (cached strips)

Code (L251-253):
```python
segments = self.app.console.render(renderable, render_options)
lines = list(Segment.split_lines(segments))
strips = Strip.from_lines(lines)
```

### 4. Virtual Size Management (L279)

```python
self.virtual_size = Size(self._widest_line_width, len(self.lines))
```

- **Width**: `_widest_line_width` (max line width across all stored lines)
- **Height**: `len(self.lines)` (line count)
- Updated after each `write()` call
- Scrollbars automatically adjust based on this size

### 5. State Reset Pattern (L286-298)

```python
def clear(self) -> Self:
    self.lines.clear()
    self._line_cache.clear()
    self._start_line = 0
    self._widest_line_width = 0
    self._deferred_renders.clear()
    self.virtual_size = Size(0, len(self.lines))
    self.refresh()
    return self
```

**Critical Fields**:
- `self.lines` - List of Strip objects (rendered lines)
- `self._line_cache` - LRU cache of rendered lines (key: content y, scroll_x, width, max_width)
- `self._start_line` - Offset for absolute indexing (handles line trimming)
- `self._widest_line_width` - Maximum width for cache invalidation
- `self.virtual_size` - Passed to scrollbar system for viewport calculation

## Implementation Requirements for MessagesScrollView

Based on this analysis, a custom Line API widget must:

1. **Override render_line(y: int) -> Strip**:
   - Accept widget-relative y coordinate (0 to visible height)
   - Add scroll_offset.y to convert to content index
   - Return a Strip object (fixed-width, styled text line)

2. **Maintain virtual_size**:
   - Set `self.virtual_size = Size(width, len(lines))`
   - ScrollView automatically shows scrollbars based on this

3. **Cache Rendered Lines** (optional but recommended):
   - Key includes: content_y, scroll_x, visible_width
   - Invalidate on size changes (watch_scroll_x/watch_scroll_y triggers)

4. **Handle Horizontal Scrolling**:
   - `scroll_x` offset must be applied to crop Strip output
   - Use `Strip.crop_extend(scroll_x, scroll_x + width, style)` pattern

5. **Handle Line Trimming**:
   - Track `_start_line` offset if implementing max_lines
   - Include in cache key to invalidate properly

## Coordinate Systems Summary

| Coordinate | Purpose | Range | Notes |
|---|---|---|---|
| Widget-relative y | render_line() parameter | 0 to height-1 | What method receives |
| Content index | self.lines[] lookup | 0 to len(lines)-1 | Add scroll_offset.y |
| Absolute line | Cache key component | varies | May include _start_line offset |
| scroll_x | Horizontal offset | 0 to max-width | Use in crop_extend() |
| scroll_y | Vertical offset | 0 to total_height | Add to widget y for content index |

