#!/usr/bin/env python3
"""check_and_grade.py — Fetch scores via ESPN (free) and grade all 3 sports.

Self-contained script (no cross-repo imports) designed to run in GitHub Actions
every 15 minutes during game windows. Uses ESPN scoreboards exclusively —
zero Odds API calls, saving the entire quota for odds fetching.

ESPN endpoints (free, unlimited, near real-time):
  NBA:   https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard
  NHL:   https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard
  NCAAB: https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard

Usage:
    python scripts/check_and_grade.py
"""

import json
import os
import sys
import requests
from datetime import datetime, timedelta

# ── Configuration ────────────────────────────────────────────────

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ESPN_ENDPOINTS = {
    "NBA": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "NHL": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
    "NCAAB": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
    "MLB": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
}

ESPN_NHL_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/summary"

# ESPN sometimes uses non-standard abbreviations — map to our projection format
ESPN_ABBR_FIX = {
    # NBA
    "GS": "GSW", "SA": "SAS", "NY": "NYK", "NO": "NOP",
    "UTAH": "UTA", "WSH": "WAS",
    # NHL
    "TB": "TBL", "SJ": "SJS", "LA": "LAK", "NJ": "NJD",
    "MON": "MTL", "CLB": "CBJ", "NASH": "NSH",
}


# ── ESPN Score Fetching ──────────────────────────────────────────


def fetch_espn_scores(sport, date_str=None):
    """Fetch scores from ESPN scoreboard for any sport.

    Args:
        sport: "NBA", "NHL", or "NCAAB"
        date_str: Optional date in 'YYYY-MM-DD' format (defaults to today)

    Returns dict: {"AWAY@HOME": {away_score, home_score, completed}}
    """
    url = ESPN_ENDPOINTS[sport]
    params = {}
    if date_str:
        params["dates"] = date_str.replace("-", "")
    if sport == "NCAAB":
        params["limit"] = 300
        params["groups"] = 50

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        scores = {}
        for event in data.get("events", []):
            status_type = event.get("status", {}).get("type", {}).get("name", "")
            competition = event.get("competitions", [{}])[0]
            competitors = competition.get("competitors", [])

            if len(competitors) != 2:
                continue

            home_comp = away_comp = None
            for comp in competitors:
                if comp.get("homeAway") == "home":
                    home_comp = comp
                else:
                    away_comp = comp

            if not home_comp or not away_comp:
                continue

            home_abbr = home_comp.get("team", {}).get("abbreviation", "")
            away_abbr = away_comp.get("team", {}).get("abbreviation", "")

            # Normalize ESPN abbreviations to our format
            home_abbr = ESPN_ABBR_FIX.get(home_abbr, home_abbr)
            away_abbr = ESPN_ABBR_FIX.get(away_abbr, away_abbr)

            home_score = int(home_comp.get("score", 0) or 0)
            away_score = int(away_comp.get("score", 0) or 0)

            completed = status_type == "STATUS_FINAL"
            in_progress = status_type == "STATUS_IN_PROGRESS"

            key = f"{away_abbr}@{home_abbr}"
            scores[key] = {
                "away_score": away_score,
                "home_score": home_score,
                "completed": completed,
                "in_progress": in_progress,
            }

        label = f"{sport} {date_str}" if date_str else sport
        print(f"  [{label}] ESPN: {len(scores)} games")
        return scores

    except Exception as e:
        label = f"{sport} {date_str}" if date_str else sport
        print(f"  [{label}] ESPN fetch error: {e}")
        return {}


# ── Smart Checking ───────────────────────────────────────────────


