"""Sampling helpers (package E): random, systematic and value-based, deterministic for a given seed (own SplitMix64 generator, not the random
module, so results do not change between Python versions). Pure Python. Interface in docs/PHASE8_PLAN.md section Sampling.

Rules (W-02): the population is sorted by string id first; the same seed and population always give the same ids; the result is returned in
population (sorted) order. Amounts are Decimal. Nothing here reads a database or global random state.
"""

from collections.abc import Sequence
from decimal import Decimal

_MASK = (1 << 64) - 1
_GAMMA = 0x9E3779B97F4A7C15
_MUL1 = 0xBF58476D1CE4E5B9
_MUL2 = 0x94D049BB133111EB
MAX_SEED = (1 << 63) - 1   # the database column is a signed bigint


class SamplingError(ValueError):
    """A sample that cannot be drawn. The service turns it into `sample_invalid`."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SplitMix64:
    """SplitMix64 (Steele, Lea, Flood 2014). seed 0 gives 0xE220A8397B1DCDAF, 0x6E789E6AA1B965F4, 0x06C45D188009454F, ..."""

    def __init__(self, seed: int):
        self._state = seed & _MASK

    def next(self) -> int:
        self._state = (self._state + _GAMMA) & _MASK
        z = self._state
        z = ((z ^ (z >> 30)) * _MUL1) & _MASK
        z = ((z ^ (z >> 27)) * _MUL2) & _MASK
        return z ^ (z >> 31)


def check_seed(seed: object) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_SEED:
        raise SamplingError("A sample needs a whole-number seed between 0 and 9223372036854775807; it is stored so the sample can be repeated.")
    return seed


def _population(ids: Sequence[object]) -> list[str]:
    population = sorted(str(i) for i in ids)
    if len(set(population)) != len(population):
        raise SamplingError("The population has the same id more than once, so a sample cannot be drawn from it.")
    return population


def _check_size(size: object, population_count: int) -> int:
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise SamplingError("The sample size must be a whole number of at least 1.")
    if size > population_count:
        raise SamplingError(f"The sample size {size} is larger than the population of {population_count} items.")
    return size


def random_sample(ids: Sequence[object], n: int, seed: int) -> list[str]:
    """Partial Fisher-Yates over the sorted population: step i swaps position i with i + (draw mod (N - i)); the first n positions are
    the sample, returned in population order."""
    check_seed(seed)
    population = _population(ids)
    n = _check_size(n, len(population))
    gen = SplitMix64(seed)
    order = list(range(len(population)))
    for i in range(n):
        j = i + gen.next() % (len(population) - i)
        order[i], order[j] = order[j], order[i]
    return [population[k] for k in sorted(order[:n])]


def systematic_sample(ids: Sequence[object], n: int, seed: int, start: int | None = None) -> list[str]:
    """Every interval-th item, interval = N // n; start = first draw mod interval unless `start` (0-based, below the interval) is given."""
    check_seed(seed)
    population = _population(ids)
    n = _check_size(n, len(population))
    interval = len(population) // n
    if start is None:
        start = SplitMix64(seed).next() % interval
    elif isinstance(start, bool) or not isinstance(start, int) or not 0 <= start < interval:
        raise SamplingError(f"The start must be a whole number from 0 to {interval - 1} for this population and size.")
    return [population[start + k * interval] for k in range(n)]


def value_sample(items: Sequence[tuple[object, Decimal | None]], threshold: Decimal, n_rest: int, seed: int) -> list[str]:
    """Every item with amount at or above `threshold` (key items), plus `n_rest` random items from the rest. Result in population order."""
    check_seed(seed)
    if not isinstance(threshold, Decimal) or threshold < 0:
        raise SamplingError("The value threshold must be an amount of zero or more.")
    if isinstance(n_rest, bool) or not isinstance(n_rest, int) or n_rest < 0:
        raise SamplingError("The number of items to add from the rest must be zero or more.")
    amounts = {str(i): a for i, a in items}
    if len(amounts) != len(items):
        raise SamplingError("The population has the same id more than once, so a sample cannot be drawn from it.")
    if any(not isinstance(a, Decimal) for a in amounts.values()):
        raise SamplingError("A value sample needs an amount for every item of the population.")
    key = [i for i in sorted(amounts) if amounts[i] >= threshold]
    rest = [i for i in sorted(amounts) if amounts[i] < threshold]
    if n_rest > len(rest):
        raise SamplingError(f"{n_rest} items were asked from the rest but only {len(rest)} items are below the threshold.")
    picked = random_sample(rest, n_rest, seed) if n_rest else []
    if not key and not picked:
        raise SamplingError("No item is at or above the threshold and no extra items were asked for: the sample would be empty.")
    return sorted(key + picked)
