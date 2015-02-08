import logging

import numpy as np
import pandas as pd

from tardis.plasma.plasma_properties import ProcessingPlasmaProperty

logger = logging.getLogger(__name__)

class PhiSahaNebular(ProcessingPlasmaProperty):
    """
    Calculating the ionization equilibrium using the Saha equation, where i is atomic number,
    j is the ion_number, :math:`n_e` is the electron density, :math:`Z_{i, j}` are the partition functions
    and :math:`\chi` is the ionization energy. For the `NebularPlasma` we first calculate the
    ionization balance assuming LTE conditions (:math:`\\Phi_{i, j}(\\textrm{LTE})`) and use factors to more accurately
    describe the plasma. The two important factors are :math:`\\zeta` - a correction factor to take into account
    ionizations from excited states. The second factor is :math:`\\delta` , adjusting the ionization balance for the fact that
    there's more line blanketing in the blue.

    The :math:`\\zeta` factor for different temperatures is read in to the `~tardis.atomic.NebularAtomData` and then
    interpolated for the current temperature.

    The :math:`\\delta` factor is calculated with :meth:`calculate_radiation_field_correction`.

    Finally the ionization balance is adjusted (as equation 14 in :cite:`1993A&A...279..447M`):

    .. math::


        \\Phi_{i,j} =& \\frac{N_{i, j+1} n_e}{N_{i, j}} \\\\

        \\Phi_{i, j} =& W \\times[\\delta \\zeta + W ( 1 - \\zeta)] \\left(\\frac{T_\\textrm{e}}{T_\\textrm{R}}\\right)^{1/2}
        \\Phi_{i, j}(\\textrm{LTE})

    """

    def calculate(self):
        logger.debug('Calculating Saha using Nebular approximation')

        phis = self.calculate_saha_lte()
        if self.delta_treatment is None:
            delta = self.calculate_radfield_correction().ix[phis.index]
        else:
            delta = self.delta_treatment

        zeta_data = self.atom_data.zeta_data
        try:
            zeta = interpolate.interp1d(zeta_data.columns.values, zeta_data.ix[phis.index].values)(self.t_rads)
        except ValueError:
            raise ValueError('t_rads outside of zeta factor interpolation'
                             ' zeta_min={0:.2f} zeta_max={1:.2f} '
                             '- requested {2}'.format(
                zeta_data.columns.values.min(), zeta_data.columns.values.max(),
                self.t_rads))
        else:
            # fixing missing nan data
            # issue created - fix with warning some other day
            zeta[np.isnan(zeta)] = 1.0

        phis *= self.ws * (delta * zeta + self.ws * (1 - zeta)) * \
                (self.t_electrons / self.t_rads) ** .5

        return phis

class PhiSahaLTE(ProcessingPlasmaProperty):
    """
    Calculating the ionization equilibrium using the Saha equation, where i is atomic number,
    j is the ion_number, :math:`n_e` is the electron density, :math:`Z_{i, j}` are the partition functions
    and :math:`\chi` is the ionization energy.

    .. math::


        \\Phi_{i,j} = \\frac{N_{i, j+1} n_e}{N_{i, j}}

        \\Phi_{i, j} = g_e \\times \\frac{Z_{i, j+1}}{Z_{i, j}} e^{-\chi_{j\\rightarrow j+1}/k_\\textrm{B}T}

    """
    name = 'phi'
    inputs = ['g_electron', 'beta_rad', 'partition_function',
              'ionization_data']
    type_str = []

    @staticmethod
    def calculate(g_electron, beta_rad, partition_functions,
                  ionization_data):

        logger.debug('Calculating Saha using LTE approximation')

        def calculate_phis(group):
            return group[1:] / group[:-1].values

        phis = partition_functions.groupby(level='atomic_number').apply(
            calculate_phis)

        phis = pd.DataFrame(phis.values, index=phis.index.droplevel(0))

        phi_coefficient = (2 * g_electron * np.exp(np.outer(
            ionization_data.ionization_energy.ix[phis.index].values, beta_rad)))

        return phis * phi_coefficient


