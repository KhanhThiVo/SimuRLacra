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

import pytest
import torch.nn as nn
from copy import deepcopy
from sbi import utils
from sbi.inference import SNPE

from pyrado.algorithms.episodic.cem import CEM
from pyrado.algorithms.episodic.power import PoWER
from pyrado.algorithms.episodic.reps import REPS
from pyrado.algorithms.episodic.sysid_via_episodic_rl import DomainDistrParamPolicy, SysIdViaEpisodicRL
from pyrado.algorithms.meta.npdr import NPDR
from pyrado.algorithms.meta.arpl import ARPL
from pyrado.algorithms.meta.bayrn import BayRn
from pyrado.algorithms.meta.epopt import EPOpt
from pyrado.algorithms.meta.simopt import SimOpt
from pyrado.algorithms.meta.spota import SPOTA
from pyrado.algorithms.meta.udr import UDR
from pyrado.algorithms.step_based.gae import GAE
from pyrado.algorithms.step_based.ppo import PPO
from pyrado.domain_randomization.default_randomizers import (
    create_default_randomizer,
    create_zero_var_randomizer,
    create_default_domain_param_map_qq,
    create_default_randomizer_qbb,
)
from pyrado.domain_randomization.domain_parameter import NormalDomainParam, UniformDomainParam
from pyrado.domain_randomization.domain_randomizer import DomainRandomizer
from pyrado.domain_randomization.utils import wrap_like_other_env
from pyrado.environment_wrappers.action_delay import ActDelayWrapper
from pyrado.environment_wrappers.action_normalization import ActNormWrapper
from pyrado.environment_wrappers.domain_randomization import (
    DomainRandWrapperBuffer,
    DomainRandWrapperLive,
    MetaDomainRandWrapper,
)
from pyrado.environment_wrappers.observation_noise import GaussianObsNoiseWrapper
from pyrado.environment_wrappers.state_augmentation import StateAugmentationWrapper
from pyrado.environment_wrappers.utils import inner_env
from pyrado.environments.sim_base import SimEnv
from pyrado.logger import set_log_prefix_dir
from pyrado.policies.features import *
from pyrado.policies.feed_forward.fnn import FNN, FNNPolicy
from pyrado.policies.feed_forward.linear import LinearPolicy
from pyrado.policies.special.environment_specific import QQubeSwingUpAndBalanceCtrl
from pyrado.sampling.rollout import rollout
from pyrado.sampling.sequences import *
from pyrado.spaces import BoxSpace, ValueFunctionSpace
from pyrado.utils.data_types import EnvSpec


@pytest.fixture
def ex_dir(tmpdir):
    # Fixture providing an experiment directory
    set_log_prefix_dir(tmpdir)
    return tmpdir


@pytest.mark.longtime
@pytest.mark.parametrize("env", ["default_qbb"], ids=["qbb"], indirect=True)
@pytest.mark.parametrize(
    "spota_hparam",
    [
        dict(
            max_iter=2,
            alpha=0.05,
            beta=0.01,
            nG=2,
            nJ=10,
            ntau=5,
            nc_init=1,
            nr_init=1,
            sequence_cand=sequence_add_init,
            sequence_refs=sequence_const,
            warmstart_cand=False,
            warmstart_refs=False,
            num_bs_reps=1000,
            studentized_ci=False,
        ),
    ],
    ids=["casual_hparam"],
)
def test_spota_ppo(ex_dir, env: SimEnv, spota_hparam):
    # Environment and domain randomization
    randomizer = create_default_randomizer(env)
    env = DomainRandWrapperBuffer(env, randomizer)

    # Policy and subroutines
    policy = FNNPolicy(env.spec, [16, 16], hidden_nonlin=to.tanh)
    vfcn = FNN(input_size=env.obs_space.flat_dim, output_size=1, hidden_sizes=[16, 16], hidden_nonlin=to.tanh)
    critic_hparam = dict(gamma=0.998, lamda=0.95, num_epoch=3, batch_size=64, lr=1e-3)
    critic_cand = GAE(vfcn, **critic_hparam)
    critic_refs = GAE(deepcopy(vfcn), **critic_hparam)

    subrtn_hparam_cand = dict(
        # min_rollouts=0,  # will be overwritten by SPOTA
        min_steps=0,  # will be overwritten by SPOTA
        max_iter=2,
        num_epoch=3,
        eps_clip=0.1,
        batch_size=64,
        num_workers=1,
        std_init=0.5,
        lr=1e-2,
    )
    subrtn_hparam_cand = subrtn_hparam_cand

    sr_cand = PPO(ex_dir, env, policy, critic_cand, **subrtn_hparam_cand)
    sr_refs = PPO(ex_dir, env, deepcopy(policy), critic_refs, **subrtn_hparam_cand)

    # Create algorithm and train
    algo = SPOTA(ex_dir, env, sr_cand, sr_refs, **spota_hparam)
    algo.train()


