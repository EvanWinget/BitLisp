"""Hypothesis profiles shared by every suite."""

from hypothesis import settings

# Hypothesis's default 200 ms deadline is a latency check, not an
# oracle. The mutation harness runs many suites in parallel on a
# loaded machine, where overruns would report false kills, so it
# selects this profile with --hypothesis-profile=mutate. Nothing loads
# it by default.
settings.register_profile("mutate", deadline=None)
