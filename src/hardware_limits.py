"""
What 156 qubits can and cannot do, measured rather than estimated.

The ECDLP run established that the binding constraint is DEPTH, not width: nine
of 156 qubits were used, and the circuit died because it ran 195 us against a
median T2 of 88 us. Two claims followed from calibration data rather than from
measurement, and this module measures them.

  A. Where the depth wall actually is. Mirror circuits -- U followed by U-dagger,
     which must return |00...0> -- at increasing depth. The depth at which the
     return probability crosses 1/2 is the usable coherent depth of the device,
     measured on the device, on the day.

  B. That the wall is not made of qubits. A shallow GHZ entangler across 10 to
     100+ qubits. If wide-and-shallow succeeds while narrow-and-deep fails, the
     "just add more qubits" intuition is wrong in a way a figure can show.

  D. Grover against a toy hash, which is the attack that matters for hash-based
     signatures rather than for ECDSA. Included because a wallet built on
     one-time signatures should demonstrate the attack on its OWN primitive, and
     show that it buys only a square root.

Honest labelling note for B: the reported statistic is the fraction of shots
landing on all-zeros or all-ones. That is a decoherence probe, NOT a GHZ
entanglement witness -- a classically correlated mixture scores identically. It
demonstrates that correlation survived across N qubits, which is the width claim
being tested, and nothing stronger. A real witness needs parity oscillations.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from qiskit import QuantumCircuit, transpile
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2

RESULTS = Path(__file__).parent.parent / "results"


# ── A. Where the depth wall is ──────────────────────────────────────────────


def mirror_circuit(nq: int, layers: int, seed: int) -> QuantumCircuit:
    """
    U then U-dagger. Noise-free this returns |00...0> with probability 1 for any
    depth, so every departure from 1 is the device, not the algorithm. That is
    what makes it a measurement of the hardware rather than of the circuit.
    """
    import random

    rng = random.Random(seed)
    u = QuantumCircuit(nq)
    for _ in range(layers):
        for q in range(nq):
            u.rz(rng.uniform(0, 2 * math.pi), q)
            u.sx(q)
        offset = rng.randint(0, 1)
        for q in range(offset, nq - 1, 2):
            u.cz(q, q + 1)

    qc = QuantumCircuit(nq, nq)
    qc.compose(u, inplace=True)
    qc.barrier()
    qc.compose(u.inverse(), inplace=True)
    qc.measure(range(nq), range(nq))
    return qc


def run_depth_cliff(backend, nq=9, depths=(1, 2, 5, 10, 20, 50, 100, 200),
                    shots=512) -> dict:
    circuits = [mirror_circuit(nq, d, seed=1000 + d) for d in depths]
    isa = [transpile(c, backend=backend, optimization_level=1,
                     seed_transpiler=20260801) for c in circuits]

    sampler = SamplerV2(mode=backend)
    sampler.options.max_execution_time = 300
    job = sampler.run(isa, shots=shots)
    res = job.result()

    zero = "0" * nq
    out = []
    for i, d in enumerate(depths):
        counts = res[i].data.c.get_counts()
        total = sum(counts.values())
        out.append({
            "layers": d,
            "cz": dict(isa[i].count_ops()).get("cz", 0),
            "transpiled_depth": isa[i].depth(),
            "return_probability": counts.get(zero, 0) / total,
        })
    return {"experiment": "A_depth_cliff", "backend": backend.name,
            "qubits": nq, "shots": shots, "job_id": job.job_id(),
            "qpu_seconds": _usage(job), "points": out}


# ── B. That the wall is not made of qubits ──────────────────────────────────


def ghz_circuit(nq: int) -> QuantumCircuit:
    """
    Tree entangler: depth grows as log2(nq), so 100 qubits costs ~7 layers of
    CX. Deliberately the opposite shape to the ECDLP circuit -- as wide as the
    device allows and as shallow as the problem allows.
    """
    qc = QuantumCircuit(nq, nq)
    qc.h(0)
    step = 1
    while step < nq:
        for src in range(0, nq - step, 2 * step):
            qc.cx(src, src + step)
        step *= 2
    qc.measure(range(nq), range(nq))
    return qc


def run_width_proof(backend, widths=(10, 25, 50, 100), shots=512) -> dict:
    circuits = [ghz_circuit(n) for n in widths]
    isa = [transpile(c, backend=backend, optimization_level=3,
                     seed_transpiler=20260801) for c in circuits]

    sampler = SamplerV2(mode=backend)
    sampler.options.max_execution_time = 300
    job = sampler.run(isa, shots=shots)
    res = job.result()

    out = []
    for i, n in enumerate(widths):
        counts = res[i].data.c.get_counts()
        total = sum(counts.values())
        allsame = counts.get("0" * n, 0) + counts.get("1" * n, 0)
        out.append({
            "qubits": n,
            "cx": dict(isa[i].count_ops()).get("cz", 0)
                  + dict(isa[i].count_ops()).get("cx", 0),
            "transpiled_depth": isa[i].depth(),
            # Decoherence probe, not an entanglement witness. See module docstring.
            "correlated_fraction": allsame / total,
            "depolarised_expectation": 2 / (2 ** n),
        })
    return {"experiment": "B_width_proof", "backend": backend.name,
            "shots": shots, "job_id": job.job_id(),
            "qpu_seconds": _usage(job), "points": out}


# ── D. Grover against a toy hash ────────────────────────────────────────────


def grover_preimage(nbits: int, target: int, iterations: int) -> QuantumCircuit:
    """
    Search for the input whose toy "hash" equals `target`.

    The oracle marks one basis state, which is the standard toy construction and
    carries the standard caveat: a real preimage oracle would compute the hash
    reversibly and cost far more. What survives the simplification is the only
    thing being claimed -- the QUADRATIC iteration count, sqrt(2^n) rather than
    2^n, and that those iterations are inherently sequential.
    """
    qc = QuantumCircuit(nbits, nbits)
    qc.h(range(nbits))

    for _ in range(iterations):
        # Oracle: phase-flip the marked state.
        for q in range(nbits):
            if not (target >> q) & 1:
                qc.x(q)
        qc.h(nbits - 1)
        qc.mcx(list(range(nbits - 1)), nbits - 1)
        qc.h(nbits - 1)
        for q in range(nbits):
            if not (target >> q) & 1:
                qc.x(q)
        # Diffuser: reflect about the uniform superposition.
        qc.h(range(nbits))
        qc.x(range(nbits))
        qc.h(nbits - 1)
        qc.mcx(list(range(nbits - 1)), nbits - 1)
        qc.h(nbits - 1)
        qc.x(range(nbits))
        qc.h(range(nbits))

    qc.measure(range(nbits), range(nbits))
    return qc


def run_grover(backend, nbits=4, target=11, shots=1024) -> dict:
    optimal = max(1, int(round(math.pi / 4 * math.sqrt(2 ** nbits))))
    iters = list(range(0, optimal + 2))
    circuits = [grover_preimage(nbits, target, k) for k in iters]
    isa = [transpile(c, backend=backend, optimization_level=3,
                     seed_transpiler=20260801) for c in circuits]

    sampler = SamplerV2(mode=backend)
    sampler.options.max_execution_time = 300
    job = sampler.run(isa, shots=shots)
    res = job.result()

    key = format(target, f"0{nbits}b")
    out = []
    for i, k in enumerate(iters):
        counts = res[i].data.c.get_counts()
        total = sum(counts.values())
        out.append({
            "iterations": k,
            "cz": dict(isa[i].count_ops()).get("cz", 0),
            "transpiled_depth": isa[i].depth(),
            "target_probability": counts.get(key, 0) / total,
        })
    return {"experiment": "D_grover_toy_hash", "backend": backend.name,
            "bits": nbits, "target": target, "optimal_iterations": optimal,
            "uniform_baseline": 1 / (2 ** nbits), "shots": shots,
            "job_id": job.job_id(), "qpu_seconds": _usage(job), "points": out}


def _usage(job):
    try:
        return job.usage()
    except Exception:
        return None


def save(record: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    name = f"{record['experiment']}_{record['backend']}_{record['job_id']}.json"
    (RESULTS / name).write_text(json.dumps(record, indent=2))
