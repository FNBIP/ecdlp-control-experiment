# ecdlp-control-experiment

Shor's algorithm for the elliptic-curve discrete logarithm problem, run on IBM quantum
hardware with a control experiment.

The control is the point. Two published results claim hardware recovery of elliptic-curve
private keys; neither ran one. This repository runs the smallest honest instance that
exists, runs the same circuit again with coherence deliberately destroyed, and compares
both against a coin toss.

All three perform the same.

**Total cost: 11 seconds of QPU time on IBM's free Open Plan.**

## Result

4-bit challenge (`p=13`, group order `n=7`, secret scalar `k=2`), `ibm_fez`
(Heron r2, 156 qubits), 256 shots × 20 trials per arm.

| Arm | depth | CZ | true-key share | vs uniform |
|---|---|---|---|---|
| (a) honest circuit | 1,949 | 571 | 15.34% | +2.10 σ |
| (b) + 1× T2 forced idle | 1,953 | 571 | 17.06% | +4.20 σ |
| (b) + 4× T2 forced idle | 1,953 | 571 | 16.94% | +5.16 σ |
| (c) classical random | — | — | 14.29% | — |

Noise-free simulation of the same circuit recovers `k=2` at rank 1 with **62.8%**.

### The control changed the conclusion

Arm (a) sits marginally above uniform at +2.10 σ. Reported alone, that reads as a weak
quantum signal.

It is not. **The elevation grows as coherence is destroyed** — +2.10 σ at zero dose,
+5.16 σ after 4×T2 of forced idling. A quantum interference signal must *decrease* under
decoherence. This increases, so the excess is systematic bias in readout and decoding, not
interference.

Smolin, Smith and Vargo named this test in 2013:

> "it was shown that intentionally added decoherence reduced the contrast in the data, a
> hallmark of a quantum-coherent process"

Without it, this repository would have reported a positive result.

### Why it fails

Not qubit count. The circuit uses **9 of 156 available qubits**.

The circuit runs 1,949 layers ≈ **195 µs**. Median T2 on `ibm_fez` is **88 µs**. The
computation takes **2.2× longer than the qubits stay coherent**, so the state is gone
before the measurement.

The failure has a fingerprint: `k=0` — what you decode from the all-zeros ground state —
was the top candidate in **16 of 20 trials (80%)**. That is relaxation, not computation.

## The honest oracle

Shor's ECDLP algorithm prepares `Σ|a⟩|b⟩|aP + bQ⟩`. The third register can be built two
ways, and they are not equivalent.

**Cheap and circular** — label each point by its discrete logarithm base `P`, so `iP`
becomes the integer `i`. The group law collapses to addition mod `n`. But `Q`'s label *is*
`k`, so writing the oracle down requires already having the answer.

**Honest** — label points by a canonical ordering of their coordinates and implement the
actual group law. Both permutations derive from the curve, `P` and `Q`, all public. `k`
never appears at construction time.

This repository does the second, which is why its circuits are far more expensive than the
published ones. Challenge points are SHA-256-derived (nothing-up-my-sleeve) following the
design of [arXiv:2508.14011](https://arxiv.org/abs/2508.14011), so no private scalar is
chosen in advance. The answer is computed only after the circuit exists, by brute force, to
score results — never to build them.

## On arXiv:2507.10592

The published 5-bit result uses the circular encoding: `ORDER = 32`, `P_IDX = 1`,
`Q_IDX = 23`, so the scalar is `k = 23` by construction.

Exact noise-free simulation of that circuit (`src/` reproduces this in seconds):

- Peaks lie on the ridge `b ≡ 23a (mod 32)`, probability 1/32 on each of 32 ridge points
- The paper's stated decode `k = −a·b⁻¹` yields **25**
- The reported **7** is `23⁻¹ mod 32` — the same ridge read with registers exchanged
- Its success test, `any(k == 7)` over the top 100 candidates from a **32-value space**,
  returns `False` on ideal data and passed on hardware because that data was noise

Circuit fidelity at the paper's own gate counts (34,319 CZ at 3e-3) is ~10⁻⁴⁵.

## Distance to secp256k1

| | this experiment | secp256k1 |
|---|---|---|
| Logical qubits | 0 | ~1,200 |
| Physical qubits | 156 (uncorrected) | ~500,000 |
| Circuit depth | 880 coherent layers available | ~9×10⁸ layers |

Resource estimates from Babbush et al. 2026 ([IACR ePrint 2026/625](https://eprint.iacr.org/2026/625)).
The gap is ~10⁶× in depth, and 156 physical qubits without error correction provide **zero**
logical qubits.

## Limitations

- **One curve size.** The 4-bit instance failed, so larger rungs were not run. The 6-bit
  instance transpiles to 19,517 CZ gates (predicted fidelity 5×10⁻²⁴) and would fail harder.
- **Arm (b) was underdosed on the first attempt.** A fixed ~20 µs delay moved the result by
  less than one standard deviation and tested nothing. The T2-relative sweep replaced it.
  Both are in the history.
- **This oracle is exponential in register width** because it synthesises arbitrary
  basis-state permutations. A polynomial construction (Roetteler et al.) would be cheaper.
  The gate counts here bound *this* implementation, not the fundamental difficulty.
- **20 trials per arm.** Enough to exclude a large effect, not a subtle one.
- **One backend.** `ibm_kingston` has better error rates (7.84e-4 best-edge vs 1.34e-3) but
  had 700+ queued jobs.

## Reproduce

```
pip install -r requirements.txt
python src/run_experiment.py 4 a ibm_fez 20
```

Requires an IBM Quantum account. The free Open Plan suffices — this entire experiment used
11 of the 600 QPU-seconds available per 28-day window.

Job IDs are recorded in `results/` so the runs can be independently confirmed.

## License

MIT.
