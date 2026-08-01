"""
Submit one arm of the falsification test to real hardware.

Arms
----
(a) the honest circuit, unmodified
(b) the same circuit with deliberate decoherence injected -- Smolin-Smith-Vargo
    name this as the positive test of a quantum-coherent process: "it was shown
    that intentionally added decoherence reduced the contrast in the data, a
    hallmark of a quantum-coherent process". If contrast does NOT drop, there
    was never a quantum signal to degrade.
(c) the QPU replaced by random.Random -- see classical_control.py.

Every arm shares the decoder, the d*P == Q oracle and the success criterion, so
the only variable is where the candidates come from. That is the entire design.

Budget discipline
-----------------
The free Open Plan allowance is 600 QPU-seconds per rolling 28 days, and the
service default execution cap is three hours -- eighteen times the whole monthly
budget. max_execution_time is therefore pinned explicitly on every submission;
a single runaway job would otherwise cost a month of experiments.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from qiskit import transpile
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2

from ecdlp_ladder import build_challenge, solve, verify
from honest_oracle import build_ecdlp_circuit, decode_candidates

RESULTS = Path(__file__).parent / "results"


def joint_counts(pub_result, m: int) -> dict:
    """
    Normalise hardware output to the two-register, space-separated form the
    decoder already validated against a noise-free simulator.

    join_data() concatenates classical registers with the LAST-declared one
    first, matching Aer's "mb ma" convention, so a single space inserted after
    the first m characters reproduces it exactly.
    """
    raw = pub_result.join_data().get_counts()
    return {f"{s[:m]} {s[m:]}": c for s, c in raw.items()}


def dephase(circuit, backend, t2_multiples: float = 1.0, slices: int = 4):
    """
    Arm (b): idle the qubits for a controlled multiple of T2, without changing
    the unitary being computed. The circuit performs the same function; it just
    spends longer holding the state while doing nothing.

    Dosed in multiples of the device's own median T2 rather than in absolute
    time. A first version added a fixed ~20 us -- about 10% of the circuit's
    195 us duration -- which moved the measured share by less than one standard
    deviation and so tested nothing. Decoherence has to be dosed against the
    coherence time to be a dose at all.

    Inserted in `slices` chunks spread through the circuit rather than as one
    block at the end, so the idling overlaps the computation rather than
    following it.
    """
    from qiskit.circuit import Delay
    import statistics as _st

    props = backend.properties()
    t2 = []
    for q in range(backend.num_qubits):
        try:
            t2.append(props.t2(q))
        except Exception:
            pass
    median_t2 = _st.median(t2)

    total_idle = t2_multiples * median_t2
    per_slice = total_idle / slices

    out = circuit.copy()
    for _ in range(slices):
        out.barrier()
        for q in range(out.num_qubits):
            out.append(Delay(per_slice, unit="s"), [q])
    out.barrier()
    return out


def run_arm(bits: int, arm: str, backend_name: str = "ibm_fez",
            shots: int = 256, trials: int = 1, max_seconds: int = 300) -> dict:
    service = QiskitRuntimeService()
    backend = service.backend(backend_name)

    ch = build_challenge(bits)
    oc = build_ecdlp_circuit(ch)
    circuit = oc.circuit if arm == "a" else dephase(oc.circuit, backend)

    isa = transpile(circuit, backend=backend, optimization_level=3,
                    seed_transpiler=20260801)
    cz = dict(isa.count_ops()).get("cz", 0)

    sampler = SamplerV2(mode=backend)
    sampler.options.max_execution_time = max_seconds

    job = sampler.run([isa] * trials, shots=shots)
    print(f"submitted {job.job_id()} -> {backend_name} "
          f"({bits}-bit arm {arm}, {trials}x{shots} shots, {cz} cz)")

    started = time.time()
    result = job.result()
    elapsed = time.time() - started

    # The answer is consulted only now, to score results -- never to build them.
    key = solve(ch)
    assert verify(ch, key)

    per_trial = []
    for i in range(trials):
        counts = joint_counts(result[i], oc.reg_bits)
        ranked = decode_candidates(counts, oc.reg_bits, ch.n)
        order = [k for k, _ in ranked]
        total = sum(v for _, v in ranked) or 1
        per_trial.append({
            "rank": order.index(key) + 1 if key in order else None,
            "share": next((v / total for k, v in ranked if k == key), 0.0),
            "distinct_candidates": len(order),
            "top5": [[k, v] for k, v in ranked[:5]],
        })

    usage = None
    try:
        usage = job.usage()
    except Exception:
        pass

    record = {
        "backend": backend_name, "bits": bits, "arm": arm,
        "n": ch.n, "p": ch.p, "key": key,
        "shots": shots, "trials": trials,
        "cz_gates": cz, "depth": isa.depth(),
        "predicted_fidelity": math.exp(-cz * 0.00275),
        "job_id": job.job_id(), "wall_seconds": round(elapsed, 1),
        "qpu_usage": usage,
        "per_trial": per_trial,
    }
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{backend_name}_{bits}bit_arm{arm}_{job.job_id()}.json"
    out.write_text(json.dumps(record, indent=2))
    return record


if __name__ == "__main__":
    import sys
    bits = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    arm = sys.argv[2] if len(sys.argv) > 2 else "a"
    backend = sys.argv[3] if len(sys.argv) > 3 else "ibm_fez"
    trials = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    rec = run_arm(bits, arm, backend, trials=trials)
    print(json.dumps({k: v for k, v in rec.items() if k != "per_trial"}, indent=2))
    for i, t in enumerate(rec["per_trial"]):
        print(f"  trial {i}: rank={t['rank']} share={t['share']:.1%} top5={t['top5'][:3]}")
