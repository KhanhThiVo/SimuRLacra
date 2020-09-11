# Copyright (c) 2020, Fabio Muratore, Honda Research Institute Europe GmbH, and
# Technical University of Darmstadt.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
# 3. Neither the name of Fabio Muratore, Honda Research Institute Europe GmbH,
#    or Technical University of Darmstadt, nor the names of its contributors may
#    be used to endorse or promote products derived from this software without
#    specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL FABIO MURATORE, HONDA RESEARCH INSTITUTE EUROPE GMBH,
# OR TECHNICAL UNIVERSITY OF DARMSTADT BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER
# IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import numpy as np
import torch as to
from copy import deepcopy
from functools import reduce
from typing import Sequence, Callable

import pyrado
from pyrado.utils import get_class_name
from pyrado.utils.input_output import print_cbt
from pyrado.utils.data_processing import normalize
from pyrado.utils.tensor import atleast_2D


class FeatureStack:
    """
    Features are nonlinear transformations of the inputs.
    .. note:: We only consider 1-dim measurements, i.e. no images.
    """

    def __init__(self, feat_fcns: Sequence[Callable]):
        """
        Constructor

        :param feat_fcns: list of feature functions, each of them maps from a multi-dim input to a multi-dim output
        (e.g. identity_feat, squared_feat, exception: const_feat)
        """
        self.feat_fcns = feat_fcns

    def __str__(self):
        """ Get an information string. """
        feat_fcn_names = [f.__name__ if f is callable else str(f) for f in self.feat_fcns]
        return f'{get_class_name(self)} [' + ', '.join(feat_fcn_names) + ']'

    def __call__(self, inp: to.Tensor):
        """
        Evaluate the features for a given input.

        :param inp: input, i.e. observations in the RL setting
        :return: 1-dim tensor with a value of every feature of the input
        """
        feats_val = [f(inp) for f in self.feat_fcns]
        return to.cat(feats_val, dim=-1)

    def get_num_feat(self, inp_flat_dim: int) -> int:
        """
        Calculate the number of features which depends on the dimension of the input and the selected feature functions.

        :param inp_flat_dim: flattened dimension input to the feature functions
        :return: number of feature values
        """
        num_fcns = len(self.feat_fcns)

        # Add the number of parameters for all feature functions that are based on the observations
        num_feat = num_fcns*inp_flat_dim

        # Special cases
        if const_feat in self.feat_fcns:  # check for a function
            # We do not care about the number of observations
            num_feat = num_feat - inp_flat_dim + 1

        if any(isinstance(f, RandFourierFeat) for f in self.feat_fcns):
            # List all random fourier features
            rffs = [isinstance(f, RandFourierFeat) for f in self.feat_fcns]  # could be more that one rff
            for i, fcn in enumerate(self.feat_fcns):
                # We do not care about the number of observations, but we added them before
                num_feat -= inp_flat_dim
                # Get the number of features from the current item
                if rffs[i]:
                    num_feat += fcn.num_feat_per_dim

        if any(isinstance(f, RBFFeat) for f in self.feat_fcns):
            # List all radial basis features
            rbfs = [isinstance(f, RBFFeat) for f in self.feat_fcns]  # could be more that one rbf
            for i, fcn in enumerate(self.feat_fcns):
                # We do not care about the number of observations, but we added them before
                num_feat -= inp_flat_dim
                # Get the number of features from the current item
                if rbfs[i]:
                    num_feat += fcn.num_feat

        if any(isinstance(f, MultFeat) for f in self.feat_fcns):
            for fcn in self.feat_fcns:
                if isinstance(fcn, MultFeat):
                    # We do not care about the number of observations, but we added them before
                    num_feat = num_feat - inp_flat_dim + 1

        return num_feat


def const_feat(inp: to.Tensor):
    if len(inp.shape) == 2:
        # When the input is batched, we need to broadcast that manually
        return to.ones(inp.shape[0], 1).type_as(inp)
    else:
        # When the input is not given in batches
        return to.tensor([1.]).type_as(inp)


def identity_feat(inp: to.Tensor):
    return inp.clone()


def sign_feat(inp: to.Tensor):
    return to.sign(inp)


def abs_feat(inp: to.Tensor):
    return to.abs(inp)


def squared_feat(inp: to.Tensor):
    return to.pow(inp, 2)


def qubic_feat(inp: to.Tensor):
    return to.pow(inp, 3)


def sig_feat(inp: to.Tensor, scale: float = 1.):
    return to.sigmoid(scale*inp)


def bell_feat(inp: to.Tensor, scale: float = 1.):
    return to.exp(-scale*to.pow(inp, 2))


