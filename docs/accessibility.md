# Operator console accessibility

AgentHub's six dependency-free operator consoles use semantic HTML and progressive
enhancement. Their baseline targets WCAG 2.2 AA keyboard, structure, status, and
contrast expectations without claiming formal certification.

## Implemented behavior

- Every page has a first-focusable skip link and a programmatically focusable main
  landmark.
- Native links, buttons, inputs, textareas, and selects retain visible high-contrast
  focus indicators and keyboard behavior.
- Loading and refresh regions expose `aria-busy`; polite atomic status regions announce
  completed work, while failed requests switch to an alert announcement.
- Action buttons are disabled while their request is in flight. Canary and rollback
  actions state the affected operation in their accessible names.
- Tables have captions and scoped column headings. Candidate-traffic meters expose
  progress-bar semantics rather than relying on color or width alone.
- Empty states explain whether registry, evaluation, delivery, incident, cost, or
  telemetry data has not been recorded.
- Gate, canary, and incident outcomes use text and symbols in addition to color.
- The delivery console labels in-process spend as measured and its hard-coded demo
  rate card as an illustrative what-if projection.

Static contracts in `tests/contract/test_web_accessibility.py` prevent removal of the
landmarks, live-region semantics, table metadata, error/loading states, and truthful
cost labels. API contract and end-to-end tests cover the server-rendered files and the
data contracts consumed by the pages.

## Manual release check

Before a tagged release, serve the application with `make run` and check each console
at 200% browser zoom:

1. Press Tab once, follow **Skip to main content**, then traverse every interactive
   element without a pointer.
2. Confirm focus is never hidden or trapped and control order follows the visual order.
3. Exercise an empty database, a failed API request, and a populated demo. Confirm the
   loading, empty, failure, and success messages are announced by a screen reader.
4. Inspect narrow layouts at 320 CSS pixels. Content may scroll horizontally inside
   data-table wrappers, but page controls and primary content must remain usable.
5. Confirm action names and current incident selection are understandable without
   color.

## Known limits

The consoles have not undergone an external accessibility audit and do not promise a
specific assistive-technology/browser support matrix. Grafana is a separate product
with its own accessibility behavior. Dates use the operator's browser locale, and
large audit tables intentionally use a labelled horizontal scrolling region on small
screens.
