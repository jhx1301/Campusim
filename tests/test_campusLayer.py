import numpy as np
import covasim as cv


def test_campus_layers_and_groups():
    sim = cv.Sim(pop_type='campus', pop_size=3000, n_days=3, rand_seed=1, verbose=0)
    sim.initialize()

    keys = set(sim.people.contacts.keys())
    assert keys == {'d', 'clu', 'clg', 'of', 'ta', 'cm'}, f"contacts keys mismatch: {keys}"

    sl = sim.people.student_level
    assert len(sl) == sim['pop_size'], f"student_level length mismatch: {len(sl)} != {sim['pop_size']}"
    assert np.isin(sl, [0, 1, 2]).all(), "student_level contains values outside {0,1,2}"

    for i, grp in enumerate(sim.people.class_groups_ug):
        if len(grp['students']):
            assert np.all(sim.people.student_level[grp['students']] == 0), \
                f"Undergraduate class group {i} contains non-undergraduate students"

    for i, grp in enumerate(sim.people.class_groups_gr):
        if len(grp['students']):
            assert np.all(sim.people.student_level[grp['students']] == 1), \
                f"Graduate class group {i} contains non-graduate students"

    print("test_campus_layers_and_groups: PASSED")


def test_campus_ta_non_student_only():
    sim = cv.Sim(pop_type='campus', pop_size=2000, n_days=2, rand_seed=2, verbose=0)
    sim.initialize()

    ta = sim.people.contacts['ta']
    non_student = (sim.people.student_level != 0) & (sim.people.student_level != 1)

    if len(ta['p1']):
        assert non_student[ta['p1']].all(), "ta['p1'] contains students"
        assert non_student[ta['p2']].all(), "ta['p2'] contains students"

    print("test_campus_ta_non_student_only: PASSED")


if __name__ == "__main__":
    try:
        test_campus_layers_and_groups()
        test_campus_ta_non_student_only()
        print("\nAll tests passed.")
    except AssertionError as e:
        print(f"\nTest failed: {e}")
    except Exception as e:
        print(f"\nRuntime error: {e}")