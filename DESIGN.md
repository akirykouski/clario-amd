---
name: Clario
description: A translucent seven-day organizer in liquid glass, on an icy ground lit by slow colour light.
colors:
  ice: "#E9F3F6"
  ice-clinic: "#ECEEF8"
  panel: "#FFFFFF"
  ink: "#14323A"
  ink-clinic: "#1A1F3A"
  muted: "#45616A"
  muted-clinic: "#4C5370"
  aqua: "#3FB8C9"
  lilac: "#8A7CF0"
  coral: "#FF8A6B"
  accent: "#0E7380"
  accent-clinic: "#4F42C8"
  accent-ink: "#FFFFFF"
  weak: "#56677A"
  moderate: "#A86A12"
  strong: "#A23B52"
  glass: "rgba(255, 255, 255, 0.48)"
  glass-strong: "rgba(255, 255, 255, 0.72)"
  glass-edge: "rgba(255, 255, 255, 0.85)"
  glass-rim: "rgba(20, 50, 58, 0.10)"
  line: "rgba(20, 50, 58, 0.14)"
  accent-soft: "rgba(63, 184, 201, 0.22)"
  danger-tint: "rgba(255, 138, 107, 0.16)"
  amber-tint: "rgba(255, 196, 92, 0.18)"
typography:
  display:
    fontFamily: "Funnel Display, system-ui, sans-serif"
    fontSize: "44px"
    fontWeight: 600
    lineHeight: 1.06
    letterSpacing: "-0.035em"
  headline:
    fontFamily: "Funnel Display, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Funnel Display, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Funnel Sans, system-ui, sans-serif"
    fontSize: "16.5px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Funnel Sans, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.3
  code:
    fontFamily: "Geist Mono, ui-monospace, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  input: "16px"
  card: "22px"
  panel: "28px"
  tray: "32px"
  pill: "999px"
spacing:
  gap-compartment: "14px"
  card-padding: "20px"
  control-height: "44px"
  input-height: "46px"
components:
  button:
    backgroundColor: "{colors.glass-strong}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 20px"
    height: "44px"
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.pill}"
    padding: "0 20px"
    height: "44px"
  input:
    backgroundColor: "{colors.glass-strong}"
    textColor: "{colors.ink}"
    rounded: "{rounded.input}"
    padding: "10px 16px"
    height: "46px"
  card:
    backgroundColor: "{colors.glass-strong}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "20px"
  glass-panel:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
  chip-filled:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "4px 12px"
  chip-review:
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "4px 12px"
  chip-struck:
    textColor: "{colors.muted}"
    rounded: "{rounded.pill}"
    padding: "4px 12px"
  compartment:
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    height: "116px"
---

# Design System: Clario

## Overview

**Creative North Star: "The Pill Organizer in Glass"**

Clario is a translucent Y2K seven-day organizer in liquid glass. The week is always visible as seven candy-plastic compartments; the chosen day swells open and joins a large glass tray below. The ground is icy and lit by three slow colour fields. Panels are frosted glass with a bright top edge and a soft, low shadow. Both apps share this one light world (desk use, daylight or office light): the patient app leads with aqua, the clinic console leads with lilac.

The feel is calm and precise, never alarming. Density is moderate and desktop-first. The system rejects the stock health-app pattern of flat white cards on grey.

**Key Characteristics:**
- Icy ground with per-app ambient light (patient aqua-led, clinic lilac-led).
- Frosted glass for large surfaces; gradient-faked glass for small controls.
- Seven compartments cycling aqua, lilac, coral; the selected one turns clear glass and joins the tray.
- Fixed capsule state marks: filled, hollow ring, struck.
- One liquid indicator (shared-layout glide) for nav and selected day.
- Deep teal ink (indigo ink in the clinic), AA contrast on ice and on glass.

## Colors

A pale cool ground, deep ink, and three candy hues used as material, with one deeper accent for text and controls.