@pytest.mark.longtime
@pytest.mark.parametrize("env", ["default_qqsu"], ids=["qq"], indirect=True)
@pytest.mark.parametrize(
    "bayrn_hparam",
    [
        dict(
            max_iter=2,
            acq_fc="UCB",
            acq_param=dict(beta=0.25),
            acq_restarts=100,
            acq_samples=100,
            num_init_cand=3,
            warmstart=True,
            num_eval_rollouts_sim=10,
            num_eval_rollouts_real=2,  # sim-2-sim
        ),
    ],
    ids=["casual_hparam"],
)
def test_bayrn_power(ex_dir, env: SimEnv, bayrn_hparam):
    # Environments and domain randomization
    env_real = deepcopy(env)
    env_sim = DomainRandWrapperLive(env, create_zero_var_randomizer(env))
    dp_map = create_default_domain_param_map_qq()
    env_sim = MetaDomainRandWrapper(env_sim, dp_map)
    env_real.domain_param = dict(Mp=0.024 * 1.1, Mr=0.095 * 1.1)
    env_real = wrap_like_other_env(env_real, env_sim)

    # Policy and subroutine
    policy_hparam = dict(energy_gain=0.587, ref_energy=0.827, acc_max=10.0)
    policy = QQubeSwingUpAndBalanceCtrl(env_sim.spec, **policy_hparam)
    subrtn_hparam = dict(
        max_iter=1,
        pop_size=20,
        num_init_states_per_domain=1,
        num_is_samples=20,
        expl_std_init=1.0,
        num_workers=1,
    )
    subrtn = PoWER(ex_dir, env_sim, policy, **subrtn_hparam)

    # Set the boundaries for the GP
    dp_nom = inner_env(env_sim).get_nominal_domain_param()
    ddp_space = BoxSpace(
        bound_lo=np.array([0.8 * dp_nom["Mp"], 1e-8, 0.8 * dp_nom["Mr"], 1e-8]),
        bound_up=np.array([1.2 * dp_nom["Mp"], 1e-7, 1.2 * dp_nom["Mr"], 1e-7]),
    )

    # Create algorithm and train
    algo = BayRn(ex_dir, env_sim, env_real, subrtn, ddp_space, **bayrn_hparam)
    algo.train()
    assert algo.curr_iter == algo.max_iter


@pytest.mark.parametrize("env", ["default_omo"], ids=["omo"], indirect=True)
def test_arpl(ex_dir, env: SimEnv):
    env = ActNormWrapper(env)
    env = StateAugmentationWrapper(env, domain_param=None)

    policy = FNNPolicy(env.spec, hidden_sizes=[16, 16], hidden_nonlin=to.tanh)

    vfcn_hparam = dict(hidden_sizes=[32, 32], hidden_nonlin=to.tanh)
    vfcn = FNNPolicy(spec=EnvSpec(env.obs_space, ValueFunctionSpace), **vfcn_hparam)
    critic_hparam = dict(
        gamma=0.9844534412010116,
        lamda=0.9710614403461155,
        num_epoch=10,
        batch_size=150,
        standardize_adv=False,
        lr=0.00016985313083236645,
    )
    critic = GAE(vfcn, **critic_hparam)

    algo_hparam = dict(
        max_iter=2,
        min_steps=23 * env.max_steps,
        min_rollouts=None,
        num_epoch=5,
        eps_clip=0.085,
        batch_size=150,
        std_init=0.995,
        lr=2e-4,
        num_workers=1,
    )
    arpl_hparam = dict(
        max_iter=2,
        steps_num=23 * env.max_steps,
        halfspan=0.05,
        dyn_eps=0.07,
        dyn_phi=0.25,
        obs_phi=0.1,
        obs_eps=0.05,
        proc_phi=0.1,
        proc_eps=0.03,
        torch_observation=True,
    )
    ppo = PPO(ex_dir, env, policy, critic, **algo_hparam)
    algo = ARPL(ex_dir, env, ppo, policy, ppo.expl_strat, **arpl_hparam)

    algo.train(snapshot_mode="best")


