"""
DesignAgent - Analyzes slides visually and provides design fixes.

Hybrid approach:
1. Vision model (LLM) → Suggests SPECIFIC actions with full documentation
2. apply_fixes (deterministic) → Executes those actions reliably
"""

from typing import Dict, Any, List, Optional
import json
import re
import copy
import logging
from pathlib import Path
from autodeck_core.llm.gemma_client import GemmaClient
from autodeck_core.llm.gemini_client import GeminiClient



# =============================================================================
# COMPLETE ACTION CATALOG (For Vision Model Prompt)
# =============================================================================

ACTION_CATALOG = """
## COMPLETE ACTION CATALOG

### Problem → Solution Quick Reference
| Visual Problem | Recommended Actions |
|----------------|---------------------|
| Text crammed/narrow | `body_width:full`, `body_width:wide` |
| Text overflowing | `body_font_size:small`, `split_slide` |
| Too much whitespace | `body_width:narrow`, `body_font_size:large` |
| Text hard to read | `body_font_size:large`, `line_spacing:1.5` |
| Bullets too close | `para_spacing:loose`, `line_spacing:1.5` |
| Title too small | `title_font_size:large` |
| Needs emphasis | Use **bold** in content for key terms |
| Poor alignment | `text_align:left`, `text_align:center` |
| Content dense | `text_padding:loose`, `line_spacing:1.5` |

---

### 1. WIDTH & POSITION ACTIONS (Shape Level)
Control how much horizontal/vertical space the content uses.

```
# Body Content Width
body_width:full         → 9.4" width (edge-to-edge, MAXIMUM readability)
body_width:wide         → 9.0" width (small margins)
body_width:normal       → 8.0" width (standard layout)
body_width:narrow       → 6.0" width (for image-beside-text)

# Body Position
body_left:X             → Left edge X inches from slide left (0.3-2.0)
body_top:X              → Top edge X inches from slide top (1.5-3.0)

# Title Width & Position
title_width:full        → Title spans full slide
title_width:normal      → Standard title width
title_left:X            → Title left position
title_top:X             → Title top position

# Image Position & Size
image_width:X           → Image width in inches
image_height:X          → Image height in inches
image_left:X            → Image left position
image_top:X             → Image top position
```

---

### 2. FONT ACTIONS
Control text size, style, and appearance.

```
# Body Font Size
body_font_size:N        → Set body text to N points (10-24)
body_font_size:large    → 20pt (for minimal content)
body_font_size:medium   → 16pt (balanced)
body_font_size:small    → 12pt (for dense content)
increase_font           → Increase by 2pt
decrease_font           → Decrease by 2pt

# Title Font Size
title_font_size:N       → Set title to N points (24-44)
title_font_size:large   → 40pt
title_font_size:medium  → 32pt
title_font_size:small   → 28pt

# Font Style (applies to all body text)
body_font_bold:on       → Make body text bold
body_font_bold:off      → Remove bold from body
body_font_italic:on     → Make body text italic
body_font_italic:off    → Remove italic
body_font_color:RRGGBB  → Set body text color (hex, e.g., 333333)

# Title Style
title_font_bold:on      → Make title bold
title_font_color:RRGGBB → Set title color
```

---

### 3. SPACING ACTIONS (Paragraph Level)
Control space between lines, paragraphs, and text edges.

```
# Line Spacing (vertical space between lines within a bullet)
line_spacing:single     → 1.0x (tight, compact)
line_spacing:1.15       → 1.15x (default, standard)
line_spacing:1.5        → 1.5x (comfortable, readable)
line_spacing:double     → 2.0x (very spread out)

# Paragraph Spacing (space between bullets)
para_spacing:tight      → 6pt between bullets (compact)
para_spacing:normal     → 12pt between bullets (standard)
para_spacing:loose      → 18pt between bullets (spacious)

# Text Padding (inner margins inside text box)
text_padding:loose      → 0.5" inner margins (lots of breathing room)
text_padding:normal     → 0.25" inner margins (standard)
text_padding:tight      → 0.1" inner margins (maximum text space)
text_padding:none       → 0" (text touches edges)
```

---

### 4. ALIGNMENT ACTIONS
Control horizontal text alignment.

```
text_align:left         → Left-aligned (default for bullets)
text_align:center       → Centered (good for titles, quotes)
text_align:right        → Right-aligned
text_align:justify      → Justified (even left and right edges)
```

---

### 5. LAYOUT ACTIONS
Change the overall slide structure.

```
set_layout:standard_list → Single column with bullets (default)
set_layout:two_column    → Split content into left/right columns
set_layout:title_only    → Large title area, minimal body
set_layout:image_left    → Image on left, text on right
set_layout:image_right   → Text on left, image on right
set_layout:grid_2x2      → Four quadrants for comparison
```

---

### 6. SHAPE APPEARANCE ACTIONS
Control background and border of text boxes.

```
# Body Box Appearance
body_fill:RRGGBB        → Set body box background color (hex)
body_fill:none          → Transparent body background
body_border:RRGGBB      → Set body box border color
body_border:none        → Remove body border
body_border_width:N     → Border thickness in points

# Title Box Appearance
title_fill:RRGGBB       → Set title box background color
title_fill:none         → Transparent title background
```

---

### 7. CONTENT ACTIONS
Affect the content structure itself.

```
split_slide             → Flag: content should be split into 2 slides
word_wrap:on            → Enable word wrapping (default)
word_wrap:off           → Disable wrapping (text may overflow)
```

---

### TEXT FORMATTING via Markdown
To format specific words, use markdown in the bullet content:

```
**bold text**           → Renders as bold
*italic text*           → Renders as italic (if supported)
```

Vision model should suggest: "Wrap 'key term' in **bold**"
"""

