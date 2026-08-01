"""
Small-curve ECDLP challenges on Bitcoin's curve form, generated so that nobody
-- including whoever builds the quantum circuit -- knows the answer in advance.

Why this file exists
--------------------
Smolin, Smith and Vargo ("Pretending to factor large numbers on a quantum
computer", arXiv:1301.7007) state the rule that both published hardware ECDLP
results violate:

    "While there is no objection to having a classical compiler help design a
     quantum circuit ... it is not legitimate for a compiler to know the answer
     to the problem being solved."

The 5-bit demonstration (arXiv:2507.10592) hardcodes ORDER = 32, P_IDX = 1,
Q_IDX = 23 and then declares success by testing `any(k == 7 ...)` over the top
100 candidates -- out of 32 possible values of k. A test that scans a third of
the answer space for a constant the author already knows cannot fail, and
therefore measures nothing.

This module removes that failure mode structurally rather than by discipline.
Both points are derived by a deterministic nothing-up-my-sleeve rule from the
curve parameters alone, following the design of the ECDLP challenge ladder
(arXiv:2508.14011, "Brace for impact"), whose stated property is that "no
private challenge scalar is chosen in advance". The discrete log exists and is
computable -- but only AFTER the circuit is built, and only by brute force.

Scope
-----
Bitcoin's curve FORM, y^2 = x^3 + 7, over deliberately tiny prime fields. This
is not secp256k1 and nothing here bears on real keys: the whole point is to
measure how far a real quantum computer gets on a problem a laptop solves
instantly, and to publish that distance honestly.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterator, Optional

CURVE_B = 7  # y^2 = x^3 + 7, the secp256k1 form


# ── Curve arithmetic ────────────────────────────────────────────────────────
#
# Affine coordinates and Python bigints. This is small-field code for building
# challenge instances and brute-forcing their answers; it is NOT constant time
# and must never touch key material. Kept deliberately separate from anything
# in the wallet for that reason.

Point = Optional[tuple[int, int]]  # None is the point at infinity


def is_on_curve(pt: Point, p: int) -> bool:
    if pt is None:
        return True
    x, y = pt
    return (y * y - x * x * x - CURVE_B) % p == 0


def point_add(a: Point, b: Point, p: int) -> Point:
    if a is None:
        return b
    if b is None:
        return a
    (x1, y1), (x2, y2) = a, b
    if x1 == x2 and (y1 + y2) % p == 0:
        return None
    if a == b:
        # Tangent. y1 == 0 was handled above as the order-2 case.
        lam = (3 * x1 * x1) * pow(2 * y1, -1, p) % p
    else:
        lam = (y2 - y1) * pow(x2 - x1, -1, p) % p
    x3 = (lam * lam - x1 - x2) % p
    return (x3, (lam * (x1 - x3) - y1) % p)


def scalar_mul(k: int, pt: Point, p: int) -> Point:
    if k == 0 or pt is None:
        return None
    if k < 0:
        x, y = pt  # type: ignore[misc]
        return scalar_mul(-k, (x, (-y) % p), p)
    result: Point = None
    addend = pt
    while k:
        if k & 1:
            result = point_add(result, addend, p)
        addend = point_add(addend, addend, p)
        k >>= 1
    return result


def curve_order(p: int) -> int:
    """Count points by exhaustive search. O(p) -- tiny fields only."""
    squares: dict[int, list[int]] = {}
    for y in range(p):
        squares.setdefault(y * y % p, []).append(y)
    total = 1  # point at infinity
    for x in range(p):
        rhs = (x * x * x + CURVE_B) % p
        total += len(squares.get(rhs, ()))
    return total


# ── Deterministic challenge construction ────────────────────────────────────


@dataclass(frozen=True)
class Challenge:
    """One rung of the ladder. `answer` is populated only by solve()."""

    bits: int
    p: int
    n: int          # prime group order
    P: tuple[int, int]
    Q: tuple[int, int]

    def describe(self) -> str:
        return (f"{self.bits}-bit  p={self.p}  n={self.n}  "
                f"P={self.P}  Q={self.Q}")


def _nums_x_candidates(p: int, tag: bytes) -> Iterator[int]:
    """
    Nothing-up-my-sleeve x-coordinates: SHA-256 over a counter and a label
    derived from the field prime. No seed is chosen by hand, so no x can have
    been selected for a property the chooser wanted.
    """
    seed = tag + b"|p=" + str(p).encode()
    counter = 0
    while True:
        digest = hashlib.sha256(seed + b"|" + str(counter).encode()).digest()
        yield int.from_bytes(digest, "big") % p
        counter += 1


def _lift_x(x: int, p: int) -> Point:
    """The point with this x and even y, if one exists."""
    rhs = (x * x * x + CURVE_B) % p
    # p % 4 == 3 admits the closed-form square root; otherwise search.
    if p % 4 == 3:
        y = pow(rhs, (p + 1) // 4, p)
        if y * y % p != rhs:
            return None
    else:
        for y in range(p):
            if y * y % p == rhs:
                break
        else:
            return None
    return (x, min(y, p - y))


def _nums_point(p: int, tag: bytes) -> tuple[int, int]:
    for x in _nums_x_candidates(p, tag):
        pt = _lift_x(x, p)
        if pt is not None and pt != (0, 0):
            return pt
    raise AssertionError("unreachable: some x is always on the curve")


def build_challenge(bits: int) -> Challenge:
    """
    Smallest prime of the given bit length whose curve has PRIME order.

    Prime order matters for two reasons: every non-identity point is then a
    generator (so the NUMS-derived P needs no further validation), and the
    discrete log is unique modulo n, which keeps the decoding unambiguous. A
    composite order would let Pohlig-Hellman split the problem and would make
    "recovered the key" mean something different per subgroup.
    """
    lo, hi = 1 << (bits - 1), 1 << bits
    for p in range(lo | 1, hi, 2):
        if p < 5 or not _is_prime(p):
            continue
        n = curve_order(p)
        if not _is_prime(n):
            continue
        P = _nums_point(p, b"QVAULT-ECDLP-LADDER-G")
        Q = _nums_point(p, b"QVAULT-ECDLP-LADDER-Q")
        if P == Q:
            continue
        return Challenge(bits=bits, p=p, n=n, P=P, Q=Q)
    raise ValueError(f"no prime-order curve with a {bits}-bit prime")


def _is_prime(v: int) -> bool:
    if v < 2:
        return False
    for q in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if v % q == 0:
            return v == q
    d, r = v - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for a in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        x = pow(a, d, v)
        if x in (1, v - 1):
            continue
        for _ in range(r - 1):
            x = x * x % v
            if x == v - 1:
                break
        else:
            return False
    return True


def solve(ch: Challenge) -> int:
    """
    Brute-force the discrete log. Call this AFTER the circuit exists, never
    before -- that ordering is the entire Smolin argument, and it is why this
    lives in a separate function rather than in build_challenge().
    """
    acc: Point = None
    for d in range(1, ch.n):
        acc = point_add(acc, ch.P, ch.p)
        if acc == ch.Q:
            return d
    raise ValueError("Q is not in the subgroup generated by P")


def verify(ch: Challenge, d: int) -> bool:
    """The oracle every candidate is checked against: does d*P equal Q?"""
    return scalar_mul(d % ch.n, ch.P, ch.p) == ch.Q
