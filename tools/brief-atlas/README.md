# Briefing reading groups

The [Pages workflow](../../.github/workflows/pages.yml) rebuilds the exploration
page from approved reports on every push to `main`. Pull requests run the same
tests/build without deploying. No LLM, embedding model, external analysis API,
or manually maintained research-topic list is required.

## Build and test

From the repository root (Python 3.12, Node.js 22):

```sh
npm ci --prefix tools/brief-atlas --ignore-scripts --no-audit --no-fund
python3 briefing.py build
python3 tools/brief-atlas/build.py
node tools/brief-atlas/node_modules/playwright/cli.js install chromium --only-shell
python3 -m unittest discover -s tests -q
python3 -m unittest discover -s tools/brief-atlas -p 'test_*.py' -q
node --test tests/*.test.cjs tools/brief-atlas/*.test.cjs
```

Open `site/insights/index.html`. Data and application scripts are embedded; font
loading and local fallbacks match the main site. Header, logo, navigation, search
and light/dark tokens are shared with the archive. The active navigation item is
a plain underlined link, not a permanently pressed-looking button.

## Article-first grouping

[grouping.py](grouping.py) groups source items rather than isolated extracted words:

1. Keep the latest occurrence of each existing canonical source identity for
   textual comparison, retaining all original occurrence indices for filtering.
2. Restrict pair candidates to articles sharing an existing editorial tag.
   Shared tags alone never create a relationship.
3. Build field-weighted lexical TF-IDF vectors from titles (weight 3), each
   original `topics` entry separately (4), and original summaries (0.7).
   Case/Unicode/spacing/hyphens are normalized. Generic taxonomy words, standard
   function words, and version-only tokens do not provide distinctive evidence.
4. Require two informative shared words or a shared multiword phrase in the
   **titles/keywords**, not just summary boilerplate. Then require cosine
   similarity of at least 0.16 and reciprocal top-four-neighbor membership.
5. Form disjoint groups from the strongest pairs. Every pair of articles in a
   group must pass the same criteria; a chain A—B—C cannot imply A—C.
6. Select explanatory terms from shared title/keyword expressions before limiting
   their number, so summary boilerplate cannot displace the naming evidence. Store pair
   scores, shared expressions/tags, original source indices and representatives.
   The score describes lexical resemblance, not semantic truth or confidence.

Groups with paper entries are displayed under **논문 관련**; otherwise those
with CNCF entries appear under **클라우드 네이티브**, and other groups under
**개발·커뮤니티**. Ordering happens within these source-context sections rather
than treating platform releases and research as one frontier ranking.

Unmatched articles remain in **전체 소식**. Group labels may be imperfect, and
equivalent ideas written with different vocabulary can be missed. The strict
thresholds favor precision over coverage; no connection is added just to fill
the screen. These are reading candidates, not a complete topic taxonomy.

## Dates and counts

- The browser anchors `최근 3일 / 7일 / 30일` to **today in Asia/Seoul**, not the
  latest stored report. The real window and latest source date are shown.
- The date anchor refreshes when the tab becomes visible or regains focus. A
  stale archive does not silently shift the window backwards. `이후 미수록`
  explicitly marks the gap between the latest stored report and today.
- Recent emphasis compares equal adjacent periods using unique source counts and
  normalized share differences. A rising group requires two distinct sources and
  two observed dates. Republication does not remove earlier observation dates.
- Empty/insufficient collection prevents a growth claim. The previous/current
  count and percent-point change remain inspectable; no forecast is generated.
- Selecting a heatmap cell selects its group without changing the today-relative
  range. **연결 글 전체** explicitly expands that group's evidence into the past
  without changing the main comparison window or including future items.
- A source is counted using existing canonical identities. Different URLs about
  the same event are not automatically merged. Group definitions are rebuilt from
  the current archive and can change as articles are added or corrected.

## Artifacts

Generated files live only under ignored `site/insights/`:

- `groups.json`: lexical groups, evidence links, source membership and period counts.
- `graph.json`: existing extracted graph export, with `article_groups` attached.
- `evidence.json`: original summaries, keywords, application notes and limitations.
- `index.html`: the grouped recent-reading UI.
- `overview.html`: script-free group/source links.
- `D3-LICENSE.txt`: license for the retained legacy graph renderer.

The new page does not load the legacy graph renderer or D3 bundle. Those modules
and their tests remain available for consumers of the existing graph export.
Existing report anchor/URL helpers are reused. Both builders retain the shared
site theme. No generated artifacts or dependency directories should be committed.

Tests cover candidate gating, source deduplication, exact grouping provenance,
non-chaining groups, standalone determinism, complete output regeneration,
Korean-midnight boundaries, stale data, actual grouped UI behavior, source
history/search/pagination, active navigation semantics, and light/dark layouts.
