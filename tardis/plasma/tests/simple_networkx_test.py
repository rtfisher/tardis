from tardis.plasma.base import BasePlasma
from tardis.plasma.plasma_properties import (BetaRadiation,
                                             LevelBoltzmannFactor,
                                             AtomicLevels, AtomicLines)

from tardis.plasma.plasma_input import TRadiative, AtomicData


def test_simple_networkx_test1():
    bp = BasePlasma([TRadiative, BetaRadiation, LevelBoltzmannFactor, AtomicLevels, AtomicLines, AtomicData])
