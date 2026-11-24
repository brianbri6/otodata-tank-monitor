# Nee-Vo history API tank-level workaround

The upstream integration reads tank percentages from `GetAllDisplayPropaneDevices[].Level`. On some Otodata accounts this percentage stays stale even though the Nee-Vo graph shows newer readings.

This fork adds a second authenticated request for each tank:

`GET https://ws.otodatanetwork.com/neevoapp/v1/DataService.svc/GetPropaneLevels/{Id}`

The default **Latest historical graph point** mode uses the newest valid `GraphLevelsData[].Level` by timestamp and falls back to `CurrentLevel`. It replaces only the effective tank `Level` and, when dated, `LastReadingDate`; tank IDs, capacity, pressure and other metadata still come from the original summary response. Version 2.2.0 uses a separate integration domain and new entity identities.

## Install via HACS or Marketplace

**Existing upstream users:** the fork now installs into its own directory, so no repository ownership repair is required. Configure it as a separate integration.

1. HACS → Custom repositories → add `https://github.com/brianbri6/otodata-tank-monitor2` as **Integration**.
2. Install the current main branch (manifest version 2.2.0); leave the original integration intact.
3. Restart Home Assistant and add **Otodata Tank Monitor (History API)** in Settings → Devices & services.
4. Open **Settings → Devices & services → Otodata Tank Monitor (History API) → Configure**. Choose the history source and polling interval.

The workaround is included on the default `main` branch.

## History source options

- **Latest historical graph point (workaround)** — default; use newest dated graph point, then history `CurrentLevel`.
- **History CurrentLevel (alternate)** — prefer `CurrentLevel`, then graph.
- **Original device summary (disable workaround)** — restore upstream behavior.

The main tank sensor exposes `level_source`, `summary_level`, `history_current_level`, `history_graph_level`, `history_graph_date` and `history_status` for troubleshooting.

On a history API error, the last successfully retrieved history reading is retained in memory until restart. If no history reading is available, the percentage is unavailable rather than silently reverting to the known-stale summary value. The history endpoint is polled once per tank per integration update; it reuses the same BasicAuth credentials. It does not transmit anything to third parties.

The consumption sensor re-baselines when the source changes so the initial jump from a stale 6% summary does not generate a fictitious fill event or gas-consumption delta. Totals are preserved across source changes within this integration; existing upstream totals are not automatically imported.

**Caveats:** The endpoint and payload were identified by static analysis of the Nee-Vo Android app, but the workaround has not been tested against your authenticated live account. The history API may change. If `GraphLevelsData` lacks usable timestamps, `CurrentLevel` is used. The consumption sensor cannot reconstruct missed historical consumption between polls.

## Verify

After a successful update, inspect the tank sensor attributes. `level_source` should be `history_graph` or `history_current`, and `summary_level` should still show the old backend value if Otodata has not repaired it. Compare the displayed percentage to the latest Nee-Vo history graph reading.

For automated tests, run `python -m unittest discover -s tests -v` (Python standard library).
