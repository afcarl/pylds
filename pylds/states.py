from __future__ import division
import numpy as np

from pybasicbayes.util.general import AR_striding

from lds_messages_interface import kalman_filter, filter_and_sample, E_step, \
    info_E_step

class LDSStates(object):
    def __init__(self,model,T=None,data=None,stateseq=None,
            generate=True,initialize_from_prior=False,initialize_to_noise=True):
        self.model = model
        self.data = data

        self.T = T if T else data.shape[0]
        self.data = data

        if stateseq is not None:
            self.stateseq = stateseq
        elif generate:
            if data is not None and not (initialize_from_prior or initialize_to_noise):
                self.resample()
            else:
                if initialize_from_prior:
                    self.generate_states()
                else:
                    self.stateseq = np.random.normal(size=(self.T,self.n))

    ### model properties

    @property
    def emission_distn(self):
        return self.model.emission_distn

    @property
    def dynamics_distn(self):
        return self.model.dynamics_distn

    @property
    def mu_init(self):
        return self.model.mu_init

    @property
    def sigma_init(self):
        return self.model.sigma_init

    @property
    def n(self):
        return self.model.n

    @property
    def p(self):
        return self.model.p

    @property
    def A(self):
        return self.model.A

    @property
    def sigma_states(self):
        return self.model.sigma_states

    @property
    def C(self):
        return self.model.C

    @property
    def sigma_obs(self):
        return self.model.sigma_obs

    @property
    def strided_stateseq(self):
        return AR_striding(self.stateseq,1)

    def log_likelihood(self):
        # TODO handle caching and stuff
        if True or self._normalizer is None:
            self._normalizer, _, _ = kalman_filter(
                self.mu_init, self.sigma_init,
                self.A, self.sigma_states, self.C, self.sigma_obs,
                self.data)
        return self._normalizer

    # generation

    def generate_states(self):
        T, n = self.T, self.n

        stateseq = self.stateseq = np.empty((T,n),dtype='double')
        stateseq[0] = np.random.multivariate_normal(self.mu_init, self.sigma_init)

        chol = np.linalg.cholesky(self.sigma_states)
        randseq = np.random.randn(T-1,n)

        for t in xrange(1,T):
            stateseq[t] = self.A.dot(stateseq[t-1]) + chol.dot(randseq[t-1])

        return stateseq

    # filtering

    def filter(self):
        self._normalizer, self.filtered_mus, self.filtered_sigmas = kalman_filter(
            self.mu_init, self.sigma_init,
            self.A, self.sigma_states, self.C, self.sigma_obs,
            self.data)

    # resampling

    def resample(self):
        self._normalizer, self.stateseq = filter_and_sample(
            self.mu_init, self.sigma_init,
            self.A, self.sigma_states, self.C, self.sigma_obs,
            self.data)

    # EM

    def E_step(self):
        self._normalizer, self.smoothed_mus, self.smoothed_sigmas, \
            E_xtp1_xtT = E_step(
                self.mu_init, self.sigma_init,
                self.A, self.sigma_states, self.C, self.sigma_obs,
                self.data)

        self._set_expected_stats(
            self.smoothed_mus,self.smoothed_sigmas,E_xtp1_xtT)

    def _set_expected_stats(self,smoothed_mus,smoothed_sigmas,E_xtp1_xtT):
        assert not np.isnan(E_xtp1_xtT).any()
        assert not np.isnan(smoothed_mus).any()
        assert not np.isnan(smoothed_sigmas).any()

        EyyT = np.einsum('ti,tj->ij',self.data,self.data)  # TODO don't redo
        EyxT = np.einsum('ti,tj->ij',self.data,smoothed_mus)
        ExxT = smoothed_sigmas.sum(0) + \
            np.einsum('ti,tj->ij',smoothed_mus,smoothed_mus)

        E_xt_xtT = \
            ExxT - (smoothed_sigmas[-1]
                    + np.outer(smoothed_mus[-1],smoothed_mus[-1]))
        E_xtp1_xtp1T = \
            ExxT - (smoothed_sigmas[0]
                    + np.outer(smoothed_mus[0], smoothed_mus[0]))

        E_xtp1_xtT = E_xtp1_xtT.sum(0)

        def is_symmetric(A):
            return np.allclose(A,A.T)
        assert is_symmetric(ExxT)
        assert is_symmetric(E_xt_xtT)
        assert is_symmetric(E_xtp1_xtp1T)

        self.E_emission_stats = np.array([EyyT, EyxT, ExxT, self.T])
        self.E_dynamics_stats = \
            np.array([E_xtp1_xtp1T, E_xtp1_xtT, E_xt_xtT, self.T-1])

    # mean field

    def meanfieldupdate(self):
        J_init, h_init = np.linalg.inv(self.sigma_init), \
            np.linalg.solve(self.sigma_init, self.mu_init)
        J_pair_22, J_pair_21, J_pair_11, _ = \
            self.dynamics_distn._mf_expected_statistics()
        _, J_yx, J_node, _ = self.emission_distn._mf_expected_statistics()
        h_node = np.einsum('ti,ij->tj',self.data,J_yx)

        self._normalizer, self.smoothed_mus, self.smoothed_sigmas, \
            E_xtp1_xtT = info_E_step(
                J_init,h_init,J_pair_11,J_pair_21,J_pair_22,J_node,h_node)

        self._set_expected_stats(
            self.smoothed_mus,self.smoothed_sigmas,E_xtp1_xtT)

    def get_vlb(self):
        if self._normalizer is None:
            self.meanfieldupdate()  # NOTE: sets self._normalizer
        return self._normalizer

