# Briefing atlas

The Pages workflow regenerates `/insights/` from the checked-out approved
[reports](../../reports/) on every push to `main`. Pull requests run the same
tests and builds without deploying. Manual dispatch deploys only from `main`.

This is a repeatable pipeline, not a committed HTML snapshot. No additional
LLM, embedding service, graph database server, or research-term whitelist is used.

## Build locally

From the repository root, with Python 3.12 and Node.js 22:

```sh
npm ci --prefix tools/brief-atlas --ignore-scripts --no-audit --no-fund
python3 briefing.py build
python3 tools/brief-atlas/build.py
```

Open `site/insights/index.html` in a browser. Assets are embedded, so local files
and GitHub Pages work without a runtime data API or chart CDN. The shared site
font stylesheet uses Google Fonts with local fallbacks, just like the archive.
Navigation and source links are relative to the generated site.

The existing [Pages workflow](../../.github/workflows/pages.yml) validates the
reports, builds the briefing site, builds the atlas, and uploads the combined
`site/` artifact. The shared header includes an always-visible **탐색** link.
Both builders reuse [site-header.html](../../site-header.html),
[site-theme.css](../../site-theme.css), and [site-theme.js](../../site-theme.js)
for the logo, navigation, typography, light/dark theme and search.

## Outputs

All outputs are generated under the ignored `site/insights/` directory:

- `graph.json`: stable node IDs, typed nodes, source-item references,
  co-occurrence links, and weekly/monthly aggregates.
- `evidence.json`: original summaries, topics, application notes, and limitations.
- `index.html`: self-contained recent-change heatmap and source list, with
  one context-selected relationship view when the evidence supports it.
- `overview.html`: a script-free overview.
- `D3-LICENSE.txt`: the bundled renderer's license.

The builder rereads all current reports. Corrections and deletions therefore
remove stale counts and orphaned nodes rather than accumulating duplicate state.
The same inputs, source revision, and renderer version produce identical files.
Existing URL normalization and item-anchor helpers from
[briefing.py](../../briefing.py) are reused.
Template slots are validated before a single substitution pass, so token-like
strings in report text remain literal data rather than additional template slots.

## Extraction and presentation

- The default view compares the latest seven archive days with the preceding
  seven, within the selected section, tag and node type. The first heatmap ranks
  positive percentage-point changes in the share of unique source items, requiring
  at least two unique items and two observation dates in the period. Observation
  dates are counted before deduplicating the displayed evidence, so republishing
  a source cannot remove an otherwise qualifying topic. Repeated publication of
  one item alone is not sufficient. Raw prior/current counts are shown beside the change; these are
  archive emphasis changes, not predictions or claims of technology novelty.
- Comparisons require a nonempty denominator, at least 80% of report days and
  no more than 20% unavailable coverage slots in both windows. Without a baseline,
  counts remain browsable but changes show `—` and the comparison is marked
  unavailable. `등장량` restores count-based exploration; search can find any
  observed node, not only the rising subset.
- Presentation follows the task rather than offering multiple layouts for the
  same content: recent changes use the heatmap; selecting a topic opens its source
  list. A relationship panel appears only when at least two distinct source
  identities support a co-occurrence link in the selected interval.
- Only the selected topic's connected neighborhood, within the selected node
  type, is used. Sparse repeated relations use a network; at least six connected
  nodes with edge density of 0.4 or greater use a matrix. The density is the number
  of repeated undirected edges divided by the number of possible pairs. These
  deterministic presentation thresholds are readability rules, not significance
  or trend scores. No layout tabs or LLM-based selection are involved.
- Single-source links, isolated topics and the full source inventory do not show a
  relationship diagram. Their source items remain readable. Tree and cluster
  algorithms remain internal renderer capabilities; the page does not force
  hierarchy or semantic grouping onto co-occurrence data.
- Multiword `topics` entries supply phrase candidates. Literal matches in
  titles and topics connect entries across sections. Case, whitespace, and
  hyphens are normalized; the longest overlapping phrase in a field wins.