# Condensed version for vision model prompt (the full catalog above is too long)
VISION_PROMPT_ACTIONS = """
## Available Actions (use EXACT syntax):

**Width (for cramped text):**
- body_width:full → 9.4" width (maximum)
- body_width:wide → 9.0" width

**Font Size:**
- body_font_size:small/medium/large → 12/16/20pt
- title_font_size:small/medium/large → 28/32/40pt

**Spacing:**
- line_spacing:1.5 → comfortable reading
- para_spacing:loose → more space between bullets

**Layout:**
- set_layout:two_column → split content
- split_slide → too much content, needs 2 slides
"""



# =============================================================================
# DETERMINISTIC ACTION HANDLERS
# =============================================================================

# Preset value mappings
BODY_WIDTH_PRESETS = {
    "full": 9.4,
    "wide": 9.0,
    "normal": 8.0,
    "narrow": 6.0
}

BODY_LEFT_FOR_WIDTH = {
    "full": 0.3,
    "wide": 0.5,
    "normal": 1.0,
    "narrow": 2.0
}

FONT_SIZE_PRESETS = {
    "large": 20,
    "medium": 16,
    "small": 12
}

TITLE_FONT_SIZE_PRESETS = {
    "large": 40,
    "medium": 32,
    "small": 28
}

LINE_SPACING_PRESETS = {
    "single": 1.0,
    "1.15": 1.15,
    "1.5": 1.5,
    "double": 2.0
}

PARA_SPACING_PRESETS = {
    "tight": 6,
    "normal": 12,
    "loose": 18
}

TEXT_PADDING_PRESETS = {
    "loose": 0.5,
    "normal": 0.25,
    "tight": 0.1,
    "none": 0.0
}


