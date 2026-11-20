"""Package E (Phase 8): sampling engine. Expected values are typed literally; they were derived by hand from the SplitMix64 algorithm
described in docs/PHASE8_PLAN.md (Steele-Lea-Flood constants), the derivation is in each comment."""

from decimal import Decimal

import pytest

from app.engine.audit_sampling import (
    SamplingError,
    SplitMix64,
    random_sample,
    systematic_sample,
    value_sample,
)

IDS = [f"v{n:02d}" for n in range(1, 11)]


def test_W02_splitmix64_published_vector_for_seed_zero():
    g = SplitMix64(0)
    assert [g.next() for _ in range(3)] == [0xE220A8397B1DCDAF, 0x6E789E6AA1B965F4, 0x06C45D188009454F]


def test_W02_splitmix64_seed_42_first_draws():
    g = SplitMix64(42)
    assert [g.next() for _ in range(3)] == [13679457532755275413, 2949826092126892291, 5139283748462763858]


def test_W02_random_sample_seed_0_exact_ids():
    # draws 16294208416658607535, 7960286522194355700, 487617019471545679 -> mod 10, 9, 8 = 5, 0, 7
    # [0..9]: i=0 swap with 5; i=1 swap with 1; i=2 swap with 2+7=9 -> first three positions hold 5, 1, 9 -> population order 1, 5, 9
    assert random_sample(IDS, 3, 0) == ["v02", "v06", "v10"]


def test_W02_random_sample_seed_42_exact_ids():
    # draws mod 10, 9, 8 = 3, 1, 2: i=0 swap with 3 -> [3,1,2,0]; i=1 swap with 2 -> [3,2,1,0]; i=2 swap with 4 -> [3,2,4,...]
    assert random_sample(IDS, 3, 42) == ["v03", "v04", "v05"]


def test_W02_same_seed_same_sample_whatever_the_input_order():
    assert random_sample(list(reversed(IDS)), 3, 42) == ["v03", "v04", "v05"]


def test_W02_full_size_sample_is_the_whole_population():
    assert random_sample(["b", "a", "c"], 3, 7) == ["a", "b", "c"]


def test_W02_population_sorted_by_string_id():
    # string order: "10" < "2" < "9"; seed 0, N=3, n=1: first draw 16294208416658607535 mod 3 = 1 -> position 1 = "2"
    assert random_sample([9, 2, 10], 1, 0) == ["2"]


def test_W02_systematic_with_given_start_matches_plan_example():
    assert systematic_sample(IDS, 3, 42, start=1) == ["v02", "v05", "v08"]
    assert systematic_sample(IDS, 3, 42, start=0) == ["v01", "v04", "v07"]


def test_W02_systematic_start_from_first_draw():
    # interval 10 // 3 = 3; seed 42 first draw 13679457532755275413 mod 3 = 1 -> indexes 1, 4, 7
    assert systematic_sample(IDS, 3, 42) == ["v02", "v05", "v08"]
    # seed 1 first draw 0x910A2DEC89025CC1 mod 3 = 2 -> indexes 2, 5, 8
    assert systematic_sample(IDS, 3, 1) == ["v03", "v06", "v09"]


def test_W02_value_sample_key_items_at_or_above_threshold():
    items = [("a", Decimal("80000.00")), ("b", Decimal("49999.99")), ("c", Decimal("50000.00")), ("d", Decimal("10000.00"))]
    assert value_sample(items, Decimal("50000.00"), 0, 0) == ["a", "c"]


def test_W02_value_sample_adds_random_items_from_the_rest():
    items = [("a", Decimal("80000.00")), ("b", Decimal("49999.99")), ("c", Decimal("50000.00")), ("d", Decimal("10000.00"))]
    # rest sorted = [b, d]; seed 0 first draw 16294208416658607535 mod 2 = 1 -> d
    assert value_sample(items, Decimal("50000.00"), 1, 0) == ["a", "c", "d"]


@pytest.mark.parametrize("call", [
    lambda: random_sample(IDS, 0, 1),
    lambda: random_sample(IDS, 11, 1),
    lambda: random_sample(IDS, 3, -1),
    lambda: random_sample(IDS, 3, 2**63),
    lambda: random_sample(IDS, 3, None),
    lambda: random_sample(["a", "a"], 1, 1),
    lambda: systematic_sample(IDS, 3, 1, start=3),
    lambda: value_sample([("a", Decimal("1.00"))], Decimal("5.00"), 0, 1),
    lambda: value_sample([("a", Decimal("1.00"))], Decimal("5.00"), 2, 1),
    lambda: value_sample([("a", None)], Decimal("5.00"), 0, 1),
])
def test_W02_invalid_samples_are_refused_with_a_reason(call):
    with pytest.raises(SamplingError) as e:
        call()
    assert e.value.message