- GitHub source URLs supply repository nodes. Title token patterns supply
  names/acronyms. Repository keys normalize case but preserve `.`, `_`, and `-`.
  A single HTTPS clone suffix `.git` is removed so clone and web URLs share a node.
  Repository candidates require HTTPS, a GitHub host, a valid owner/repository
  path, and either the repository root or a supported repository resource
  (releases, issues, pull requests, discussions, code, commits, comparisons,
  actions, security advisories, wiki, branches, or tags). Known GitHub site-level
  routes are rejected centrally. Unknown routes remain in the source inventory
  without a project node; this offline recognizer does not verify existence.
  Common noise tokens and existing broad taxonomy aliases are
  excluded from phrase/name discovery. Editorial tags remain context filters.
- Links mean **co-occurrence in the same briefing entry**, not dependency or
  causation. The tree is a bounded traversal of those links, not an impact model.
- Matrix ordering uses deterministic weighted modularity grouping, not semantic
  topic classifications. The renderer shows a bounded neighborhood (24 nodes on
  desktop, 14 on mobile), and at most 12/8 matrix rows. Counts beside the controls
  indicate displayed versus eligible nodes.
- Explicit selections remain visible even with no observations in the chosen
  interval. The source list stays empty for an explicit zero-count selection and
  the relationship panel is hidden. Matrix limits reserve space for the selected
  node and its counterpart. Changing a filter selects within the current type.
  Tag and node-type filters preserve a heatmap-selected interval; only changing
  a date control or resetting the filters clears that interval.
- A period with only unavailable collection is shown as unobserved, not zero.
  At least one `ok` or `partial` coverage slot is required for an observed value.
- Evidence is deduplicated after matching the selected nodes. Each source keeps
  its latest matching occurrence, and the results are ordered newest first.
  Repeated identical title tokens store one provenance record per name and item;
  distinct original spellings remain available as evidence.
- When a keyboard action replaces or hides its focused control, focus moves to the
  related source panel or node search. Matrix column buttons expose node names to screen readers.
  Chart counts and empty-state markers maintain at least 4.5:1 foreground contrast.
- Fit-to-screen uses the current graph bounds, including labels and dragged nodes,
  rather than resetting only the zoom transform.
- Raw names can be ambiguous, phrases can be missed, and different URLs for
  the same event can remain separate. Counts describe this archive, not the
  wider technology market. All entries remain accessible in the source inventory,
  including entries without extracted nodes.

D3 is pinned in [package-lock.json](package-lock.json). It is installed during
the build and embedded in the page, not fetched by readers. Generated datasets,
screenshots, browser caches, and dependency directories must not be committed.

## Tests

```sh
node tools/brief-atlas/node_modules/playwright/cli.js install chromium --only-shell
python3 -m unittest discover -s tests -q
node --test tests/*.test.cjs
python3 -m unittest discover -s tools/brief-atlas -p 'test_*.py' -q
node --test tools/brief-atlas/*.test.cjs
```

Tests cover automatic new-term discovery, deletion/republication handling,
provenance, relative source links, offline builds and byte reproducibility across
separate Python processes with different hash seeds, date filtering,
co-occurrence intersections, precomputed series reuse without item reads,
section-specific collection failures, literal template tokens and mixed-case
script-end tags, syntax-parsed literal DOM references, matrix column names, empty-state
contrast, tree/matrix projections, and deterministic layouts. Browser tests use
the real stylesheet and renderer, check computed colors on desktop/mobile, and
verify that higher-specificity, inline, and custom-property contrast regressions
are rejected. They also check matrix row indices, connections over cluster fills,
and pagination reset when selecting another connection. CI installs the pinned
headless browser and its system dependencies.
The browser suite also checks initialized interface text and label attributes
(including runtime-concatenated strings), keyboard focus after controls disappear,
and pagination immediately before/after edge selection.