@pytest.mark.longtime
@pytest.mark.parametrize("env, num_eval_rollouts", [("default_bob", 5)], ids=["bob"], indirect=["env"])
def test_sysidasrl_reps(ex_dir, env: SimEnv, num_eval_rollouts):
    def eval_ddp_policy(rollouts_real):
        init_states_real = np.array([ro.states[0, :] for ro in rollouts_real])
        rollouts_sim = []
        for i, _ in enumerate(range(num_eval_rollouts)):
            rollouts_sim.append(
                rollout(env_sim, behavior_policy, eval=True, reset_kwargs=dict(init_state=init_states_real[i, :]))
            )

        # Clip the rollouts rollouts yielding two lists of pairwise equally long rollouts
        ros_real_tr, ros_sim_tr = algo.truncate_rollouts(rollouts_real, rollouts_sim, replicate=False)
        assert len(ros_real_tr) == len(ros_sim_tr)
        assert all([np.allclose(r.states[0, :], s.states[0, :]) for r, s in zip(ros_real_tr, ros_sim_tr)])

        # Return the average the loss
        losses = [algo.loss_fcn(ro_r, ro_s) for ro_r, ro_s in zip(ros_real_tr, ros_sim_tr)]
        return float(np.mean(np.asarray(losses)))

    # Environments
    env_real = deepcopy(env)
    env_real.domain_param = dict(ang_offset=-2 * np.pi / 180)

    env_sim = deepcopy(env)
    randomizer = DomainRandomizer(
        UniformDomainParam(name="ang_offset", mean=0, halfspan=1e-6),
    )
    env_sim = DomainRandWrapperLive(env_sim, randomizer)
    dp_map = {0: ("ang_offset", "mean"), 1: ("ang_offset", "halfspan")}
    env_sim = MetaDomainRandWrapper(env_sim, dp_map)

    assert env_real is not env_sim

    # Policies (the behavioral policy needs to be deterministic)
    behavior_policy = LinearPolicy(env_sim.spec, feats=FeatureStack([identity_feat]))
    prior = DomainRandomizer(
        UniformDomainParam(name="ang_offset", mean=1 * np.pi / 180, halfspan=1 * np.pi / 180),
    )
    ddp_policy = DomainDistrParamPolicy(mapping=dp_map, trafo_mask=[False, True], prior=prior)

    # Subroutine
    subrtn_hparam = dict(
        max_iter=2,
        eps=1.0,
        pop_size=200,
        num_init_states_per_domain=1,
        expl_std_init=5e-2,
        expl_std_min=1e-4,
        num_workers=1,
    )
    subrtn = REPS(ex_dir, env_sim, ddp_policy, **subrtn_hparam)

    algo_hparam = dict(
        metric=None, obs_dim_weight=np.ones(env_sim.obs_space.shape), num_rollouts_per_distr=5, num_workers=1
    )

    algo = SysIdViaEpisodicRL(subrtn, behavior_policy, **algo_hparam)

    rollouts_real_tst = []
    for _ in range(num_eval_rollouts):
        rollouts_real_tst.append(rollout(env_real, behavior_policy, eval=True))
    loss_pre = eval_ddp_policy(rollouts_real_tst)

    # Mimic training
    while algo.curr_iter < algo.max_iter and not algo.stopping_criterion_met():
        algo.logger.add_value(algo.iteration_key, algo.curr_iter)

        # Creat fake real-world data
        rollouts_real = []
        for _ in range(num_eval_rollouts):
            rollouts_real.append(rollout(env_real, behavior_policy, eval=True))

        algo.step(snapshot_mode="latest", meta_info=dict(rollouts_real=rollouts_real))

        algo.logger.record_step()
        algo._curr_iter += 1

    loss_post = eval_ddp_policy(rollouts_real_tst)
    assert loss_post <= loss_pre  # don't have to be better every step


