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

## Not used yet

- `DemandShare`, `SignedGap` and the PerfApproach `Volume`: the PerfApproach volume differs from the link volume used by
  Q1 (3055 [E]: 314 against 355 for 08:00-08:15); to be confirmed with the data owner first.
- `ISI`, `RiskBusiest`: definitions to be confirmed.
- Usual cycle variation and usual phase shares by quarter-hour (would need the reference weeks on click).
- The rank's mapping-suspect list still uses the usual 100 % rule: the screening does not read `Phases`.
