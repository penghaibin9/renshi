# Product Design QA — Secondary Workspaces V4

- Source visual truth: `/mnt/data/Yueke_University_HR_R2_Unified_Brand_V3_20260918_ContactSheet.png`
- Implementation evidence: `/mnt/data/hr_detail_polish_v4/evidence/secondary_workspaces_v4_contact_sheet.png`
- Combined comparison: `/mnt/data/hr_detail_polish_v4/evidence/designqa_v3_system_vs_v4_details.png`
- Before/after evidence: `/mnt/data/hr_detail_polish_v4/evidence/secondary_workspaces_v4_before_after.png`
- Viewport: 1440 × 1024 CSS px, deviceScaleFactor 1
- State: desktop school-admin / HR-teacher representative states; browser fixtures use real project CSS and the modified production JS for HR04, HR05 and HR16.
- Important evidence limit: Django is not installed in this sandbox, so these are Chromium frontend regression captures with representative data, not a claim of a live Django + MySQL authenticated E2E run.

## Full-view comparison

The V4 detail workspaces preserve Unified Brand V3's single blue brand system, neutral surfaces, compact typography, low-shadow visual language and semantic-only success/warning/error colors. The detail pages intentionally diverge in composition because the user requested business-specific workflows rather than repeated card layouts.

## Focused region comparisons

- **HR03 person profile:** identity and navigation moved to a stable left rail; current facts and masked identity are readable as an open fact sheet. The hierarchy is materially clearer without introducing another dashboard layer.
- **HR04 candidate detail:** candidate search/list is now a master pane and the current candidate remains visible in a dedicated detail pane. Selection state has a clear blue edge and the next recruitment steps are exposed without inventing new business facts.
- **HR05 onboarding case:** the five-stage handling position is visible before the case facts; next actions are separated from facts in a dedicated handling rail. The current stage is singular and visually obvious.
- **HR13 expert review:** operator forms are separated from live round/assignment evidence. Review facts, assignment/conflict state and current rounds are no longer mixed into a generic grid of equal cards.
- **HR15 payroll calculation:** the calculation stage is explicit and the central surface reads as a ledger/operator workspace. Formal result, payment and reconciliation remain separated conceptually.
- **HR16 exit handover:** mandatory incomplete items visually precede optional/completed items; guidance communicates the three handling rules before the checklist, while the business path remains visible at right.

## Required fidelity surfaces

### Fonts and typography
Pass. The implementation keeps the V3 system font/fallbacks, compact body scale, restrained title hierarchy, tabular/ledger density, and avoids decorative typography. No new font was introduced.

### Spacing and layout rhythm
Pass. Detail workspaces use 24–28 px major gutters, 10–16 px row rhythm, separators rather than nested card padding, and consistent sticky-rail spacing. HR03/04/05/13/15/16 intentionally have different column structures but share the same spacing grammar.

### Colors and visual tokens
Pass. One brand-blue interaction color is retained. Green/orange/red are used only for success/attention/risk semantics. No module-specific palette was reintroduced.

### Image quality and asset fidelity
Pass / not applicable. These six enterprise HR workspaces do not require decorative imagery. No fake illustration, emoji, handcrafted SVG or placeholder art was introduced.

### Copy and content
Pass. The new copy describes workflow position, safe next steps, evidence boundaries and handling rules. It does not change formal state definitions or claim backend actions that do not exist.

## Interaction evidence

- HR04 candidate master-detail selection: PASS. Clicking the second candidate changes the right detail pane and leaves exactly one selected row.
- HR05 onboarding stage/action rendering: PASS. Five stages render, exactly one current stage is marked, and existing action links remain present.
- HR16 handover priority sorting: PASS. Required incomplete handover precedes optional incomplete and completed/not-required items.
- Chromium page errors across all six after screenshots: none.

## Comparison history

### Iteration 1 findings
- HR04/HR05/HR16 initially rendered blank/error in the screenshot harness because mocks were injected as init scripts after `set_content`; this was a test-harness issue, not product code.
- Fix: inject fixture APIs into the active document before loading the real production JS.
- Post-fix evidence: all six after captures render correctly and every `*_after_console.txt` reports `NO_PAGE_ERRORS`.

No actionable P0/P1/P2 visual or interaction findings remain in the scoped frontend-only work.

## Follow-up polish (P3 only)

- In a real Django login session, validate long real-world names, 10+ candidate rows, unusually long contract/qualification labels, and 125% Windows display scaling.
- Re-run the same six flows against MySQL-backed data before production deployment; this is an environment acceptance step, not a V4 design blocker.

final result: passed
