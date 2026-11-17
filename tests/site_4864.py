"""SCATS 4864 Bay Road / Reserve Road, Tue 10 Nov 2026 08:00-08:30: the values of the Red report; the quarter-hour
records and the phases are reconstructed from that report (phases A,C / A,B / B,C solve its current shares exactly).
Site 2318 is its subsystem neighbour; its values here are illustrative."""
from diagnostics.templates import d001
from diagnostics import subsystems
def row(link,label,cur,usual,lo,hi,status,d,n=6):
    return {"link":link,"label":label,"current":cur,"usual":usual,"p_low":lo,"p_high":hi,"status":status,"direction":d,"n_history":n,"pct_difference":(cur-usual)/usual*100}
E,W,N="LE","LW","LN"
SITE={"site":"4864","name":"Bay Road / Reserve Road","label":"Red","q2":{"tolerated":[],"detectors":[]},
 "q1":{"status":"ABNORMAL","approaches":[row(E,"Bay Road [E]",420,215.5,191.5,292,"ABNORMAL","HIGH"),row(W,"Bay Road [W]",394,329,268,367.5,"ABNORMAL","HIGH"),row(N,"Reserve Road [N]",237,120,115,167,"ABNORMAL","HIGH")]},
 "q3":{"status":"ABNORMAL","abnormal_count":2,"components":{"cycle_length":row(None,None,76.1,71.8,70.8,82.2,"NORMAL",None,5),
  "cycle_stability":row(None,None,49.4,79.5,66.4,90.3,"ABNORMAL","POORER",5),
  "phase_service":{"status":"ABNORMAL","approaches":[row(E,"Bay Road [E]",71.6,83.0,76.1,84.7,"ABNORMAL","LOW",5),row(W,"Bay Road [W]",74.4,55.3,54.8,71.1,"ABNORMAL","HIGH",5),row(N,"Reserve Road [N]",54.0,28.2,27.9,54.2,"NORMAL",None,5)]}}}}
DETAIL={"quarters":["08:00-08:15","08:15-08:30"],"kpi":[{"AvgCycle":75.2,"CycleCvPct":8.9,"CycleStability":55.3},{"AvgCycle":77.0,"CycleCvPct":11.3,"CycleStability":43.5}],
 "approaches":{E:[{"GreenShare":72.2,"Phases":"A,C"},{"GreenShare":71.1,"Phases":"A,C"}],W:[{"GreenShare":73.9,"Phases":"A,B"},{"GreenShare":74.9,"Phases":"A,B"}],N:[{"GreenShare":53.9,"Phases":"B,C"},{"GreenShare":54.1,"Phases":"B,C"}]},
 "volume":{E:[199,221],W:[193,201],N:[105,132]}}
MATE={"site":"2318","name":"Bay Road / Jack Road","category":"amber_signal","q3":{"components":{"cycle_length":{"status":"NORMAL","current":76.0,"usual":72.0,"direction":None},"cycle_stability":{"status":"ABNORMAL","current":50.0,"usual":80.0,"direction":"POORER"}}}}
if __name__=="__main__":
    ev=d001.evidence(SITE,{"local":"p"},DETAIL,None,subsystems.context("4864",{"2318":MATE}.get))
    w=d001.written(ev)
    print(w["diagnosis"]); print(); print(*w["suggested_checks"],sep="\n")
    for r in ev["readings"]: print(r["key"],r["strength"],r["for"],r["against"])