### Primary
- **Deep Aqua Accent** (`accent`, #0E7380): patient-app buttons, links, focus ring, active nav text, role badge text. Passes AA on ice and glass.
- **Clinic Indigo Accent** (`accent-clinic`, #4F42C8): replaces the accent when `data-app="clinic"` is set on the root.

### Secondary
- **Candy Aqua** (`aqua`, #3FB8C9): compartment colour, filled capsule, nav indicator, patient ambient light. A material colour, not a text colour.
- **Candy Lilac** (`lilac`, #8A7CF0): compartment colour, clinic ambient light.
- **Candy Coral** (`coral`, #FF8A6B): compartment colour, danger tint.

### Neutral
- **Ice** (`ice`, #E9F3F6): page ground and theme-color. Clinic: **Lavender Ice** (`ice-clinic`, #ECEEF8).
- **Deep Teal Ink** (`ink`, #14323A): all text. Clinic: **Midnight Indigo Ink** (`ink-clinic`, #1A1F3A).
- **Slate Teal Muted** (`muted`, #45616A): secondary text. Clinic: `muted-clinic` (#4C5370).
- **Glass tints** (`glass`, `glass-strong`, `glass-edge`, `glass-rim`, `line`): white at 48% and 72% fills, an 85% white edge, and ink at 10 to 14% for rims and dividers.
- **Evidence ramp** (`weak` #56677A, `moderate` #A86A12, `strong` #A23B52): confidence and severity marks only. `moderate` also drives the amber card tint and the redaction ring.

### Named Rules
**The Ambient Light Rule.** Colour comes from three blurred fields behind the glass (`--amb1..3`), not from flat fills on panels. The fields drift on transform only.

**The Two-Accent Rule.** Aqua leads in the patient app, lilac in the clinic. Switch with `data-app`, never by recolouring components.

**The Candy Is Material Rule.** Aqua, lilac and coral colour surfaces. Text always uses ink, muted, or the deep accent.

## Typography

**Display Font:** Funnel Display (system-ui fallback), headings h1 to h3
**Body Font:** Funnel Sans (system-ui fallback), with `ss01` and `cv11` features
**Label/Mono Font:** Geist Mono, for HPO codes and fingerprints only

**Character:** One neo-grotesk family in two optical cuts; the display cut is tight and confident, the text cut is open and readable for tired eyes.

### Hierarchy
- **Display** (600, 34px mobile / 44px, 1.06, -0.035em): the Today prompt over the note field.
- **Headline** (600, 24px, 1.2): section titles such as recent notes; clinic page h1 is 30px.
- **Title** (600, 20px): panel headings such as "What we understood".
- **Body** (400, 16.5px, 1.55): notes and prose. Note field text is 19px.
- **Label** (600, 15px; 13px for dates, captions and weekday): buttons, nav, field labels.
- **Day numeral** (600, 30px, -0.03em, tabular): compartment date.
- **Code** (Geist Mono, 12px, muted): HPO ids and fingerprints.

### Named Rules
**The Tabular Rule.** Dates, counts and tables use tabular numerals.

**The Mono Is For Codes Rule.** Geist Mono appears only on identifiers, never on prose or labels.

## Layout

Desktop first. Wide screens use a 264px frosted sidebar column plus a main column capped at 1180px with 40px side padding; below `lg` the sidebar becomes a frosted top bar with a bottom-padded body. The week is a strict 7-column grid (gap 10px, 14px from `sm`), the visible armature of the screen. Today's tray splits roughly two thirds (note field and save) to one third (understood capsules). Cards use 20px padding. Controls are at least 44px tall (inputs 46px, small buttons 34px). Small widths stay usable but are not the design target.

## Elevation & Depth

Depth is hybrid: translucency plus a bright inset top edge, with soft, long, low-opacity shadows in ink tint.

### Shadow Vocabulary
- **Glass** (`--shadow-glass`: inset 1px white top edge, faint inset bottom, `0 18px 40px -22px` ink at 35%, `0 2px 6px -2px` ink at 8%): panels, cards, tray.
- **Lift** (`--shadow-lift`: inset top edge, `0 24px 48px -24px` ink at 45%): raised overlays.
- **Control** (inset white 1px, `0 8px 18px -12px` ink at 45%; hover `0 12px 22px -12px`): buttons.
- **Compartment** (inset white top, inset coloured bottom, `0 16px 26px -14px` hue at 75%): each lid, tinted by its own hue.

### Named Rules
**The Large Surfaces Only Rule.** `backdrop-filter: blur(22px) saturate(170%)` is allowed only on large surfaces (panels, sidebar, top bar). Small controls fake glass with white gradients.

**The Soft Offset Rule.** Shadows are long, negative-spread and ink-tinted. No hard-edged or coloured offset shadows.

## Shapes

Pills for anything you press or read as a token (999px): buttons, capsules, role badge. Rounded rectangles scale with size: inputs 16px, cards and compartments 22px, glass panels 28px, the tray 32px. The tray's top corner is squared (0 radius) beneath the first or last day when that day is open, so the neck joins flush. The neck has concave 30px shoulders. Each compartment carries a top hinge, a lid specular streak, and a bottom latch (hidden when selected).

## Components

### Buttons
- **Shape:** full pill, 44px tall (34px small), 20px side padding, 15px semibold ink.
- **Default:** glass pill with white gradient and inset top edge. One diagonal sheen sweep (900ms) on hover; press scales to 0.965.
- **Primary:** liquid accent gradient from lighter top to deeper bottom with white text and an accent glow.
- **Quiet:** transparent, accent text, underlined, no sheen.
- **Disabled:** 50% opacity.

### Inputs / Fields
- 16px radius, 46px minimum height, 62% white fill, inset shadow and white lower highlight, 1px rim. Focus lifts the fill to 85% white with a 3px soft accent ring. Note field is 22px radius with 19px text. Caret uses the accent.

### Cards / Containers
- **Card:** 22px radius, 20px padding, white gradient (78% to 56%), glass edge, glass shadow.
- **Accent card:** accent tint at 12% fading out over the first 140px. **Amber card:** same with `moderate`. Used for attention, not decoration.

### Capsules (chips)
- Pill, 14 to 15px medium, white gradient. State marks are fixed system-wide.
- **Filled** (counted): aqua gradient wash, aqua border.
- **Review** (unsure): transparent with a 1.5px ink ring, hollow.
- **Struck** (rejected): line-through in strong at 70%, muted text, faint fill.

### Navigation
- Sidebar items are 46px, 16px radius, semibold 15px; muted by default, ink when active. The active state is a single aqua-wash indicator that glides between items (shared layout, spring 420/32/0.8). Role badge is a pill in accent-soft with accent text.

### Week Organizer (signature)
- Seven compartments, 116px minimum height, cycling aqua, lilac, coral by day index. Hover lifts 3px; the selected day is clear glass, lifted 6px, with its latch removed. A single `.neck` element glides between days (spring 380/30/0.9) and joins the open day to the tray. Future days are disabled at 40% opacity.

## Do's and Don'ts

### Do:
- **Do** keep state marks fixed: filled is confirmed, hollow ring is unsure, struck is rejected.
- **Do** put colour in ambient light and compartments; keep panels near-white glass.
- **Do** use `ease-out` (0.16, 1, 0.3, 1) or `ease-liquid` (0.22, 1, 0.36, 1) for transitions, and framer-motion springs only for the nav indicator and selected-day neck.
- **Do** animate ambient drift on `transform` only, and stop all animation and transition under `prefers-reduced-motion`.
- **Do** keep text on ink, muted, or the deep accent so it holds 4.5:1.
- **Do** keep copy free of em dashes and exclamation marks.

### Don't:
- **Don't** put `backdrop-filter` on chips, buttons, or list items.
- **Don't** use candy aqua, lilac or coral as text colour.
- **Don't** use the stock health-app look of flat white cards on grey.
- **Don't** use Geist Mono for anything but codes and fingerprints.
- **Don't** blend patient aqua and clinic lilac leads on one screen; the root `data-app` decides.