def has_ungraded_games(proj_path):
    """Check if a projection file has any ungraded (non-final) games.

    Returns (has_ungraded: bool, total_games: int, ungraded_count: int)
    """
    if not os.path.exists(proj_path):
        return False, 0, 0

    try:
        with open(proj_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        games = data.get("games", [])
        if not games:
            return False, 0, 0

        ungraded = sum(1 for g in games if g.get("status") not in ("final", "closed"))
        return ungraded > 0, len(games), ungraded

    except Exception:
        return True, 0, 0  # err on the side of checking


# ── Grading Functions ────────────────────────────────────────────


def grade_spread(game, away_score, home_score):
    """Grade a spread pick. Returns 'W', 'L', or 'P' (push)."""
    pick_str = game.get("spread_pick", "")
    if not pick_str or pick_str == "N/A":
        return None

    parts = pick_str.rsplit(" ", 1)
    if len(parts) < 2:
        return None

    pick_team = parts[0]
    try:
        line = float(parts[1])
    except (ValueError, IndexError):
        return None

    if pick_team == game["home_team"]:
        margin = home_score - away_score + line
    else:
        margin = away_score - home_score + line

    if margin > 0:
        return "W"
    elif margin < 0:
        return "L"
    return "P"


def grade_total(game, away_score, home_score):
    """Grade a total pick. Returns 'W', 'L', or 'P' (push)."""
    pick = game.get("total_pick")
    line = game.get("total_line")
    if not pick or line is None:
        return None

    actual_total = away_score + home_score
    if pick == "OVER":
        if actual_total > line:
            return "W"
        elif actual_total < line:
            return "L"
        return "P"
    else:  # UNDER
        if actual_total < line:
            return "W"
        elif actual_total > line:
            return "L"
        return "P"


def grade_ml(game, away_score, home_score):
    """Grade a moneyline pick. Returns 'W' or 'L'."""
    pick = game.get("ml_pick")
    if not pick:
        return None

    if pick == game["home_team"]:
        return "W" if home_score > away_score else "L"
    else:
        return "W" if away_score > home_score else "L"


# ── Results Helpers ──────────────────────────────────────────────


def _hit_from_result(r):
    """Convert grade letter to hit value: True/False/None (push)."""
    if r == "W":
        return True
    if r == "L":
        return False
    return None  # P or None


def _tally(picks_list):
    w = sum(1 for p in picks_list if p.get("hit") is True)
    l = sum(1 for p in picks_list if p.get("hit") is False)
    ps = sum(1 for p in picks_list if p.get("hit") is None)
    return w, l, ps


def _make_stat(w, l, ps=0):
    t = w + l
    pct_val = round(w / t * 100, 1) if t > 0 else 0
    record = f"{w}-{l}-{ps}" if ps else f"{w}-{l}"
    return {"wins": w, "losses": l, "pushes": ps, "record": record, "pct": pct_val}


def _sum_cat(days_list, cat):
    """Sum a category across all days and compute allTime stats with ROI."""
    w = sum(d.get(cat, {}).get("wins", 0) for d in days_list)
    l = sum(d.get(cat, {}).get("losses", 0) for d in days_list)
    p = sum(d.get(cat, {}).get("pushes", 0) for d in days_list)
    t = w + l
    pct_val = round(w / t * 100, 1) if t > 0 else 0
    profit = w * 90.91 - l * 100
    roi = round(profit / (t * 100) * 100, 1) if t > 0 else 0
    return {"wins": w, "losses": l, "pushes": p, "pct": pct_val, "roi": roi}


# ── Core Grading Pipeline ───────────────────────────────────────


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    # Safety guard: never reduce game count in projection files
    if "games" in data and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            old_count = len(existing.get("games", []))
            new_count = len(data.get("games", []))
            if new_count < old_count:
                print(f"  WARNING: Refusing to save {os.path.basename(path)} — "
                      f"would reduce games from {old_count} to {new_count}")
                return False
        except Exception:
            pass  # can't read existing file, proceed with save
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return True


def grade_sport(sport_label, proj_filename, results_filename, scores, is_nba=False):
    """Grade a single sport's projections against scores.

    Args:
        sport_label: Display name (NBA, NHL, NCAAB)
        proj_filename: Projection JSON filename in repo root
        results_filename: Results JSON filename in repo root
        scores: Dict of {"AWAY@HOME": {away_score, home_score, completed}}
        is_nba: If True, use NBA-specific results merge (preserve props)

    Returns (changed: bool, summary: str)
    """
    proj_path = os.path.join(REPO_ROOT, proj_filename)
    results_path = os.path.join(REPO_ROOT, results_filename)

    proj_data = load_json(proj_path)
    if not proj_data or not proj_data.get("games"):
        return False, f"{sport_label}: no projection file"

    games = proj_data["games"]
    game_date = proj_data.get("date", datetime.now().strftime("%Y-%m-%d"))

    if not scores:
        return False, f"{sport_label}: no ESPN scores available"

    # IMPORTANT: This loop only updates score/status/result fields.
    # It NEVER modifies prediction values (spread_pick, spread_conf,
    # total_pick, total_line, ml_pick, ml_conf, proj_* fields, etc.)
    # so locked projections stay intact through grading.
    changed = False
    graded_games = []
    live_updates = 0

    for g in games:
        key = f"{g['away_team']}@{g['home_team']}"
        sc = scores.get(key)
        if not sc:
            continue

        away_score = sc["away_score"]
        home_score = sc["home_score"]
        if away_score is None or home_score is None:
            continue

        if sc["completed"]:
            # Skip if already graded with same scores
            if (g.get("status") == "final"
                    and g.get("away_score") == away_score
                    and g.get("home_score") == home_score
                    and g.get("spread_result") is not None):
                continue

            g["away_score"] = away_score
            g["home_score"] = home_score
            g["status"] = "final"

            g["spread_result"] = grade_spread(g, away_score, home_score)
            g["total_result"] = grade_total(g, away_score, home_score)
            g["ml_result"] = grade_ml(g, away_score, home_score)

            matchup = f"{g['away_team']} {away_score} - {g['home_team']} {home_score}"
            graded_games.append(matchup)
            changed = True

        else:
            # Live game — update scores only
            if g.get("status") != "final":
                old_away = g.get("away_score")
                if old_away != away_score or g.get("home_score") != home_score:
                    g["away_score"] = away_score
                    g["home_score"] = home_score
                    g["status"] = "live"
                    live_updates += 1
                    changed = True

    if changed:
        proj_data["updated"] = datetime.now().isoformat(timespec="seconds")
        save_json(proj_path, proj_data)

        if is_nba:
            update_nba_results(proj_data, results_path)
        else:
            update_results(sport_label, proj_data, results_path)

    # Build summary
    final_count = sum(1 for g in games if g.get("status") == "final")
    live_count = sum(1 for g in games if g.get("status") == "live")
    sched_count = sum(1 for g in games if g.get("status") not in ("live", "final"))

    parts = []
    if graded_games:
        parts.append(f"{len(graded_games)} graded ({', '.join(graded_games)})")
    if live_updates:
        parts.append(f"{live_updates} live score updates")
    if not parts:
        if final_count == len(games):
            parts.append("all games already graded")
        elif sched_count == len(games):
            parts.append("all games still scheduled")
        else:
            parts.append(f"{live_count} live, {sched_count} scheduled — no score changes")

    summary = f"{sport_label}: {'; '.join(parts)} [{final_count}F/{live_count}L/{sched_count}S]"
    print(f"  {summary}")

    return changed, summary


def update_results(sport_label, proj_data, results_path):
    """Update results JSON for NHL/NCAAB (no props to preserve)."""
    games = proj_data.get("games", [])
    game_date = proj_data.get("date", datetime.now().strftime("%Y-%m-%d"))

    picks = []
    for g in games:
        if g.get("status") != "final" or g.get("away_score") is None:
            continue

        matchup = f"{g['away_team']} @ {g['home_team']}"
        result_str = f"{g['away_score']}-{g['home_score']}"

        if g.get("spread_result") in ("W", "L", "P"):
            picks.append({
                "date": game_date, "type": "spread", "game": matchup,
                "pick": g.get("spread_pick", ""), "result": result_str,
                "hit": _hit_from_result(g["spread_result"]),
                "confidence": g.get("spread_conf", 0),
            })
        if g.get("total_result") in ("W", "L", "P"):
            pick_label = f"{g.get('total_pick', '')} {g.get('total_line', '')}"
            picks.append({
                "date": game_date, "type": "total", "game": matchup,
                "pick": pick_label, "result": result_str,
                "hit": _hit_from_result(g["total_result"]),
                "confidence": g.get("total_conf", 0),
            })
        if g.get("ml_result") in ("W", "L"):
            picks.append({
                "date": game_date, "type": "ml", "game": matchup,
                "pick": g.get("ml_pick", ""), "result": result_str,
                "hit": _hit_from_result(g["ml_result"]),
                "confidence": g.get("ml_conf", 0),
            })

    if not picks:
        return

    # Tag top 5 by confidence as best bets
    by_conf = sorted(picks, key=lambda p: p.get("confidence") or 0, reverse=True)
    for p in by_conf[:5]:
        p["best_bet"] = True

    # Tally per category
    spread_picks = [p for p in picks if p["type"] == "spread"]
    total_picks = [p for p in picks if p["type"] == "total"]
    ml_picks = [p for p in picks if p["type"] == "ml"]
    bb_picks = [p for p in picks if p.get("best_bet")]

    sw, sl, sp = _tally(spread_picks)
    tw, tl, tp = _tally(total_picks)
    mw, ml_l, mp = _tally(ml_picks)
    bw, bl, bp = _tally(bb_picks)

    # Load or create results
    results = load_json(results_path) or {"updated": "", "allTime": {}, "days": []}

    day_entry = {
        "date": game_date,
        "spreads": _make_stat(sw, sl, sp),
        "totals": _make_stat(tw, tl, tp),
        "moneylines": _make_stat(mw, ml_l, mp),
        "best_bets": _make_stat(bw, bl, bp),
        "picks": picks,
    }

    # Replace or append day
    days = results.get("days", [])
    replaced = False
    for i, d in enumerate(days):
        if d["date"] == game_date:
            days[i] = day_entry
            replaced = True
            break
    if not replaced:
        days.append(day_entry)
    days.sort(key=lambda d: d["date"], reverse=True)
    results["days"] = days

    # Recalculate allTime
    results["allTime"] = {
        "spreads": _sum_cat(days, "spreads"),
        "totals": _sum_cat(days, "totals"),
        "moneylines": _sum_cat(days, "moneylines"),
        "best_bets": _sum_cat(days, "best_bets"),
    }
    results["updated"] = datetime.now().isoformat(timespec="seconds")

    save_json(results_path, results)


def update_nba_results(proj_data, results_path):
    """Update NBA results.json, preserving existing props data."""
    games = proj_data.get("games", [])
    game_date = proj_data.get("date", datetime.now().strftime("%Y-%m-%d"))

    # Build game picks (spread/total/ML only — no props)
    game_picks = []
    for g in games:
        if g.get("status") != "final" or g.get("away_score") is None:
            continue

        matchup = f"{g['away_team']} @ {g['home_team']}"
        result_str = f"{g['away_score']}-{g['home_score']}"

        if g.get("spread_result") in ("W", "L", "P"):
            game_picks.append({
                "date": game_date, "type": "spread", "game": matchup,
                "pick": g.get("spread_pick", ""), "result": result_str,
                "hit": _hit_from_result(g["spread_result"]),
                "confidence": g.get("spread_conf", 0),
            })
        if g.get("total_result") in ("W", "L", "P"):
            pick_label = f"{g.get('total_pick', '')} {g.get('total_line', '')}"
            game_picks.append({
                "date": game_date, "type": "total", "game": matchup,
                "pick": pick_label, "result": result_str,
                "hit": _hit_from_result(g["total_result"]),
                "confidence": g.get("total_conf", 0),
            })
        if g.get("ml_result") in ("W", "L"):
            game_picks.append({
                "date": game_date, "type": "ml", "game": matchup,
                "pick": g.get("ml_pick", ""), "result": result_str,
                "hit": _hit_from_result(g["ml_result"]),
                "confidence": g.get("ml_conf", 0),
            })

    if not game_picks:
        return

    # Tag top 5 game picks by confidence as best bets
    by_conf = sorted(game_picks, key=lambda p: p.get("confidence") or 0, reverse=True)
    for p in by_conf[:5]:
        p["best_bet"] = True

    # Load existing results
    results = load_json(results_path) or {"updated": "", "allTime": {}, "days": []}
    days = results.get("days", [])

    # Find existing day entry
    existing_day = None
    existing_idx = None
    for i, d in enumerate(days):
        if d["date"] == game_date:
            existing_day = d
            existing_idx = i
            break

    if existing_day:
        # Merge: keep existing prop picks, replace game picks
        existing_picks = existing_day.get("picks", [])
        prop_picks = [p for p in existing_picks if p.get("type") == "prop"]
        merged_picks = prop_picks + game_picks
        existing_day["picks"] = merged_picks

        # Recalculate game stats only (spreads, totals, moneylines, best_bets)
        spread_picks = [p for p in game_picks if p["type"] == "spread"]
        total_picks = [p for p in game_picks if p["type"] == "total"]
        ml_picks = [p for p in game_picks if p["type"] == "ml"]
        bb_picks = [p for p in game_picks if p.get("best_bet")]

        sw, sl, sp = _tally(spread_picks)
        tw, tl, tp = _tally(total_picks)
        mw, ml_l, mp = _tally(ml_picks)
        bw, bl, bp = _tally(bb_picks)

        existing_day["spreads"] = _make_stat(sw, sl, sp)
        existing_day["totals"] = _make_stat(tw, tl, tp)
        existing_day["moneylines"] = _make_stat(mw, ml_l, mp)
        existing_day["best_bets"] = _make_stat(bw, bl, bp)
        # props stats preserved (not touched)

        days[existing_idx] = existing_day
    else:
        # New day entry — game stats only (no props yet)
        spread_picks = [p for p in game_picks if p["type"] == "spread"]
        total_picks = [p for p in game_picks if p["type"] == "total"]
        ml_picks = [p for p in game_picks if p["type"] == "ml"]
        bb_picks = [p for p in game_picks if p.get("best_bet")]

        sw, sl, sp = _tally(spread_picks)
        tw, tl, tp = _tally(total_picks)
        mw, ml_l, mp = _tally(ml_picks)
        bw, bl, bp = _tally(bb_picks)

        day_entry = {
            "date": game_date,
            "spreads": _make_stat(sw, sl, sp),
            "totals": _make_stat(tw, tl, tp),
            "moneylines": _make_stat(mw, ml_l, mp),
            "best_bets": _make_stat(bw, bl, bp),
            "picks": game_picks,
        }
        days.append(day_entry)

    days.sort(key=lambda d: d["date"], reverse=True)
    results["days"] = days

    # Recalculate allTime — include props from all days
    all_time = {
        "spreads": _sum_cat(days, "spreads"),
        "totals": _sum_cat(days, "totals"),
        "moneylines": _sum_cat(days, "moneylines"),
        "best_bets": _sum_cat(days, "best_bets"),
    }
    # Preserve props allTime if it exists (calculated by daily_update.py)
    if "props" in results.get("allTime", {}):
        all_time["props"] = _sum_cat(days, "props")
    # Preserve best_prop_type/pct if they exist
    for key in ("best_prop_type", "best_prop_pct"):
        if key in results.get("allTime", {}):
            all_time[key] = results["allTime"][key]

    results["allTime"] = all_time
    results["updated"] = datetime.now().isoformat(timespec="seconds")

    save_json(results_path, results)


def grade_nhl_props():
    """Grade NHL player props against actual box score stats."""
    props_path = os.path.join(REPO_ROOT, "nhl_player_props.json")
    results_path = os.path.join(REPO_ROOT, "nhl_props_results.json")

    if not os.path.exists(props_path):
        print("  NHL Props: no nhl_player_props.json found")
        return False

    with open(props_path, "r", encoding="utf-8") as f:
        props_data = json.load(f)

    props = props_data.get("projections", [])
    if not props:
        print("  NHL Props: no projections to grade")
        return False

    ungraded = [p for p in props if not p.get("result")]
    if not ungraded:
        print("  NHL Props: all props already graded")
        return False

    print(f"  NHL Props: {len(ungraded)} ungraded props")

    game_ids = set()
    for p in ungraded:
        gid = p.get("game_id")
        if gid:
            game_ids.add(str(gid))

    if not game_ids:
        print("  NHL Props: no game IDs found in props")
        return False

    box_scores = {}
    for gid in game_ids:
        try:
            url = f"{ESPN_NHL_SUMMARY}?event={gid}"
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()

            status = data.get("header", {}).get("competitions", [{}])[0].get("status", {}).get("type", {}).get("name", "")
            if status != "STATUS_FINAL":
                continue

            stats = {}
            for team_data in data.get("boxscore", {}).get("players", []):
                for stat_section in team_data.get("statistics", []):
                    labels = stat_section.get("labels", [])
                    for athlete_data in stat_section.get("athletes", []):
                        player = athlete_data.get("athlete", {})
                        name = player.get("displayName", "")
                        if not name:
                            continue
                        stat_values = athlete_data.get("stats", [])
                        player_stats = {}
                        for i, key in enumerate(labels):
                            if i < len(stat_values):
                                try:
                                    val = stat_values[i]
                                    if "/" in str(val):
                                        parts = str(val).split("/")
                                        player_stats[key] = float(parts[0])
                                    else:
                                        player_stats[key] = float(val)
                                except (ValueError, IndexError):
                                    player_stats[key] = val
                        if name not in stats:
                            stats[name] = {}
                        stats[name].update(player_stats)

            if stats:
                box_scores[gid] = stats
                print(f"    Game {gid}: {len(stats)} players")
        except Exception as e:
            print(f"    Game {gid} error: {e}")

    if not box_scores:
        print("  NHL Props: no finished games with box scores")
        return False

    graded = 0
    wins = 0
    losses = 0

    STAT_MAP = {
        "shots": ["SOG", "S", "Shots"],
        "goals": ["G", "Goals"],
        "assists": ["A", "Assists"],
        "points": ["PTS", "P", "Points"],
        "saves": ["SV", "SA", "Saves"],
    }

    for p in props:
        if p.get("result"):
            continue
        gid = str(p.get("game_id", ""))
        if gid not in box_scores:
            continue
        player_name = p.get("player", "")
        prop_type = p.get("prop", "").lower()
        line = p.get("line")
        direction = p.get("direction", "OVER").upper()
        if line is None:
            continue

        actual_stats = None
        for name, s in box_scores[gid].items():
            if name.lower() == player_name.lower():
                actual_stats = s
                break
            if (name.split()[-1].lower() == player_name.split()[-1].lower() and
                name.split()[0][0].lower() == player_name.split()[0][0].lower()):
                actual_stats = s
                break

        if actual_stats is None:
            continue

        actual_value = None
        for key in STAT_MAP.get(prop_type, [prop_type]):
            if key in actual_stats:
                actual_value = actual_stats[key]
                break
        if actual_value is None:
            continue
        actual_value = float(actual_value)

        if direction == "OVER":
            result = "WIN" if actual_value > line else ("PUSH" if actual_value == line else "LOSS")
        else:
            result = "WIN" if actual_value < line else ("PUSH" if actual_value == line else "LOSS")

        p["result"] = result
        p["actual"] = actual_value
        graded += 1
        if result == "WIN":
            wins += 1
        elif result == "LOSS":
            losses += 1

    if graded == 0:
        print("  NHL Props: no props could be graded")
        return False

    print(f"  NHL Props: graded {graded} props ({wins}W-{losses}L)")
    save_json(props_path, props_data)
    _update_nhl_props_results(props, props_data.get("date", datetime.now().strftime("%Y-%m-%d")), results_path)
    return True


def _update_nhl_props_results(props, game_date, results_path):
    """Update nhl_props_results.json with grading results."""
    results = load_json(results_path) or {
        "sport": "NHL", "type": "player_props",
        "days": [], "all_time": {"wins": 0, "losses": 0, "pushes": 0},
    }

    graded = [p for p in props if p.get("result")]
    if not graded:
        return

    wins = sum(1 for p in graded if p["result"] == "WIN")
    losses = sum(1 for p in graded if p["result"] == "LOSS")
    pushes = sum(1 for p in graded if p["result"] == "PUSH")

    by_type = {}
    for p in graded:
        pt = p.get("prop", "?")
        if pt not in by_type:
            by_type[pt] = {"wins": 0, "losses": 0, "pushes": 0}
        if p["result"] == "WIN": by_type[pt]["wins"] += 1
        elif p["result"] == "LOSS": by_type[pt]["losses"] += 1
        else: by_type[pt]["pushes"] += 1

    by_tier = {}
    for p in graded:
        tier = p.get("edge", "FAIR") or "FAIR"
        if tier not in by_tier:
            by_tier[tier] = {"wins": 0, "losses": 0, "pushes": 0}
        if p["result"] == "WIN": by_tier[tier]["wins"] += 1
        elif p["result"] == "LOSS": by_tier[tier]["losses"] += 1
        else: by_tier[tier]["pushes"] += 1

    day_record = {
        "date": game_date, "wins": wins, "losses": losses, "pushes": pushes,
        "total": len(graded),
        "pct": round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
        "by_type": by_type, "by_tier": by_tier,
        "picks": [{"player": p.get("player"), "prop": p.get("prop"),
                    "direction": p.get("direction"), "line": p.get("line"),
                    "actual": p.get("actual"), "result": p.get("result"),
                    "confidence": p.get("confidence"), "ev": p.get("ev"),
                    "edge": p.get("edge")} for p in graded],
    }

    found = False
    for i, d in enumerate(results["days"]):
        if d.get("date") == game_date:
            results["days"][i] = day_record
            found = True
            break
    if not found:
        results["days"].append(day_record)

    all_w = sum(d.get("wins", 0) for d in results["days"])
    all_l = sum(d.get("losses", 0) for d in results["days"])
    all_p = sum(d.get("pushes", 0) for d in results["days"])
    results["all_time"]["wins"] = all_w
    results["all_time"]["losses"] = all_l
    results["all_time"]["pushes"] = all_p
    results["all_time"]["pct"] = round(all_w / (all_w + all_l) * 100, 1) if (all_w + all_l) > 0 else 0

    results["updated"] = datetime.now().isoformat(timespec="seconds")
    save_json(results_path, results)
    print(f"  Updated nhl_props_results.json")


# ── Entry Point ──────────────────────────────────────────────────


SPORT_CONFIG = [
    {
        "label": "NBA",
        "proj_file": "game_projections.json",
        "results_file": "results.json",
        "is_nba": True,
    },
    {
        "label": "NHL",
        "proj_file": "nhl_game_projections.json",
        "results_file": "nhl_results.json",
        "is_nba": False,
    },
    {
        "label": "NCAAB",
        "proj_file": "ncaab_projections.json",
        "results_file": "ncaab_results.json",
        "is_nba": False,
    },
    {
        "label": "MLB",
        "proj_file": "mlb_game_projections.json",
        "results_file": "mlb_results.json",
        "is_nba": False,
    },
]


def main():
    print(f"\n{'=' * 60}")
    print(f"  Score Check & Auto-Grade — {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Source: ESPN (free, 0 Odds API calls)")
    print(f"{'=' * 60}\n")

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # ── Phase 1: Check which sports need grading ──
    print("Checking for ungraded games...")
    sports_to_check = []
    for cfg in SPORT_CONFIG:
        proj_path = os.path.join(REPO_ROOT, cfg["proj_file"])
        has_ungraded, total, ungraded = has_ungraded_games(proj_path)
        if has_ungraded:
            sports_to_check.append(cfg)
            print(f"  {cfg['label']}: {ungraded}/{total} ungraded — will check")
        else:
            if total == 0:
                print(f"  {cfg['label']}: no games today — skipping")
            else:
                print(f"  {cfg['label']}: all {total} games graded — skipping")

    if not sports_to_check:
        print(f"\n{'=' * 60}")
        print(f"  SUMMARY: All games graded across all sports. Nothing to do.")
        print(f"{'=' * 60}")
        return 0

    # ── Phase 2: Fetch scores from ESPN (only for sports that need it) ──
    print(f"\nFetching ESPN scores for {len(sports_to_check)} sport(s)...")
    score_map = {}
    for cfg in sports_to_check:
        sport = cfg["label"]
        scores = {}
        if sport == "NCAAB":
            # NCAAB games can span yesterday (late games) and today
            scores.update(fetch_espn_scores("NCAAB", yesterday))
            scores.update(fetch_espn_scores("NCAAB", today))
        else:
            # NBA/NHL — today's scoreboard includes games that started today
            scores.update(fetch_espn_scores(sport, today))
            # Also check yesterday for late-night games not yet graded
            scores.update(fetch_espn_scores(sport, yesterday))
        score_map[sport] = scores

    # ── Phase 3: Grade ──
    print("\nGrading...")
    any_changes = False
    summaries = []
    for cfg in sports_to_check:
        sport = cfg["label"]
        changed, summary = grade_sport(
            sport, cfg["proj_file"], cfg["results_file"],
            score_map.get(sport, {}), is_nba=cfg["is_nba"]
        )
        any_changes |= changed
        summaries.append(summary)

    # ── Phase 4: Grade NHL player props ──
    print("\nGrading NHL player props...")
    nhl_props_changed = grade_nhl_props()
    any_changes |= nhl_props_changed

    # Add skipped sports to summary
    checked_labels = {cfg["label"] for cfg in sports_to_check}
    for cfg in SPORT_CONFIG:
        if cfg["label"] not in checked_labels:
            summaries.append(f"{cfg['label']}: skipped (all graded)")

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print(f"  SUMMARY {'(files updated)' if any_changes else '(no changes)'}")
    for s in summaries:
        print(f"    {s}")
    print(f"{'=' * 60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
