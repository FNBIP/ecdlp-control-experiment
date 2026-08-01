"""
Submit without waiting, so a deep queue costs wall-clock instead of a session.

ibm_kingston carries the best error rates on the free tier (7.84e-4 best-edge vs
ibm_fez's 1.34e-3) and is therefore permanently congested -- 494 to 762 jobs
pending across one evening. run_experiment.py calls job.result(), which blocks
until the job runs; behind that queue it blocks for hours.

Queue time is not billed against the 600-second allowance, so waiting costs
nothing but attention. This submits, records the job id, and exits. Collect with
collect_async.py whenever it lands.
"""
import json, sys
from pathlib import Path
from qiskit import transpile
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2
from ecdlp_ladder import build_challenge
from honest_oracle import build_ecdlp_circuit

RESULTS = Path(__file__).parent.parent / "results"

def main(bits=4, backend_name="ibm_kingston", shots=256, trials=20):
    svc = QiskitRuntimeService()
    be = svc.backend(backend_name)
    ch = build_challenge(bits)
    oc = build_ecdlp_circuit(ch)
    isa = transpile(oc.circuit, backend=be, optimization_level=3,
                    seed_transpiler=20260801)

    sampler = SamplerV2(mode=be)
    sampler.options.max_execution_time = 300
    job = sampler.run([isa] * trials, shots=shots)

    rec = {
        "experiment": "C_cross_device", "backend": backend_name,
        "bits": bits, "n": ch.n, "p": ch.p,
        "shots": shots, "trials": trials,
        "cz_gates": dict(isa.count_ops()).get("cz", 0),
        "depth": isa.depth(),
        "reg_bits": oc.reg_bits,
        "job_id": job.job_id(), "status": "submitted",
        "queue_at_submit": be.status().pending_jobs,
    }
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"PENDING_{backend_name}_{bits}bit_{job.job_id()}.json"
    out.write_text(json.dumps(rec, indent=2))
    print(f"submitted  {job.job_id()}")
    print(f"  backend  {backend_name}  (queue {rec['queue_at_submit']} at submit)")
    print(f"  circuit  {rec['cz_gates']} cz, depth {rec['depth']}, {trials}x{shots} shots")
    print(f"  record   {out.name}")
    print(f"  collect  python3 collect_async.py {job.job_id()}")

if __name__ == "__main__":
    main(backend_name=sys.argv[1] if len(sys.argv) > 1 else "ibm_kingston")