def _apply_action(content: Dict[str, Any], action: str) -> Dict[str, Any]:
    """Apply a single action to content. Deterministic, no LLM."""
    
    # IMPORTANT: Deep copy to avoid mutating original
    content = copy.deepcopy(content)
    
    # Get or create visual_overrides
    overrides = content.get("visual_overrides", {})
    
    # =========================================================================
    # BODY WIDTH ACTIONS
    # =========================================================================
    if action.startswith("body_width:"):
        value = action.split(":")[1]
        if value in BODY_WIDTH_PRESETS:
            overrides["body_width"] = BODY_WIDTH_PRESETS[value]
            overrides["body_left"] = BODY_LEFT_FOR_WIDTH[value]
        else:
            try:
                overrides["body_width"] = float(value)
            except ValueError:
                pass
        content["visual_overrides"] = overrides
        return content
    
    if action.startswith("body_left:"):
        try:
            overrides["body_left"] = float(action.split(":")[1])
            content["visual_overrides"] = overrides
        except ValueError:
            pass
        return content
    
    if action.startswith("body_top:"):
        try:
            overrides["body_top"] = float(action.split(":")[1])
            content["visual_overrides"] = overrides
        except ValueError:
            pass
        return content
    
    # =========================================================================
    # FONT SIZE ACTIONS
    # =========================================================================
    if action.startswith("body_font_size:"):
        value = action.split(":")[1]
        if value in FONT_SIZE_PRESETS:
            overrides["font_size"] = FONT_SIZE_PRESETS[value]
        else:
            try:
                size = int(value)
                overrides["font_size"] = max(10, min(24, size))
            except ValueError:
                pass
        content["visual_overrides"] = overrides
        return content
    
    # Legacy support for font_size:N
    if action.startswith("font_size:"):
        try:
            size = int(action.split(":")[1])
            overrides["font_size"] = max(10, min(24, size))
            content["visual_overrides"] = overrides
        except ValueError:
            pass
        return content
    
    if action.startswith("title_font_size:"):
        value = action.split(":")[1]
        if value in TITLE_FONT_SIZE_PRESETS:
            overrides["title_font_size"] = TITLE_FONT_SIZE_PRESETS[value]
        else:
            try:
                size = int(value)
                overrides["title_font_size"] = max(24, min(44, size))
            except ValueError:
                pass
        content["visual_overrides"] = overrides
        return content
    
    if action == "increase_font":
        current = overrides.get("font_size", 18)
        overrides["font_size"] = min(24, current + 2)
        content["visual_overrides"] = overrides
        return content
    
    if action == "decrease_font":
        current = overrides.get("font_size", 18)
        overrides["font_size"] = max(10, current - 2)
        content["visual_overrides"] = overrides
        return content
    
    # =========================================================================
    # SPACING ACTIONS
    # =========================================================================
    if action.startswith("line_spacing:"):
        value = action.split(":")[1]
        if value in LINE_SPACING_PRESETS:
            overrides["line_spacing"] = LINE_SPACING_PRESETS[value]
        else:
            try:
                overrides["line_spacing"] = float(value)
            except ValueError:
                pass
        content["visual_overrides"] = overrides
        return content
    
    if action.startswith("para_spacing:"):
        value = action.split(":")[1]
        if value in PARA_SPACING_PRESETS:
            overrides["para_spacing"] = PARA_SPACING_PRESETS[value]
        else:
            try:
                overrides["para_spacing"] = int(value)
            except ValueError:
                pass
        content["visual_overrides"] = overrides
        return content
    
    if action.startswith("text_padding:"):
        value = action.split(":")[1]
        if value in TEXT_PADDING_PRESETS:
            overrides["text_padding"] = TEXT_PADDING_PRESETS[value]
        else:
            try:
                overrides["text_padding"] = float(value)
            except ValueError:
                pass
        content["visual_overrides"] = overrides
        return content
    
    # =========================================================================
    # ALIGNMENT ACTIONS
    # =========================================================================
    if action.startswith("text_align:"):
        value = action.split(":")[1]
        if value in ["left", "center", "right", "justify"]:
            overrides["text_align"] = value
            content["visual_overrides"] = overrides
        return content
    
    # =========================================================================
    # LAYOUT ACTIONS
    # =========================================================================
    if action.startswith("set_layout:"):
        layout = action.split(":")[1]
        content["forced_layout"] = layout
        return content
    
    # Legacy support for content_width
    if action.startswith("content_width:"):
        value = action.split(":")[1]
        if value in BODY_WIDTH_PRESETS:
            overrides["body_width"] = BODY_WIDTH_PRESETS[value]
            overrides["body_left"] = BODY_LEFT_FOR_WIDTH[value]
        content["visual_overrides"] = overrides
        return content
    
    # =========================================================================
    # FONT STYLE ACTIONS
    # =========================================================================
    if action.startswith("body_font_bold:"):
        value = action.split(":")[1]
        overrides["body_font_bold"] = (value == "on")
        content["visual_overrides"] = overrides
        return content
    
    if action.startswith("body_font_italic:"):
        value = action.split(":")[1]
        overrides["body_font_italic"] = (value == "on")
        content["visual_overrides"] = overrides
        return content
    
    if action.startswith("body_font_color:"):
        value = action.split(":")[1]
        if len(value) == 6:  # Valid hex color
            overrides["body_font_color"] = value
            content["visual_overrides"] = overrides
        return content
    
    if action.startswith("title_font_bold:"):
        value = action.split(":")[1]
        overrides["title_font_bold"] = (value == "on")
        content["visual_overrides"] = overrides
        return content
    
    if action.startswith("title_font_color:"):
        value = action.split(":")[1]
        if len(value) == 6:
            overrides["title_font_color"] = value
            content["visual_overrides"] = overrides
        return content
    
    # =========================================================================
    # SHAPE APPEARANCE ACTIONS
    # =========================================================================
    if action.startswith("body_fill:"):
        value = action.split(":")[1]
        overrides["body_fill"] = None if value == "none" else value
        content["visual_overrides"] = overrides
        return content
    
    if action.startswith("body_border:"):
        value = action.split(":")[1]
        overrides["body_border"] = None if value == "none" else value
        content["visual_overrides"] = overrides
        return content
    
    if action.startswith("body_border_width:"):
        try:
            overrides["body_border_width"] = float(action.split(":")[1])
            content["visual_overrides"] = overrides
        except ValueError:
            pass
        return content
    
    if action.startswith("title_fill:"):
        value = action.split(":")[1]
        overrides["title_fill"] = None if value == "none" else value
        content["visual_overrides"] = overrides
        return content
    
    # =========================================================================
    # IMAGE POSITIONING ACTIONS
    # =========================================================================
    if action.startswith("image_width:"):
        try:
            overrides["image_width"] = float(action.split(":")[1])
            content["visual_overrides"] = overrides
        except ValueError:
            pass
        return content
    
    if action.startswith("image_height:"):
        try:
            overrides["image_height"] = float(action.split(":")[1])
            content["visual_overrides"] = overrides
        except ValueError:
            pass
        return content
    
    if action.startswith("image_left:"):
        try:
            overrides["image_left"] = float(action.split(":")[1])
            content["visual_overrides"] = overrides
        except ValueError:
            pass
        return content
    
    if action.startswith("image_top:"):
        try:
            overrides["image_top"] = float(action.split(":")[1])
            content["visual_overrides"] = overrides
        except ValueError:
            pass
        return content
    
    # =========================================================================
    # WORD WRAP ACTION
    # =========================================================================
    if action.startswith("word_wrap:"):
        value = action.split(":")[1]
        overrides["word_wrap"] = (value == "on")
        content["visual_overrides"] = overrides
        return content
    
    # =========================================================================
    # CONTENT ACTIONS
    # =========================================================================
    if action == "split_slide":
        content["split_required"] = True
        return content
    
    # Unknown action - log and skip
    logging.warning(f"Unknown action: {action}")
    return content



