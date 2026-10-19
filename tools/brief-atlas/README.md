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
and GitHub Pages work without a runtime API or CDN. Navigation and source links
are relative to the generated site.

The existing [Pages workflow](../../.github/workflows/pages.yml) validates the
reports, builds the briefing site, builds the atlas, and uploads the combined
`site/` artifact. The report navigation includes an **탐색** link.

## Outputs

All outputs are generated under the ignored `site/insights/` directory:

- `graph.json`: stable node IDs, typed nodes, source-item references,
  co-occurrence links, and weekly/monthly aggregates.
- `evidence.json`: original summaries, topics, application notes, and limitations.
- `index.html`: self-contained interactive network, tree, adjacency matrix,
  cluster, timeline, and source views.
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

- Multiword `topics` entries supply phrase candidates. Literal matches in
  titles and topics connect entries across sections. Case, whitespace, and
  hyphens are normalized; the longest overlapping phrase in a field wins.
- GitHub source URLs supply repository nodes. Title token patterns supply
  names/acronyms. Repository keys normalize case but preserve `.`, `_`, and `-`.
  Common noise tokens and existing broad taxonomy aliases are
  excluded from phrase/name discovery. Editorial tags remain context filters.
- Links mean **co-occurrence in the same briefing entry**, not dependency or
  causation. The tree is a bounded traversal of those links, not an impact model.
- Cluster colors come from deterministic weighted modularity grouping of the
  displayed subgraph. They are not semantic topic classifications.
- The renderer shows a bounded neighborhood (24 nodes on desktop, 14 on
  mobile), with separate limits for trees and matrices. Counts beside the
  controls indicate displayed versus eligible nodes.
- Explicit selections remain visible even with no observations in the chosen
  interval. Matrix limits reserve space for the selected node and its selected
  counterpart. Changing a filter automatically selects within the current type.
- When keyboard selection replaces a focused control, focus moves to the updated
  source panel. Chart count labels maintain at least 4.5:1 foreground contrast.
- Raw names can be ambiguous, phrases can be missed, and different URLs for
  the same event can remain separate. Counts describe this archive, not the
  wider technology market. All entries remain accessible in the source inventory,
  including entries without extracted nodes.

D3 is pinned in [package-lock.json](package-lock.json). It is installed during
the build and embedded in the page, not fetched by readers. Generated datasets,
screenshots, browser caches, and dependency directories must not be committed.

## Tests

```sh
python3 -m unittest discover -s tests -q
node --test tests/*.test.cjs
python3 -m unittest discover -s tools/brief-atlas -p 'test_*.py' -q
node --test tools/brief-atlas/analytics.test.cjs tools/brief-atlas/graph-views.test.cjs
```

Tests cover automatic new-term discovery, deletion/republication handling,
provenance, relative source links, offline/reproducible builds, date filtering,
co-occurrence intersections, precomputed series reuse without item reads,
section-specific collection failures, literal template tokens, DOM reference
quote styles, tree/matrix projections, and deterministic layouts.
