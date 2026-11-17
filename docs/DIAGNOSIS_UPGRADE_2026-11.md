# Diagnosis upgrade: quarter-hours, phases and readings (17 Nov 2026)

An upgrade of the Red diagnosis (D001, section 1 and section 4 of the report). The screening, the categories, the
baseline version, the TomTom section, the Amber pages and the contract schema do not change.

## What changes

| Part | Before | After |
|---|---|---|
| Data read on click | The saved 30-minute values | Also the two quarter-hour IntersectionPerfKpi / IntersectionPerfApproach records of the period (every field, incl. `CycleCvPct` and `Phases`) and the two 15-minute link volumes (`detail.py`). If the read fails, the report is written as before |
| Diagnosis | 2 lines: "What the data show:" and "Possible explanations (not demonstrated by these data):", the second built from fixed sentences per combination | 3 lines: "What the data show:" (plus when the change starts and which phases gained or lost green), "Most likely reading (evidence: Strong/Moderate/Weak):", "Other readings:" |
| Readings | – | A fixed catalogue scored from the site's own data (`templates/readings.py`): a response to demand; green given to other phases; a plan or coordination change; unusual demand (incident, event or diversion); a data or mapping issue. Each with its points for and against; ranked, never stated as a cause |
| Strength of evidence | – | Strong: 2+ points for, none against, no data limitation. Moderate: 1 for and none against, or 2+ for and 1 against, or Strong with a data limitation (5-week history, tolerated detector). Weak: the rest. Not a probability |
| "SCATS adapts ..." sentence | In every diagnosis | Once per report: `Q4Output.limitations` (contract) and a note under section 1 (local report) |
| Checks | Generic per finding | The check of each reading first, most supported first, with the quarter-hour and the phases ("In SCATS History for 08:15-08:30, find which of phases B and D extended ... if it recurs, review ..."); the generic checks remain where no targeted one applies |
| Phase groups | Identical green-share values | The same `Phases` when read |
| Usual green share of 100 % | Always a mapping check | Not a check when the approach is served in every phase of the site (e.g. Bell Street [W] at 3055) |
| Supporting evidence | – | Adds the quarter-hour values (cycle length, cycle variation, stability, flagged volumes) and the phase shares |
| LLM | Re-words the draft | Explains the main reading from its points in time order; may make checks more specific. Rejected if it drops a label or the strength, names another main reading, adds a causal claim ("caused", "due to", "because of", "proves") or any number not in the evidence |

## SCATS 3055 Bell Street / Elm Grove, Tue 10 Nov 2026 08:00-08:30 (code wording)

Before:

> What the data show: Traffic differs from history on Bell Street [E] (higher volume than usual). Signal operation differs from history in Cycle Stability (poorer than usual) and phase service to Bell Street [E] (less green than usual). ...
> Possible explanations (not demonstrated by these data): SCATS adapts cycle length and phase service to demand and coordination, so a value outside its historical range does not by itself show a signal problem. Less green to Bell Street [E] while its volume is higher is the opposite of a demand response, so it is the finding most worth verifying; poorer stability means the cycle length varied more than usual, which can happen while SCATS adapts to changing demand.

After:

> What the data show: Traffic differs from history on Bell Street [E] (higher volume than usual). Signal operation differs from history in Cycle Stability (poorer than usual) and phase service to Bell Street [E] (less green than usual). The traffic and phase-service findings are on the same approach (Bell Street [E]); this is an association, not proof that one caused the other. On Bell Street [E] most of the change is in 08:00-08:15 (355 then 290 vehicles per 15 minutes). The signal change starts in 08:15-08:30: cycle length 120.0 s then 123.2 s, cycle variation 0.0% then 5.0%, stability 100.0 then 75.2. Phases A and C, serving Bell Street [E], took 61.3% of the cycle against a usual 75.1% (08:00-08:15 65.1%, 08:15-08:30 57.5%); phases B and D, which serve none of the assessed approaches (side road, turning or pedestrian movements), took 38.7% against a usual 24.9%.
> Most likely reading (evidence: Moderate): Green given to other phases: phases B and D took 38.7% of the cycle against a usual 24.9%; less green to Bell Street [E] while its volume is higher is the opposite of a demand response.
> Other readings: Unusual demand (incident, event or diversion) (moderate; for: the change on Bell Street [E] is concentrated in 08:00-08:15); a plan or coordination change (weak; against: 08:00-08:15 ran the usual cycle, so the change is not a plan for the whole period).

Checks:

1. In SCATS History for 08:15-08:30, find which of phases B and D extended or was called more often, and why (pedestrian calls, side-road or turning demand, phase skips); if it recurs on the same weekday, review the maximum times of phases B and D or the plan selection.
2. Check for incidents, events, roadworks or diversions affecting Bell Street [E] during 08:00-08:15, and compare the same time next week.
3. Check the plan number, subsystem cycle length and linking/offsets in force for 08:15-08:30 against the usual weekday; if a plan or coordination change is found, confirm that it was intended.