def sin_feat(inp: to.Tensor):
    return to.sin(inp)


def cos_feat(inp: to.Tensor):
    return to.cos(inp)


def sinsin_feat(inp: to.Tensor):
    return to.sin(inp)*to.sin(inp)


def sincos_feat(inp: to.Tensor):
    return to.sin(inp)*to.cos(inp)


class MultFeat:
    """ Feature that multiplies two dimensions of the given input / observation """

    def __init__(self, idcs: Sequence[int]):
        """
        Constructor

        :param idcs: indices of the dimensions to multiply
        """
        if not len(idcs) >= 2:
            raise pyrado.ShapeErr(msg='Provide at least provide two indices.')
        self._idcs = deepcopy(idcs)

    def __str__(self):
        """ Get an information string. """
        return f'{get_class_name(self)} (indices ' + ' '.join([str(i) for i in self._idcs]) + ')'

    def __call__(self, inp: to.Tensor) -> to.Tensor:
        """
        Evaluate the features.

        :param inp: input i.e. observations in the RL setting
        :return: feature value
        """
        return reduce(to.mul, [inp[i] for i in self._idcs]).unsqueeze(0)  # unsqueeze for later concatenation


class RandFourierFeat:
    """
    Random Fourier features

    .. seealso::
        [1] A. Rahimi and B. Recht "Random Features for Large-Scale Kernel Machines", NIPS, 2007
    """

    def __init__(self, inp_dim: int, num_feat_per_dim: int, bandwidth: Union[float, np.ndarray, to.Tensor]):
        r"""
        Gaussian kernel: $k(x,y) = \exp(-\sigma**2 / (2*d) * ||x-y||^2)$
                         Sample from $\mathcal{N}(0,1)$ and scale the result by $\sigma / \sqrt{2*d}$

        :param inp_dim: flat dimension of the inputs i.e. the observations, called $d$ in [1]
        :param num_feat_per_dim: number of random Fourier features, called $D$ in [1]. In contrast to the `RBFFeat`
                                 class, the output dimensionality, thus the number of associated policy parameters is
                                 `num_feat_per_dim` and not`num_feat_per_dim * inp_dim`.
        :param bandwidth: scaling factor for the sampled frequencies.
                          Pass a constant of for example env.obs_space.bound_up.
                          According to [1] and the note above we should use d here.
                          Actually, it is not a bandwidth since it is not a frequency.
        """
        self.num_feat_per_dim = num_feat_per_dim
        self.scale = to.sqrt(to.tensor(2./num_feat_per_dim))
        # Sample omega from a standardized normal distribution
        self.freq = to.randn(num_feat_per_dim, inp_dim)
        # Scale the frequency matrix with the bandwidth factor
        if not isinstance(bandwidth, to.Tensor):
            bandwidth = to.from_numpy(np.asanyarray(bandwidth))
        self.freq *= to.sqrt(to.tensor(2.)/atleast_2D(bandwidth))
        # Sample b from a uniform distribution [0, 2pi]
        self.shift = 2*np.pi*to.rand(num_feat_per_dim)

    def __call__(self, inp: to.Tensor) -> to.Tensor:
        """
        Evaluate the features, see [1].

        .. note::
            Only processing of 1-dim input (e.g., no images)! The input can be batched along the first dimension.

        :param inp: input i.e. observations in the RL setting
        :return: 1-dim vector of all feature values given the observations
        """
        if inp.ndimension() > 2:
            raise pyrado.ShapeErr(msg='RBF class can only handle 1-dim or 2-dim input!')
        inp = atleast_2D(inp)  # first dim is the batch size, the second dim it the actual input dimension

        # Resize if batched and return the feature value
        shift = self.shift.repeat(inp.shape[0], 1)
        return self.scale*to.cos(inp@self.freq.t() + shift)


