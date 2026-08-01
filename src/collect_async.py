"""Pull a submitted job's result and score it. Safe to run repeatedly."""
import json, math, statistics as st, sys, glob
from pathlib import Path
from qiskit_ibm_runtime import QiskitRuntimeService
from ecdlp_ladder import build_challenge, solve
from honest_oracle import decode_candidates
from run_experiment import joint_counts

RESULTS = Path(__file__).parent.parent / "results"

def main(job_id=None):
    pend = sorted(glob.glob(str(RESULTS / "PENDING_*.json")))
    if job_id is None:
        if not pend:
            print("no pending jobs recorded"); return
        rec = json.load(open(pend[-1]))
    else:
        rec = next(json.load(open(f)) for f in pend if job_id in f)

    svc = QiskitRuntimeService()
    job = svc.job(rec["job_id"])
    status = job.status()
    print(f"{rec['job_id']}  status={status}")
    if str(status) not in ("DONE", "JobStatus.DONE"):
        print("  not finished yet -- rerun later"); return

    res = job.result()
    ch = build_challenge(rec["bits"]); key = solve(ch)
    shares = []
    for i in range(rec["trials"]):
        ranked = decode_candidates(joint_counts(res[i], rec["reg_bits"]),
                                   rec["reg_bits"], ch.n)
        total = sum(v for _, v in ranked) or 1
        shares.append(next((v / total for k, v in ranked if k == key), 0.0))

    u = 1 / ch.n
    m, sd = st.mean(shares), st.stdev(shares)
    t = (m - u) / (sd / math.sqrt(len(shares)))
    rec.update({"status": "done", "shares": shares,
                "mean_share": m, "stdev": sd, "uniform": u, "t_stat": t})
    out = RESULTS / f"C_cross_device_{rec['backend']}_{rec['job_id']}.json"
    out.write_text(json.dumps(rec, indent=2))
    Path(pend[-1] if job_id is None else
         next(f for f in pend if job_id in f)).unlink()

    print(f"  share    {m:.2%} +/- {sd:.2%}   uniform {u:.2%}")
    print(f"  t        {t:+.2f}  -> {'SIGNAL' if abs(t) > 2 else 'no signal'}")
    print(f"  saved    {out.name}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