@pytest.mark.longtime
@pytest.mark.parametrize("env", ["default_qqsu"], ids=["qq"], indirect=True)
def test_simopt_cem_ppo(ex_dir, env: SimEnv):
    # Environments
    env_real = deepcopy(env)
    env_real = ActNormWrapper(env_real)
    env_sim = ActNormWrapper(env)
    randomizer = DomainRandomizer(
        NormalDomainParam(name="Mr", mean=0.0, std=1e6, clip_lo=1e-3),
        NormalDomainParam(name="Mp", mean=0.0, std=1e6, clip_lo=1e-3),
        NormalDomainParam(name="Lr", mean=0.0, std=1e6, clip_lo=1e-3),
        NormalDomainParam(name="Lp", mean=0.0, std=1e6, clip_lo=1e-3),
    )
    env_sim = DomainRandWrapperLive(env_sim, randomizer)
    dp_map = {
        0: ("Mr", "mean"),
        1: ("Mr", "std"),
        2: ("Mp", "mean"),
        3: ("Mp", "std"),
        4: ("Lr", "mean"),
        5: ("Lr", "std"),
        6: ("Lp", "mean"),
        7: ("Lp", "std"),
    }
    trafo_mask = [True] * 8
    env_sim = MetaDomainRandWrapper(env_sim, dp_map)

    # Subroutine for policy improvement
    behav_policy_hparam = dict(hidden_sizes=[64, 64], hidden_nonlin=to.tanh)
    behav_policy = FNNPolicy(spec=env_sim.spec, **behav_policy_hparam)
    vfcn_hparam = dict(hidden_sizes=[32, 32], hidden_nonlin=to.relu)
    vfcn = FNNPolicy(spec=EnvSpec(env_sim.obs_space, ValueFunctionSpace), **vfcn_hparam)
    critic_hparam = dict(
        gamma=0.99,
        lamda=0.98,
        num_epoch=5,
        batch_size=512,
        standardize_adv=True,
        lr=8e-4,
        max_grad_norm=5.0,
    )
    critic = GAE(vfcn, **critic_hparam)
    subrtn_policy_hparam = dict(
        max_iter=2,
        eps_clip=0.13,
        min_steps=10 * env_sim.max_steps,
        num_epoch=7,
        batch_size=512,
        std_init=0.75,
        lr=7e-04,
        max_grad_norm=1.0,
        num_workers=1,
    )
    subrtn_policy = PPO(ex_dir, env_sim, behav_policy, critic, **subrtn_policy_hparam)

    prior = DomainRandomizer(
        NormalDomainParam(name="Mr", mean=0.095, std=0.095 / 10),
        NormalDomainParam(name="Mp", mean=0.024, std=0.024 / 10),
        NormalDomainParam(name="Lr", mean=0.085, std=0.085 / 10),
        NormalDomainParam(name="Lp", mean=0.129, std=0.129 / 10),
    )
    ddp_policy_hparam = dict(mapping=dp_map, trafo_mask=trafo_mask, scale_params=True)
    ddp_policy = DomainDistrParamPolicy(prior=prior, **ddp_policy_hparam)
    subsubrtn_distr_hparam = dict(
        max_iter=2,
        pop_size=20,
        num_init_states_per_domain=1,
        num_is_samples=10,
        expl_std_init=1e-2,
        expl_std_min=1e-5,
        extra_expl_std_init=1e-2,
        extra_expl_decay_iter=5,
        num_workers=1,
    )
    subsubrtn_distr = CEM(ex_dir, env_sim, ddp_policy, **subsubrtn_distr_hparam)
    subrtn_distr_hparam = dict(
        metric=None,
        obs_dim_weight=[1, 1, 1, 1, 10, 10],
        num_rollouts_per_distr=10,
        num_workers=1,
    )
    subrtn_distr = SysIdViaEpisodicRL(subsubrtn_distr, behavior_policy=behav_policy, **subrtn_distr_hparam)

    # Algorithm
    algo_hparam = dict(
        max_iter=1,
        num_eval_rollouts=5,
        warmstart=True,
    )
    algo = SimOpt(ex_dir, env_sim, env_real, subrtn_policy, subrtn_distr, **algo_hparam)
    algo.train()

    assert algo.curr_iter == algo.max_iter