class RBFFeat:
    """ Normalized Gaussian radial basis function features """

    def __init__(self,
                 num_feat_per_dim: int,
                 bounds: [Sequence[np.ndarray], Sequence[to.Tensor], Sequence[float]],
                 scale: float = None,
                 state_wise_norm: bool = True):
        """
        Constructor

        :param num_feat_per_dim: number of radial basis functions, identical for every dimension of the input
        :param bounds: lower and upper bound for the Gaussians' centers, the input dimension is inferred from them
        :param scale: scaling factor for the squared distance, if `None` the factor is determined such that two
                      neighboring RBFs have a value of 0.2 at the other center
        :param state_wise_norm: `True` to apply the normalization across input state dimensions separately (every
                                 dimension sums to one), or `False` to jointly normalize them
        """
        if not num_feat_per_dim > 1:
            raise pyrado.ValueErr(given=num_feat_per_dim, g_constraint='1')
        if not len(bounds) == 2:
            raise pyrado.ShapeErr(given=bounds, expected_match=np.empty(2))

        # Get the bounds, e.g. from the observation space and then clip them in case the
        bounds_to = [None, None]
        for i, b in enumerate(bounds):
            if isinstance(b, np.ndarray):
                bounds_to[i] = to.from_numpy(b)
            elif isinstance(b, to.Tensor):
                bounds_to[i] = b.clone()
            elif isinstance(b, (int, float)):
                bounds_to[i] = to.tensor(b, dtype=to.get_default_dtype()).view(1, )
            else:
                raise pyrado.TypeErr(given=b, expected_type=[np.ndarray, to.Tensor, int, float])
        if any([any(np.isinf(b)) for b in bounds_to]):
            bound_lo, bound_up = [to.clamp(b, min=-1e6, max=1e6) for b in bounds_to]
            print_cbt('Clipped the bounds of the RBF centers to [-1e6, 1e6].', 'y')
        else:
            bound_lo, bound_up = bounds_to

        # Create a matrix with center locations for the Gaussians
        num_dim = len(bound_lo)
        self.num_feat = num_feat_per_dim*num_dim
        self.centers = to.empty(num_feat_per_dim, num_dim)
        for i in range(num_dim):
            # Features along columns
            self.centers[:, i] = to.linspace(bound_lo[i], bound_up[i], num_feat_per_dim)

        if scale is None:
            delta_center = self.centers[1, :] - self.centers[0, :]
            self.scale = -to.log(to.tensor(0.2))/to.pow(delta_center, 2)
        else:
            self.scale = scale

        self._state_wise_norm = state_wise_norm

    def __call__(self, inp: to.Tensor) -> to.Tensor:
        """
        Evaluate the features and normalize them.

        .. note::
            Only processing of 1-dim input (e.g., no images)! The input can be batched along the first dimension.

        :param inp: input i.e. observations in the RL setting
        :return: 1-dim vector of all feature values given the observations
        """
        if inp.ndimension() > 2:
            raise pyrado.ShapeErr(msg='RBF class can only handle 1-dim or 2-dim input!')
        inp = atleast_2D(inp)  # first dim is the batch size, the second dim it the actual input dimension
        inp = inp.reshape(inp.shape[0], 1, inp.shape[1]).repeat(1, self.centers.shape[0], 1)  # reshape explicitly

        exp_sq_dist = to.exp(-self.scale*to.pow(inp - self.centers, 2))

        feat_val = to.empty(inp.shape[0], self.num_feat)
        for i, sample in enumerate(exp_sq_dist):
            if self._state_wise_norm:
                # Normalize the features such that the activation for every state dimension sums up to one
                feat_val[i, :] = normalize(sample, axis=0, order=1).t().reshape(-1, )
            else:
                # Turn the features into a vector and normalize over all of them
                feat_val[i, :] = normalize(sample.t().reshape(-1, ), axis=-1, order=1)
        return feat_val

    def derivative(self, inp: to.Tensor) -> to.Tensor:
        """
        Compute the drivative of the features w.r.t. the inputs.

        .. note::
            Only processing of 1-dim input (e.g., no images)! The input can be batched along the first dimension.

        :param inp: input i.e. observations in the RL setting
        :return: value of all features derivatives given the observations
        """

        if inp.ndimension() > 2:
            raise pyrado.ShapeErr(msg='RBF class can only handle 1-dim or 2-dim input!')
        inp = atleast_2D(inp)  # first dim is the batch size, the second dim it the actual input dimension
        inp = inp.reshape(inp.shape[0], 1, inp.shape[1]).repeat(1, self.centers.shape[0], 1)  # reshape explicitly

        exp_sq_dist = to.exp(-self.scale*to.pow(inp - self.centers, 2))
        exp_sq_dist_d = -2*self.scale*(inp - self.centers)

        feat_val = to.empty(inp.shape[0], self.num_feat)
        feat_val_dot = to.empty(inp.shape[0], self.num_feat)

        for i, (sample, sample_d) in enumerate(zip(exp_sq_dist, exp_sq_dist_d)):
            if self._state_wise_norm:
                # Normalize the features such that the activation for every state dimension sums up to one
                feat_val[i, :] = normalize(sample, axis=0, order=1).reshape(-1, )
            else:
                # Turn the features into a vector and normalize over all of them
                feat_val[i, :] = normalize(sample.t().reshape(-1, ), axis=-1, order=1)

            feat_val_dot[i, :] = sample_d.squeeze()*feat_val[i, :] - feat_val[i, :]*sum(
                sample_d.squeeze()*feat_val[i, :])

        return feat_val_dot