class RadiationFieldCorrection():
    """
    Calculating radiation field correction factors according to Mazzali & Lucy 1993 (:cite:`1993A&A...279..447M`; henceforth ML93)


    In ML93 the radiation field correction factor is denoted as :math:`\\delta` and is calculated in Formula 15 & 20

    The radiation correction factor changes according to a ionization energy threshold :math:`\\chi_\\textrm{T}`
    and the species ionization threshold (from the ground state) :math:`\\chi_0`.

    For :math:`\\chi_\\textrm{T} \\ge \\chi_0`

    .. math::
        \\delta = \\frac{T_\\textrm{e}}{b_1 W T_\\textrm{R}} \\exp(\\frac{\\chi_\\textrm{T}}{k T_\\textrm{R}} -
        \\frac{\\chi_0}{k T_\\textrm{e}})

    For :math:`\\chi_\\textrm{T} < \\chi_0`

    .. math::self.beta_rads * chi_0
        \\delta = 1 - \\exp(\\frac{\\chi_\\textrm{T}}{k T_\\textrm{R}} - \\frac{\\chi_0}{k T_\\textrm{R}}) + \\frac{T_\\textrm{e}}{b_1 W T_\\textrm{R}} \\exp(\\frac{\\chi_\\textrm{T}}{k T_\\textrm{R}} -
        \\frac{\\chi_0}{k T_\\textrm{e}}),

    where :math:`T_\\textrm{R}` is the radiation field Temperature, :math:`T_\\textrm{e}` is the electron temperature and W is the
    dilution factor.

    Parameters
    ----------
    phi_table : `~astropy.table.Table`
        a table containing the field 'atomic_number', 'ion_number', 'phi'

    departure_coefficient : `~float` or `~None`, optional
        departure coefficient (:math:`b_1` in ML93) For the default (`None`) it is set to 1/W.

    chi_0_species : `~tuple`, optional
        This describes which ionization energy to use for the threshold. Default is Calcium II
        (1044 Angstrom; useful for Type Ia)
        For Type II supernovae use Lyman break (912 Angstrom) or (1,1) as the tuple

    Returns
    -------

    This function adds a field 'delta' to the phi table given to the function

    """

    def calculate(self, w, departure_coefficient=None, chi_0_species=(20, 2)):
        #factor delta ML 1993
        if departure_coefficient is None:
            departure_coefficient = 1. / self.ws

        ionization_data = self.atom_data.ionization_data

        chi_0 = ionization_data.ionization_energy.ix[chi_0_species]
        radiation_field_correction = -np.ones((len(ionization_data), len(self.beta_rads)))
        less_than_chi_0 = (ionization_data.ionization_energy < chi_0).values

        factor_a =  (self.t_electrons / (departure_coefficient * self.ws * self.t_rads))

        radiation_field_correction[~less_than_chi_0] = factor_a * \
                                     np.exp(np.outer(ionization_data.ionization_energy.values[~less_than_chi_0],
                                                     self.beta_rads - self.beta_electrons))




        radiation_field_correction[less_than_chi_0] = 1 - np.exp(np.outer(ionization_data.ionization_energy.values
                                                                      [less_than_chi_0], self.beta_rads)
                                                                 - self.beta_rads * chi_0)
        radiation_field_correction[less_than_chi_0] += factor_a * np.exp(
            np.outer(ionization_data.ionization_energy.values[less_than_chi_0], self.beta_rads) -
             chi_0*self.beta_electrons)

        return pd.DataFrame(radiation_field_correction, columns=np.arange(len(self.t_rads)),
                            index=ionization_data.index)

class IonPopulation(ProcessingPlasmaProperty):
    """
    Calculate the ionization balance

    .. math::
        N(X) = N_1 + N_2 + N_3 + \\dots

        N(X) = (N_2/N_1) \\times N_1 + (N3/N2) \\times (N_2/N_1) \\times N_1 + \\dots

        N(X) = N_1(1 + N_2/N_1 + (N_3/N_2) \\times (N_2/N_1) + \\dots

        N(X) = N_1(1+ \\Phi_{i,j}/N_e + \\Phi_{i, j}/N_e \\times \\Phi_{i, j+1}/N_e + \\dots)

    """

    inputs = ['phi']

    def __init__(self, plasma_parent, ion_zero_threshold=1e-20):
        self.ion_zero_threshold = ion_zero_threshold
        super(IonPopulation, self).__init__(plasma_parent)

    @staticmethod
    def calculate(phi):
        #TODO see if self.ion_populations is None is needed (first class should be enough)
        if not hasattr(self, 'ion_populations'):
            self.ion_populations = pd.DataFrame(index=self.partition_functions.index.copy(),
                                                columns=np.arange(len(self.t_rads)), dtype=np.float64)

        for atomic_number, groups in phis.groupby(level='atomic_number'):
            current_phis = (groups / self.electron_densities).replace(np.nan, 0.0).values
            phis_product = np.cumproduct(current_phis, axis=0)

            neutral_atom_density = self.number_densities.ix[atomic_number] / (1 + np.sum(phis_product, axis=0))



            self.ion_populations.ix[atomic_number].values[0] = neutral_atom_density.values
            self.ion_populations.ix[atomic_number].values[1:] = neutral_atom_density.values * phis_product
            self.ion_populations[self.ion_populations < ion_zero_threshold] = 0.0