@pytest.mark.parametrize("env", ["default_qbb"], ids=["qbb"], indirect=True)
@pytest.mark.parametrize(
    "policy",
    [
        "linear_policy",
    ],
    ids=["lin"],
    indirect=True,
)
@pytest.mark.parametrize(
    "algo, algo_hparam",
    [(UDR, {}), (EPOpt, dict(skip_iter=100, epsilon=0.2, gamma=0.9995))],
    ids=["udr", "EPOpt"],
)
def test_basic_meta(ex_dir, policy, env: SimEnv, algo, algo_hparam):
    # Policy and subroutine
    env = GaussianObsNoiseWrapper(
        env,
        noise_std=[
            1 / 180 * np.pi,
            1 / 180 * np.pi,
            0.0025,
            0.0025,
            2 / 180 * np.pi,
            2 / 180 * np.pi,
            0.05,
            0.05,
        ],
    )
    env = ActNormWrapper(env)
    env = ActDelayWrapper(env)
    randomizer = create_default_randomizer_qbb()
    randomizer.add_domain_params(UniformDomainParam(name="act_delay", mean=15, halfspan=15, clip_lo=0, roundint=True))
    env = DomainRandWrapperLive(env, randomizer)

    # Policy
    policy_hparam = dict(hidden_sizes=[64, 64], hidden_nonlin=to.tanh)  # FNN
    policy = FNNPolicy(spec=env.spec, **policy_hparam)

    # Critic
    vfcn_hparam = dict(hidden_sizes=[32, 32], hidden_nonlin=to.tanh)  # FNN
    vfcn = FNNPolicy(spec=EnvSpec(env.obs_space, ValueFunctionSpace), **vfcn_hparam)
    critic_hparam = dict(
        gamma=0.9995,
        lamda=0.98,
        num_epoch=2,
        batch_size=100,
        lr=5e-4,
        standardize_adv=False,
    )
    critic = GAE(vfcn, **critic_hparam)

    subrtn_hparam = dict(
        max_iter=2,
        min_steps=2 * env.max_steps,
        num_workers=1,
        num_epoch=2,
        eps_clip=0.1,
        batch_size=100,
        std_init=0.8,
        lr=2e-4,
    )
    subrtn = PPO(ex_dir, env, policy, critic, **subrtn_hparam)
    algo = algo(env, subrtn, **algo_hparam)

    algo.train()

    assert algo.curr_iter == algo.max_iter


@pytest.mark.longtime
@pytest.mark.parametrize("env", ["default_qqsu"], ids=["qq"], indirect=True)
@pytest.mark.parametrize("summary_statistic", ["bayessim", "dtw_distance"], ids=["summstat", "dtw"])
@pytest.mark.parametrize(
    "num_segments, len_segments",
    [(1, None), (10, None), (None, 100)],
    ids=["num1-lenNone", "num10-lenNone", "numNone-len100"],
)
@pytest.mark.parametrize("num_real_obs", [1], ids=["1realobs"])
@pytest.mark.parametrize("num_sbi_rounds", [2], ids=["2rounds"])
def test_npdr(ex_dir, env: SimEnv, summary_statistic: str, num_segments, len_segments, num_real_obs, num_sbi_rounds):
    # Create a fake ground truth target domain
    env_real = deepcopy(env)
    dp_nom = env.get_nominal_domain_param()
    env_real.domain_param = {k: v + 0.03 * np.random.randn(1).item() for k, v in dp_nom.items()}

    # Policy
    policy = QQubeSwingUpAndBalanceCtrl(env.spec)

    # Define a mapping: index - domain parameter
    dp_mapping = {i: k for i, (k, v) in enumerate(dp_nom.items())}

    # Prior and Posterior (normalizing flow)
    prior_hparam = dict(
        low=to.tensor([0.8 * dp_nom[v] for v in dp_mapping.values()]),
        high=to.tensor([1.2 * dp_nom[v] for v in dp_mapping.values()]),
    )
    prior = utils.BoxUniform(**prior_hparam)
    posterior_hparam = dict(model="maf", embedding_net=nn.Identity(), hidden_features=20, num_transforms=3)

    # Algorithm
    algo_hparam = dict(
        max_iter=1,
        summary_statistic=summary_statistic,
        num_real_rollouts=num_real_obs,
        num_sim_per_round=200,
        num_sbi_rounds=2,
        simulation_batch_size=1,
        normalize_posterior=False,
        num_eval_samples=10,
        num_segments=num_segments,
        len_segments=len_segments,
        subrtn_sbi_training_hparam=dict(
            num_atoms=10,  # default: 10
            training_batch_size=50,  # default: 50
            learning_rate=5e-4,  # default: 5e-4
            validation_fraction=0.1,  # default: 0.1
            stop_after_epochs=20,  # default: 20
            discard_prior_samples=False,  # default: False
            use_combined_loss=True,  # default: False
            retrain_from_scratch_each_round=False,  # default: False
            show_train_summary=False,  # default: False
            max_num_epochs=20,  # default: None
        ),
        subrtn_sbi_sampling_hparam=dict(sample_with_mcmc=False),
        num_workers=1,
    )
    algo = NPDR(
        ex_dir,
        env,
        env_real,
        policy,
        dp_mapping,
        prior,
        posterior_hparam,
        SNPE,
        **algo_hparam,
    )

    algo.train()