# =============================================================================
# DESIGN AGENT CLASS
# =============================================================================

class DesignAgent:
    def __init__(self, use_gemini: bool = True):
        """
        Initialize DesignAgent.
        
        Args:
            use_gemini: If True, use Gemini API for vision (better quality).
                       Falls back to local Gemma if Gemini unavailable.
        """
        self.logger = logging.getLogger("DesignAgent")
        
        # Try Gemini first for vision (better quality)
        self.gemini = GeminiClient() if use_gemini else None
        self.use_gemini = use_gemini and self.gemini and self.gemini.is_available()
        
        if self.use_gemini:
            self.logger.info("DesignAgent using Gemini API for vision")
        else:
            self.logger.info("DesignAgent using local Gemma for vision")
            self.llm = GemmaClient()


    def analyze_slide(self, image_path: str, slide_content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes a rendered slide image and suggests specific actions.
        
        Uses vision model with FULL documentation of available features.
        """
        if not Path(image_path).exists():
            self.logger.error(f"Image not found: {image_path}")
            return {"error": "Image not found", "issues": [], "suggested_actions": [], "score": 0}
            
        self.logger.info(f"Analyzing slide image: {image_path}")
        
        # Current state for context
        current_overrides = slide_content.get("visual_overrides", {})
        current_font = current_overrides.get("font_size", 18)
        current_layout = slide_content.get("forced_layout", "standard_list")
        current_body_width = current_overrides.get("body_width", 8.0)
        num_bullets = len(slide_content.get('bullet_points', []))
        
        # Check context flags
        font_is_optimized = current_overrides.get("_auto_fitted", False)
        has_template = slide_content.get("_has_template", False)
        
        # Build constraints list
        constraints = []
        if has_template:
            constraints.append("- Template/Slide Master is loaded:")
            constraints.append("  • Backgrounds, header colors, footers: DO NOT modify")
            constraints.append("  • Header font: can reduce by 1-2pt if cramped, use sparingly")
            constraints.append("  • Body font: prefer master's default, reduce if overflow, avoid exceeding")


        if font_is_optimized:
            constraints.append("- Font size is auto-optimized to maximum. Consider width/spacing changes instead")
        
        constraints_text = "\n".join(constraints) if constraints else "- No special constraints"
        
        # Show what's already been applied
        already_applied = []
        if current_body_width != 8.0:
            already_applied.append(f"body_width already at {current_body_width}\"")
        if current_overrides.get("line_spacing"):
            already_applied.append(f"line_spacing already at {current_overrides.get('line_spacing')}")
        if current_overrides.get("para_spacing"):
            already_applied.append(f"para_spacing already at {current_overrides.get('para_spacing')}")
        
        already_applied_text = "\n".join(f"  - {x}" for x in already_applied) if already_applied else "  (none)"
        
        prompt = f"""You are a conservative Presentation Design reviewer. Your job is to identify ONLY critical issues.

## Current Slide State:
- Bullets: {num_bullets}
- Font Size: {current_font}pt

## ALREADY APPLIED (do not re-suggest):
{already_applied_text}

## CRITICAL RULES - READ CAREFULLY:
1. **DO NOT increase font size** - it causes text overflow and looks unprofessional
2. **DO NOT suggest changes if the slide looks reasonable** - the template is well-designed
3. **Preserve bottom margin** - space must remain for footnotes
4. If content fits well and is readable, return score 8+ with EMPTY suggested_actions

## ONLY suggest fixes for these SEVERE problems:

1. **TEXT OVERFLOW** - Content is cut off or runs off the slide
   → FIX: `split_slide` (split into multiple slides)

2. **COMPLETELY UNREADABLE** - Font is impossibly small (under 12pt)
   → FIX: `body_font_size:medium` (16pt) - ONLY if severely unreadable

## Output (JSON only):
```json
{{
    "issues": ["describe severe problems ONLY, or empty if none"],
    "score": 1-10,
    "suggested_actions": []
}}
```

IMPORTANT: If the slide looks professional and readable, return score 8+ with NO suggested actions.
A well-designed template slide with proper margins is ALREADY good - don't mess with it.
"""




        
        # Call vision model - use Gemini if available, fallback to Gemma
        if self.use_gemini:
            self.logger.info("Using Gemini API for vision analysis")
            response = self.gemini.generate_with_image(prompt, image_path)
            response_text = response if response else ""
        else:
            response = self.llm.generate(prompt, images=[image_path], max_tokens=512)
            # Process response
            if hasattr(response, 'text'):
                response_text = response.text
            elif hasattr(response, '__str__'):
                response_text = str(response)
            else:
                response_text = response

        
        # Store raw response
        raw_response = response_text.strip()
        
        # Extract JSON from response
        json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            json_match = re.search(r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})', response_text, re.DOTALL)
            json_str = json_match.group(1).strip() if json_match else "{}"
        
        # Debug output
        print("\n" + "="*60)
        print("VISION MODEL RESPONSE:")
        print("="*60)
        print(raw_response[:800] + "..." if len(raw_response) > 800 else raw_response)
        print("="*60)
        print("EXTRACTED JSON:", json_str[:300])
        print("="*60 + "\n")
        
        # Parse JSON
        try:
            critique = json.loads(json_str)
            critique['_raw_response'] = raw_response
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON parse failed: {e}")
            critique = {
                "error": f"JSON parse failed: {str(e)}",
                "issues": ["Failed to parse vision model response"],
                "suggested_actions": [],
                "score": 0,
                "_raw_response": raw_response
            }
        
        return critique

    def apply_fixes(self, content: Dict[str, Any], critique: Dict[str, Any]) -> Dict[str, Any]:
        """
        Applies fixes DETERMINISTICALLY based on suggested actions.
        
        NO LLM call - just executes the actions from the catalog.
        """
        new_content = copy.deepcopy(content)
        actions = critique.get("suggested_actions", [])
        
        self.logger.info(f"Applying {len(actions)} actions: {actions}")
        
        for action in actions:
            new_content = _apply_action(new_content, action)
        
        return new_content
