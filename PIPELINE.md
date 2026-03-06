# Pipeline Architecture

Autonomous sports prediction platform running entirely on GitHub Actions.
Six workflows handle predictions, props, grading, health checks, and deployment — no local machine required.

## Architecture

```
  nba-predictor ──┐
  nhl-predictor ──┤
  ncaab-predictor─┤──▶ daily-predictions.yml ──▶ mattev-sports (GitHub Pages)
  mlb-predictor ──┤                                    ▲
  nhl-props ──────┘                                    │
  nba-props ─────────▶ props_refresh.yml ──────────────┘
                                                       ▲
                       check-scores.yml ───────────────┘  (grading loop)
                       health-check.yml                   (freshness monitor)
                       deploy.yml                         (GitHub Pages)
```

## Workflow Schedule

| Time (EST) | Workflow | Repo | Purpose |
|------------|----------|------|---------|
| 3:00 AM | `daily-predictions.yml` | mattev-sports | 5 parallel prediction jobs + publish |
| 9:00 AM | `daily-props.yml` | nhl-props | Full NHL props pipeline |
| 10:00 AM | `props_refresh.yml` | nba-props | NBA sim v2 + props refresh |
| 11:00 AM | `health-check.yml` | mattev-sports | Freshness check, re-trigger if stale |
| */10 game window | `check-scores.yml` | mattev-sports | Self-healing grading loop |
| On push | `deploy.yml` | mattev-sports | GitHub Pages deployment |

## Daily Timeline

1. **3 AM EST** - `daily-predictions.yml` runs 5 parallel jobs:
   - NBA: `daily_run.py` + game projections export + props generation
   - NCAAB: `get_data.py` + `fetch_odds.py` + `predict.py` + `export_projections.py`
   - NHL: `nhl_model.py --today` + `grade_nhl.py`
   - MLB: `get_data.py` + `fetch_odds.py` + `mlb_model.py --today` + `export_projections.py`
   - NHL Props: `get_player_data.py` + `fetch_prop_odds.py` + `nhl_props_model.py` + `export_props.py`
   - Publish job collects all artifacts and pushes to mattev-sports

2. **9 AM EST** - `daily-props.yml` refreshes NHL props with latest odds

3. **10 AM EST** - `props_refresh.yml` runs `daily_update.py --props-only` for NBA sim v2 + props

4. **11 AM EST** - `health-check.yml` verifies all files are fresh, re-triggers if stale

5. **Game window (12 PM - 2 AM EST)** - `check-scores.yml` runs every 10 minutes:
   - Internal loop: up to 16 iterations with 90s sleep (or 30s when games ending)
   - Fetches ESPN scoreboards (free, unlimited, no API key)
   - Grades completed games, updates live scores
   - Auto-commits and pushes changes
   - Stops early when all games are graded (exit code 2)

## File Manifest

### Prediction Files (produced by daily-predictions.yml)

| File | Producer | Consumer |
|------|----------|----------|
| `game_projections.json` | nba-predictor | Dashboard (NBA tab) |
| `ncaab_projections.json` | ncaab-predictor | Dashboard (NCAAB tab) |
| `nhl_game_projections.json` | nhl-predictor | Dashboard (NHL tab) |
| `mlb_game_projections.json` | mlb-predictor | Dashboard (MLB tab) |
| `projections.json` | nba-props | Dashboard (NBA Props tab) |
| `all_props.json` | nba-props | Dashboard (all props view) |
| `nhl_player_props.json` | nhl-props | Dashboard (NHL Props tab) |
| `nba_player_projections.json` | nba-props | Dashboard (player projections) |
| `injuries.json` | nba-props | Dashboard (injury overlay) |
| `top_picks.json` | nba-props | Dashboard (top picks widget) |
| `recommendations.json` | nba-props | Dashboard (recommendations) |

### Recommended Picks Files

| File | Producer | Consumer |
|------|----------|----------|
| `nba_recommended.json` | nba-props | Dashboard (NBA best bets) |
| `nba_props_recommended.json` | nba-props | Dashboard (NBA props best bets) |
| `ncaab_recommended.json` | ncaab-predictor | Dashboard (NCAAB best bets) |
| `nhl_recommended.json` | nhl-predictor | Dashboard (NHL best bets) |
| `mlb_recommended.json` | mlb-predictor | Dashboard (MLB best bets) |
| `nhl_props_recommended.json` | nhl-props | Dashboard (NHL props best bets) |

### Results Files (updated by check-scores.yml grading)

| File | Contents |
|------|----------|
| `results.json` | NBA game results + allTime stats |
| `ncaab_results.json` | NCAAB game results + allTime stats |
| `nhl_results.json` | NHL game results + allTime stats |
| `mlb_results.json` | MLB game results + allTime stats |
| `all_props_results.json` | NBA props grading results |
| `nhl_props_results.json` | NHL props grading results |

### Archive

| File | Purpose |
|------|---------|
| `archive/projections_YYYY-MM-DD.json` | Daily snapshot of all projections before overwrite |

## Grading System

`scripts/check_and_grade.py` handles all grading via ESPN scoreboards (free, no API key needed).

### Exit Codes

| Code | Meaning | Workflow Action |
|------|---------|-----------------|
| 0 | Normal (some games still pending) | Sleep 90s, continue loop |
| 2 | All games graded | Stop loop early |
| 3 | Games ending soon | Fast poll — sleep 30s instead of 90s |

### Smart Polling

When games are near ending (e.g., NBA 4th quarter < 3:00, NHL 3rd period < 5:00), the grading loop switches from 90s to 30s polling. This catches final scores within seconds of game end.

### Self-Healing Loop

The check-scores workflow handles push conflicts gracefully:
1. Pull with rebase before each grade cycle
2. If rebase fails, reset to remote and re-grade
3. Up to 3 push retry attempts per iteration
4. Failed pushes are picked up in the next iteration

## Manual Triggers

All workflows support `workflow_dispatch` for manual triggering:

```bash
# Re-run all predictions
gh workflow run daily-predictions.yml -R mtlusa01/mattev-sports

# Force a grading cycle
gh workflow run check-scores.yml -R mtlusa01/mattev-sports

# Refresh NBA props
gh workflow run props_refresh.yml -R mtlusa01/nba-props

# Run health check
gh workflow run health-check.yml -R mtlusa01/mattev-sports
```

## Troubleshooting

### Stale prediction files
The health-check workflow (11 AM EST) automatically detects stale files and re-triggers `daily-predictions.yml`. Manual fix:
```bash
gh workflow run daily-predictions.yml -R mtlusa01/mattev-sports
```

### Push conflicts in grading
The grading loop handles this automatically with rebase + retry. If persistent, it resets to remote and re-grades. Changes are never lost — they're regenerated from ESPN data.

### Missing recommendation files
Check that the predictor repo actually produces the `*_recommended.json` file. The artifact upload uses `if-no-files-found: warn` so missing files don't fail the build.

### Props not updating
1. Check if `ODDS_API_KEY` secret is set in the repo
2. Verify odds are available (no odds during offseason/spring training)
3. Check `props_refresh.yml` run logs for errors

### Grading not running
1. Verify it's within the game window (12 PM - 2 AM EST)
2. Check concurrency — only one `check-scores` run at a time
3. Manual trigger: `gh workflow run check-scores.yml -R mtlusa01/mattev-sports`