## Update of 18 Nov 2026: control context and phase shares

SCATS sets the cycle length and the split and link plans per subsystem (from the subsystem's strategic
measurements); the local controller then extends, terminates or skips phases within that plan. The diagnosis now
reads each change at the level that decides it.

| Change | What it does |
|---|---|
| Control context (`subsystems.py`) | The site's Region and subsystem (from `data/site_subsystem_map.json`) and the same-period results of the other sites of the subsystem. Shown as a "Control:" sentence and a `Control` evidence item |
| Readings by control level | "a subsystem decision (cycle, plan or coordination)" replaces "a plan or coordination change"; "a local controller response (phase extensions, skips or pedestrian calls)" replaces "green given to other phases". A cycle change shared with a subsystem neighbour, or a cycle equal to a neighbour's, counts for a subsystem decision; a neighbour keeping its usual cycle counts against it |
| Phase shares | The share of the cycle of each phase (or group of phases that always serve the same approaches) is solved from the approaches' green shares and their phases, and compared with the usual. Green moving to phases that serve busier approaches counts for a response to demand; to phases serving no busier approach, for a local controller response |
| Mixed splits | When the usual green shares fit no single split, the reference weeks ran different splits: the current shares are shown without a usual value, and this counts for a subsystem decision |
| Checks | A subsystem decision: check the subsystem's degree of saturation, required against active cycle length, active split and link plan and any marriage or divorce, for the whole subsystem. A local response: why the gaining phases ran longer at this site |
| Rank | Each ranked site carries its subsystem; `ranked.md` lists the subsystems with two or more Red or Amber sites |
| `python main.py subsystem-check --site ... --end ...` | Lists every stored `subsystem_status` field for the site's subsystem and the measurements of the SCATS buckets, to see which subsystem measures can be added |

Review evidence (four periods, 10 Nov 2026): at Red and Amber – signal sites with an assessed subsystem neighbour, the
neighbour also had an abnormal cycle length in 14 of 16 cases (12 with the same cycle), against 7 % of all sites.

Results on the two sample sites (code wording):
- 3055 (only site of its subsystem): a local controller response, Moderate; phases B and D gained 13.8 percentage
  points from 08:15 and serve none of the assessed approaches.
- 4864 (subsystem with 2318): a subsystem decision, Moderate; the reference weeks ran different splits and the
  site runs the same cycle as its neighbour. The first check is the subsystem's saturation, cycle and plans.

## Update of 18 Nov 2026 (2): subsystem state

`subsystem_status` (bucket `scats`) holds per subsystem, about every cycle: `DegreeOfSaturation`,
`RequiredCycleLength`, `ActiveCycleLength`, and the tag `CriticalSite` (checked with `subsystem-check` on 3055, 4864
and 2318). On a Red click the diagnosis now reads them for the period and the reference weeks (one small query per
week) and states: the critical site, the saturation (median, maximum, records at 100 or more, by quarter-hour, against
the usual median), and how the active cycle compared with the required cycle.

| Evidence | Counts for |
|---|---|
| Saturation 10 or more above its usual median, or at 100 or more in 3 or more records | a response to demand |
| The active cycle within 2 s of the required cycle in most records while it moved (and stability is poorer) | a response to demand (the subsystem adapting); against a subsystem plan decision |
| The active cycle at least 3 s above the required cycle in half the records or more | a subsystem decision (held by a plan, coordination or a configured minimum) |
| A constant subsystem cycle while the site's measured cycles varied | a local controller response; against a subsystem decision |

On the samples (10 Nov, 08:00-08:30):
- 3055: the subsystem cycle stayed at 120 s, above a required cycle of 110 s on average, while the site's own cycles varied from 08:15 and saturation rose from 66 to 93; read as a local controller response.
- 4864 (critical site of MEN-22): saturation at 100 or more in 10 of 25 records and the active cycle following the required cycle between 70 and 90 s; read as a response to demand, which also accounts for the poorer stability.

`python main.py measure-check --site ... --end ...` lists the tag and field keys of SCATS measurements not yet used
(`scats_split_plan`, `site_phase`, `site_signal_group`, `intersection_cycle_time`, `link_green_percentage`,
`congestion`, `hazard`) and the site's records in the period.

## Not used yet

- `DemandShare`, `SignedGap` and the PerfApproach `Volume`: the PerfApproach volume differs from the link volume used by
  Q1 (3055 [E]: 314 against 355 for 08:00-08:15); to be confirmed with the data owner first.
- `ISI`, `RiskBusiest`: definitions to be confirmed.
- Usual cycle variation and usual phase shares by quarter-hour (would need the reference weeks on click).
- The rank's mapping-suspect list still uses the usual 100 % rule: the screening does not read `Phases`.
- Split and link plan numbers, marriage state and strategic-approach DS are not in `subsystem_status`;
  `scats_split_plan` and `site_phase` may hold the plans and phases (`measure-check`). The site-subsystem map is static
  (no marriages).
