doosra lists, for every pair liqind routes, roughly how much you can sell before the price slips 1, 2, 3, 5 or 10 percent, grouped by chain. The numbers come from the convex routing algorithm run against a saved block on each chain, so they are model estimates rather than executed trades. 

The local build reads one active publication through `data/current-publication.json`.
It pins a complete, immutable package in `data/publications/`, including each pair's
block, timestamp and selected results. Older inputs are archived and cannot replace
the active package. Builds with explicit input files are allowed only for previews.

From the parent solver project, publish a reviewed saved pair with
`python -m scripts.publish_saved_current_pair_site --pair ID --summary PATH --release PATH --publish`,
then commit and push the generated `docs/` files. The publisher checks the selected
receipts, rejects older blocks and stale concurrent updates, and preserves every
other pair. Numerical interpolation proposes sizes; published modeled amounts must
still pass the route's funding and pool constraints.
