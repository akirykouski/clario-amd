---
version: 1
slug: "frontend-src-app-tsx"
primary_target: "frontend/src/App.tsx"
related_targets: ["frontend/src/clinic/ClinicApp.tsx"]
---

# Surface brief: Clario app (patient app + clinic console)

Scope: the whole React app in frontend/ (patient app and clinic console share one build), plus the GitHub Pages landing. Mode: Operate. Desktop browser first.

Audience and job: patients write and check daily notes and share them before a visit; clinicians review a shared package and sign a brief. Constraints: PRODUCT.md (never diagnose, quotes as source, condition names clinician-only, EN/IT, no em dashes or exclamation marks in copy).

Approved reference: .impeccable/mocks/decision/assigned.png (desktop Today screen). The user approved this look in words and asked to build it in code directly, with optimized liquid-glass animation; no further comp rounds.

## Direction contract

THESIS: The diary is a translucent Y2K seven-day organizer in liquid glass: the week is always visible as seven candy-plastic compartments and the chosen day swells open into a glass tray. It refuses the stock health-app list of white cards.

OWN-WORLD: Icy ground with slow drifting colour light; frosted glass panels with a bright top edge and soft offset shadow; candy-plastic compartments in aqua, lilac and coral cycling through the week; deep teal ink; one neo-grotesk face; capsules for terms. State marks: filled = confirmed, hollow ring = unsure, struck = rejected, sealed = shared. Clinic uses the same world with lilac leading.

STORY: The patient sees the week at a glance, opens a day, writes, and sees what Clario understood in capsules they can correct. The clinician sees the same glass language as a calm review console.

FIRST VIEWPORT: Frosted sidebar left (wordmark, nav with a liquid indicator, privacy, language, lock). Main: the week organizer across the top, today's compartment lid lifted and joined to a large glass tray below; left two thirds of the tray holds the note field and save action, right third holds "What we understood" capsules for the selected day. Recent notes follow below the fold.

FORM: Pill organizer (assigned, position 5 on the grounded list), seed key 72e6c9a7. Raises: fixed state marks (timetable), one dominant compartment per screen (zoo map), the 7-column grid as visible armature (Crouwel).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

Motion: one liquid indicator (shared-layout glide) for nav and the selected day; press squish and a single sheen sweep on hover for glass controls; ambient light drifts on the compositor only; everything parks under prefers-reduced-motion. backdrop-filter only on large surfaces.
