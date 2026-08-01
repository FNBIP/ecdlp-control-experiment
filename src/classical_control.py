"""
Arm (c) of the falsification test: what a fair coin achieves.

The claim under test
--------------------
Two published results claim hardware recovery of elliptic-curve private keys:
arXiv:2507.10592 (5-bit, ibm_torino) and the Q-Day Prize winner
(github.com/GiancarloLelli/quantum, 15-bit, ibm_fez -- one of the very backends
this project has access to). Both recover the key the same way: each shot yields
a candidate scalar d, and d is accepted if d*P == Q.

That acceptance test is classical, exact, and free. It does not care where the
candidate came from. So a run that produces uniformly random candidates and
checks each one has a well-defined, computable success probability -- and any
claim of quantum advantage has to beat it.

    P(success) = 1 - (1 - 1/n)^shots

The winner's own README reports circuit fidelity between 1e-214 and 1e-244. At
those numbers no coherent amplitude survives, so the honest prior is that the
candidates ARE uniformly random and the two probabilities coincide. This module
computes the baseline exactly, so the hardware runs have a number to be measured
against rather than a story to be told about.

Why this arm runs first
-----------------------
It costs zero QPU seconds. The free Open Plan allowance is 600 QPU-seconds per
28-day rolling window; a deep ECDLP job costs ~54 s. Spending eleven of those
without first knowing the null hypothesis would be spending the entire budget to
learn nothing. The power analysis below answers the question that decides the
experiment: how many hardware runs are needed before a difference could even be
detected? The Q-Day winner's own control used ten trials and reached p = 0.121 --
not significant, and not enough to distinguish the two hypotheses either way.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from ecdlp_ladder import Challenge, verify


# ── The null hypothesis, exactly ────────────────────────────────────────────


def baseline_success_probability(n: int, shots: int) -> float:
    """
    Probability that at least one of `shots` uniform draws from Z_n hits the
    key. Computed via expm1/log1p rather than 1-(1-1/n)**shots, which loses all
    precision once 1/n falls below the float epsilon -- exactly the regime the
    large challenges live in.
    """
    if n <= 1 or shots <= 0:
        return 0.0
    return -math.expm1(shots * math.log1p(-1.0 / n))


def shots_for_probability(n: int, target: float) -> int:
    """Shots needed for the coin to reach `target` success probability."""
    if not 0.0 < target < 1.0:
        raise ValueError("target must lie strictly between 0 and 1")
    return math.ceil(math.log1p(-target) / math.log1p(-1.0 / n))


# ── The same thing, measured rather than derived ────────────────────────────


@dataclass(frozen=True)
class TrialResult:
    trials: int
    successes: int
    shots_per_trial: int
    n: int

    @property
    def observed_rate(self) -> float:
        return self.successes / self.trials if self.trials else 0.0

    @property
    def expected_rate(self) -> float:
        return baseline_success_probability(self.n, self.shots_per_trial)


def run_classical_arm(
    ch: Challenge, shots: int, trials: int, seed: int = 0
) -> TrialResult:
    """
    Arm (c) proper: replace the QPU with random.Random and keep everything else
    -- the candidate loop, the d*P == Q oracle, the success criterion --
    byte-for-byte identical to what the hardware arms will use.

    Note what is NOT done here: the answer is never consulted. verify() re-derives
    d*P and compares against Q, which is precisely the check the published runs
    perform, and it is the only thing standing between "a quantum computer found
    the key" and "something enumerated candidates until one matched".
    """
    rng = random.Random(seed)
    successes = 0
    for _ in range(trials):
        for _ in range(shots):
            if verify(ch, rng.randrange(1, ch.n)):
                successes += 1
                break
    return TrialResult(
        trials=trials, successes=successes, shots_per_trial=shots, n=ch.n
    )


# ── How many hardware runs would settle it ──────────────────────────────────


def trials_needed(p_null: float, p_alt: float,
                  alpha: float = 0.05, power: float = 0.80) -> int:
    """
    Trials required for a one-sided test of H0: p = p_null against p = p_alt.

    The null rate is known analytically rather than estimated, which is the one
    genuinely favourable feature of this experiment: there is no uncertainty on
    the control side to pay for.

    Returned as a hard requirement to fix BEFORE running, not a number to seek
    afterwards. Choosing the trial count once the results are in is how a 0.8%
    coincidence becomes a headline.
    """
    if not 0.0 < p_null < 1.0 or not 0.0 < p_alt < 1.0:
        raise ValueError("rates must lie strictly between 0 and 1")
    if p_alt <= p_null:
        raise ValueError("alternative must exceed the null to be detectable")
    z_a = _normal_quantile(1.0 - alpha)
    z_b = _normal_quantile(power)
    numerator = (z_a * math.sqrt(p_null * (1 - p_null))
                 + z_b * math.sqrt(p_alt * (1 - p_alt)))
    return math.ceil((numerator / (p_alt - p_null)) ** 2)


def binomial_tail_p_value(successes: int, trials: int, p_null: float) -> float:
    """Exact one-sided binomial p-value, P(X >= successes | p_null)."""
    if successes <= 0:
        return 1.0
    total = 0.0
    for k in range(successes, trials + 1):
        total += math.comb(trials, k) * p_null**k * (1 - p_null) ** (trials - k)
    return min(total, 1.0)


def _normal_quantile(q: float) -> float:
    """Acklam's inverse normal CDF. Accurate to ~1e-9, no SciPy dependency."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if q < p_low:
        s = math.sqrt(-2 * math.log(q))
        return (((((c[0]*s+c[1])*s+c[2])*s+c[3])*s+c[4])*s+c[5]) / \
               ((((d[0]*s+d[1])*s+d[2])*s+d[3])*s+1)
    if q > p_high:
        s = math.sqrt(-2 * math.log(1 - q))
        return -(((((c[0]*s+c[1])*s+c[2])*s+c[3])*s+c[4])*s+c[5]) / \
                ((((d[0]*s+d[1])*s+d[2])*s+d[3])*s+1)
    s = q - 0.5
    r = s * s
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*s / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
