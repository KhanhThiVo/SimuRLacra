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

"""
Train an agent to solve the Planar-3-Link task using Activation Dynamics Networks and Hill Climbing.
"""
import torch as to

from pyrado.algorithms.cem import CEM
from pyrado.environment_wrappers.action_normalization import ActNormWrapper
from pyrado.environment_wrappers.observation_normalization import ObsNormWrapper
from pyrado.environment_wrappers.observation_partial import ObsPartialWrapper
from pyrado.environments.rcspysim.planar_3_link import Planar3LinkTASim, Planar3LinkIKActivationSim
from pyrado.logger.experiment import setup_experiment, save_list_of_dicts_to_yaml
from pyrado.policies.adn import pd_cubic, ADNPolicy, pd_linear


if __name__ == '__main__':
    # Experiment (set seed before creating the modules)
    ex_dir = setup_experiment(Planar3LinkTASim.name, f'{CEM.name}_{ADNPolicy.name}', '', seed=101)

    # Environment
    env_hparams = dict(
        physicsEngine='Bullet',  # Bullet or Vortex
        dt=1/50.,
        max_steps=1200,
        task_args=dict(consider_velocities=True),
        max_dist_force=None,
        taskCombinationMethod='sum',
        checkJointLimits=True,
        collisionAvoidanceIK=True,
        observeVelocities=True,
        observeForceTorque=True,
        observeCollisionCost=False,
        observePredictedCollisionCost=False,
        observeManipulabilityIndex=False,
        observeCurrentManipulability=True,
        observeDynamicalSystemGoalDistance=True,
        observeDynamicalSystemDiscrepancy=False,
        observeTaskSpaceDiscrepancy=True,
    )
    env = Planar3LinkTASim(**env_hparams)
    # env = Planar3LinkIKActivationSim(**env_hparams)
    # env = ActNormWrapper(env)
    # eub = {
    #     'GD_DS0': 2.,
    #     'GD_DS1': 2.,
    #     'GD_DS2': 2.,
    # }
    # env = ObsNormWrapper(env, explicit_ub=eub)
    # env = ObsNormWrapper(env)
    # env = ObsPartialWrapper(env, idcs=['Effector_Xd', 'Effector_Zd'])
    env = ObsPartialWrapper(env, idcs=['Effector_DiscrepTS_X', 'Effector_DiscrepTS_Z'])
    # env = ObsPartialWrapper(env, idcs=['Effector_DiscrepTS_X', 'Effector_DiscrepTS_Z', 'Effector_Xd', 'Effector_Zd'])
    print(env)

    # Policy
    policy_hparam = dict(
        tau_init=1e-1,
        tau_learnable=True,
        kappa_init=1e-3,
        kappa_learnable=True,
        activation_nonlin=to.sigmoid,
        potentials_dyn_fcn=pd_cubic,
        potential_init_learnable=True,
    )
    policy = ADNPolicy(spec=env.spec, dt=env.dt, **policy_hparam)

    # Algorithm
    algo_hparam = dict(
        max_iter=50,
        pop_size=200,
        num_rollouts=1,
        num_is_samples=20,
        expl_std_init=1.0,
        expl_std_min=0.02,
        extra_expl_std_init=0.5,
        extra_expl_decay_iter=10,
        full_cov=True,
        symm_sampling=False,
        num_sampler_envs=8,
    )
    algo = CEM(ex_dir, env, policy, **algo_hparam)

    # Save the hyper-parameters
    save_list_of_dicts_to_yaml([
        dict(env=env_hparams, seed=ex_dir.seed),
        dict(policy=policy_hparam),
        dict(algo=algo_hparam, algo_name=algo.name)],
        ex_dir
    )

    # Jeeeha
    algo.train(seed=ex_dir.seed)