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

import functools
import numpy as np
import os
import pandas as pd
import torch as to
from matplotlib import pyplot as plt
from typing import Sequence, List, Optional

import pyrado
from pyrado.environment_wrappers.action_normalization import ActNormWrapper
from pyrado.environment_wrappers.utils import typed_env, inner_env
from pyrado.environments.base import Env
from pyrado.plotting.curve import draw_curve
from pyrado.plotting.utils import num_rows_cols_from_length
from pyrado.policies.base import Policy
from pyrado.policies.feed_forward.linear import LinearPolicy
from pyrado.sampling.step_sequence import StepSequence
from pyrado.utils.data_types import fill_list_of_arrays
from pyrado.utils.input_output import print_cbt


def _get_obs_label(rollout: StepSequence, idx: int):
    try:
        label = f"{rollout.rollout_info['env_spec'].obs_space.labels[idx]}"
        if label == "None":
            label = f"o_{{{idx}}}"
    except (AttributeError, KeyError):
        label = f"o_{{{idx}}}"
    return label


def _get_act_label(rollout: StepSequence, idx: int):
    try:
        label = f"{rollout.rollout_info['env_spec'].act_space.labels[idx]}"
        if label == "None":
            label = f"a_{{{idx}}}"
    except (AttributeError, KeyError):
        label = f"a_{{{idx}}}"
    return label


def plot_observations_actions_rewards(ro: StepSequence):
    """
    Plot all observation, action, and reward trajectories of the given rollout.

    :param ro: input rollout
    """
    if hasattr(ro, "observations") and hasattr(ro, "actions") and hasattr(ro, "env_infos"):
        if not isinstance(ro.observations, np.ndarray):
            raise pyrado.TypeErr(given=ro.observations, expected_type=np.ndarray)
        if not isinstance(ro.actions, np.ndarray):
            raise pyrado.TypeErr(given=ro.actions, expected_type=np.ndarray)

        dim_obs = ro.observations.shape[1]
        dim_act = ro.actions.shape[1]

        # Use recorded time stamps if possible
        t = getattr(ro, "time", np.arange(0, ro.length + 1))

        fig, axs = plt.subplots(*num_rows_cols_from_length(dim_obs + dim_act + 1), figsize=(14, 10), tight_layout=True)
        fig.canvas.set_window_title("Observations, Actions, and Reward over Time")
        colors = plt.get_cmap("tab20")(np.linspace(0, 1, dim_obs if dim_obs > dim_act else dim_act))

        # Observations (without the last time step)
        for i in range(dim_obs):
            axs[i].plot(t, ro.observations[:, i], c=colors[i])
            axs[i].set_ylabel(_get_obs_label(ro, i))

        # Actions
        for i in range(dim_act):
            axs[i + dim_obs].plot(t[:-1], ro.actions[:, i], c=colors[i])
            axs[i + dim_obs].set_ylabel(_get_act_label(ro, i))
        # action_labels = env.unwrapped.action_space.labels; label=action_labels[0]

        # Rewards
        axs[-1].plot(t[:-1], ro.rewards, c="k")
        axs[-1].set_ylabel("reward")
        axs[-1].set_xlabel("time")
        plt.subplots_adjust(hspace=0.5)


def plot_observations(ro: StepSequence, idcs_sel: Sequence[int] = None):
    """
    Plot all observation trajectories of the given rollout.

    :param ro: input rollout
    :param idcs_sel: indices of the selected selected observations, if `None` plot all
    """
    if hasattr(ro, "observations"):
        if not isinstance(ro.observations, np.ndarray):
            raise pyrado.TypeErr(given=ro.observations, expected_type=np.ndarray)

        # Select dimensions to plot
        dim_obs = range(ro.observations.shape[1]) if idcs_sel is None else idcs_sel

        # Use recorded time stamps if possible
        t = getattr(ro, "time", np.arange(0, ro.length + 1))

        if len(dim_obs) <= 6:
            divisor = 2
        elif len(dim_obs) <= 12:
            divisor = 4
        else:
            divisor = 8
        num_cols = int(np.ceil(len(dim_obs) / divisor))
        num_rows = int(np.ceil(len(dim_obs) / num_cols))

        fig, axs = plt.subplots(num_rows, num_cols, figsize=(num_cols * 5, num_rows * 3), tight_layout=True)
        axs = np.atleast_2d(axs)
        axs = axs.T if axs.shape[0] == 1 else axs  # compensate for np.atleast_2d in case axs was 1-dim
        fig.canvas.set_window_title("Observations over Time")
        colors = plt.get_cmap("tab20")(np.linspace(0, 1, len(dim_obs)))

        if len(dim_obs) == 1:
            axs[0, 0].plot(t, ro.observations[:, dim_obs[0]], label=_get_obs_label(ro, dim_obs[0]))
            axs[0, 0].legend()
            axs.plot(t, ro.observations[:, dim_obs[0]], label=_get_obs_label(ro, dim_obs[0]))
            axs.legend()
        else:
            for i in range(num_rows):
                for j in range(num_cols):
                    if j + i * num_cols < len(dim_obs):
                        # Omit the last observation for simplicity
                        axs[i, j].plot(t, ro.observations[:, j + i * num_cols], c=colors[j + i * num_cols])
                        axs[i, j].set_ylabel(_get_obs_label(ro, j + i * num_cols))
                    else:
                        # We might create more subplots than there are observations
                        axs[i, j].remove()


def plot_features(ro: StepSequence, policy: Policy):
    """
    Plot all features given the policy and the observation trajectories.

    :param policy: linear policy used during the rollout
    :param ro: input rollout
    """
    if not isinstance(policy, LinearPolicy):
        print_cbt("Plotting of the feature values is only supports linear policies!", "r")
        return

    if hasattr(ro, "observations"):
        # Use recorded time stamps if possible
        t = getattr(ro, "time", np.arange(0, ro.length + 1))[:-1]

        # Recover the features from the observations
        feat_vals = policy.eval_feats(to.from_numpy(ro.observations))
        dim_feat = range(feat_vals.shape[1])
        if len(dim_feat) <= 6:
            divisor = 2
        elif len(dim_feat) <= 12:
            divisor = 4
        else:
            divisor = 8
        num_cols = int(np.ceil(len(dim_feat) / divisor))
        num_rows = int(np.ceil(len(dim_feat) / num_cols))

        fig, axs = plt.subplots(num_rows, num_cols, figsize=(num_cols * 5, num_rows * 3), tight_layout=True)
        axs = np.atleast_2d(axs)
        axs = axs.T if axs.shape[0] == 1 else axs  # compensate for np.atleast_2d in case axs was 1-dim
        fig.canvas.set_window_title("Feature Values over Time")
        plt.subplots_adjust(hspace=0.5)
        colors = plt.get_cmap("tab20")(np.linspace(0, 1, len(dim_feat)))

        if len(dim_feat) == 1:
            axs.plot(t, feat_vals[:-1, dim_feat[0]], label=_get_obs_label(ro, dim_feat[0]))
            axs.legend()
        else:
            for i in range(num_rows):
                for j in range(num_cols):
                    if j + i * num_cols < len(dim_feat):
                        # Omit the last observation for simplicity
                        axs[i, j].plot(t, feat_vals[:-1, j + i * num_cols], c=colors[j + i * num_cols])
                        axs[i, j].set_ylabel(rf"$\phi_{{{j + i*num_cols}}}$")
                    else:
                        # We might create more subplots than there are observations
                        axs[i, j].remove()


def plot_actions(ro: StepSequence, env: Env):
    """
    Plot all action trajectories of the given rollout.

    :param ro: input rollout
    :param env: environment (used for getting the clipped action values)
    """
    if hasattr(ro, "actions"):
        if not isinstance(ro.actions, np.ndarray):
            raise pyrado.TypeErr(given=ro.actions, expected_type=np.ndarray)

        dim_act = ro.actions.shape[1]
        # Use recorded time stamps if possible
        t = getattr(ro, "time", np.arange(0, ro.length + 1))[:-1]

        fig, axs = plt.subplots(*num_rows_cols_from_length(dim_act), figsize=(10, 8), tight_layout=True)
        fig.canvas.set_window_title("Actions over Time")
        colors = plt.get_cmap("tab20")(np.linspace(0, 1, dim_act))

        act_norm_wrapper = typed_env(env, ActNormWrapper)
        if act_norm_wrapper is not None:
            lb, ub = inner_env(env).act_space.bounds
            act_denorm = lb + (ro.actions + 1.0) * (ub - lb) / 2
            act_clipped = np.array([inner_env(env).limit_act(a) for a in act_denorm])
        else:
            act_denorm = ro.actions
            act_clipped = np.array([env.limit_act(a) for a in ro.actions])

        if dim_act == 1:
            axs.plot(t, act_denorm, label="to env")
            axs.plot(t, act_clipped, label="clipped", c="k", ls="--")
            axs.legend(ncol=2)
            axs.set_ylabel(_get_act_label(ro, 0))
        else:
            for i in range(dim_act):
                axs[i].plot(t, act_denorm[:, i], label="to env", c=colors[i])
                axs[i].plot(t, act_clipped[:, i], label="clipped", c="k", ls="--")
                axs[i].legend(ncol=2)
                axs[i].set_ylabel(_get_act_label(ro, i))

        # Put legends to the right of the plot
        if dim_act < 8:  # otherwise it gets too cluttered
            for a in fig.get_axes():
                a.legend(ncol=2)

        plt.subplots_adjust(hspace=0.2)


def plot_rewards(ro: StepSequence):
    """
    Plot the reward trajectories of the given rollout.

    :param ro: input rollout
    """
    if hasattr(ro, "rewards"):
        # Use recorded time stamps if possible
        t = getattr(ro, "time", np.arange(0, ro.length + 1))[:-1]

        fig, ax = plt.subplots(1, tight_layout=True)
        fig.canvas.set_window_title("Reward over Time")
        ax.plot(t, ro.rewards, c="k")
        ax.set_ylabel("reward")
        ax.set_xlabel("time")


def plot_potentials(ro: StepSequence, layout: str = "joint"):
    """
    Plot the trajectories specific to a potential-based policy.

    :param ro: input rollout
    :param layout: group jointly (default), or create a separate sub-figure for each plot
    """
    if (
        hasattr(ro, "actions")
        and hasattr(ro, "potentials")
        and hasattr(ro, "stimuli_external")
        and hasattr(ro, "stimuli_internal")
    ):
        # Use recorded time stamps if possible
        t = getattr(ro, "time", np.arange(0, ro.length + 1))[:-1]

        dim_pot = ro.potentials.shape[1]  # number of neurons with potential
        num_act = ro.actions.shape[1]
        colors_pot = plt.get_cmap("tab20")(np.linspace(0, 1, dim_pot))
        colors_act = plt.get_cmap("tab20")(np.linspace(0, 1, num_act))

        if layout == "separate":
            fig = plt.figure(figsize=(16, 10))
            gs = fig.add_gridspec(nrows=dim_pot, ncols=4)
            for i in range(dim_pot):
                ax0 = fig.add_subplot(gs[i, 0])
                ax0.plot(t, ro.stimuli_external[:, i], label=rf"$s_{{ext,{i}}}$", c=colors_pot[i])
                ax1 = fig.add_subplot(gs[i, 1])
                ax1.plot(t, ro.stimuli_internal[:, i], label=rf"$s_{{int,{i}}}$", c=colors_pot[i])
                ax2 = fig.add_subplot(gs[i, 2], sharex=ax0)
                ax2.plot(t, ro.potentials[:, i], label=rf"$p_{{{i}}}$", c=colors_pot[i])
                if i < num_act:  # could have more potentials than actions
                    ax3 = fig.add_subplot(gs[i, 3], sharex=ax0)
                    ax3.plot(t, ro.actions[:, i], label=rf"$a_{{{i}}}$", c=colors_act[i])

                if i == 0:
                    ax0.set_title(f"{ro.stimuli_external.shape[1]} External stimuli over time")
                    ax1.set_title(f"{ro.stimuli_internal.shape[1]} Internal stimuli over time")
                    ax2.set_title(f"{ro.potentials.shape[1]} Potentials over time")
                    ax3.set_title(f"{ro.actions.shape[1]} Actions over time")

            plt.subplots_adjust(hspace=0.5)
            plt.subplots_adjust(wspace=0.8)

        elif layout == "joint":
            fig, axs = plt.subplots(nrows=4, ncols=1, figsize=(14, 10), sharex="all")

            for i in range(dim_pot):
                axs[0].plot(t, ro.stimuli_external[:, i], label=rf"$s_{{ext,{i}}}$", c=colors_pot[i])
                axs[1].plot(t, ro.stimuli_internal[:, i], label=rf"$s_{{int,{i}}}$", c=colors_pot[i])
                axs[2].plot(t, ro.potentials[:, i], label=rf"$p_{{{i}}}$", c=colors_pot[i])

            for i in range(num_act):
                axs[3].plot(t, ro.actions[:, i], label=rf"$a_{{{i}}}$", c=colors_act[i])

            axs[0].set_title(f"{ro.stimuli_external.shape[1]} External stimuli over time")
            axs[1].set_title(f"{ro.stimuli_internal.shape[1]} Internal stimuli over time")
            axs[2].set_title(f"{ro.potentials.shape[1]} Potentials over time")
            axs[3].set_title(f"{ro.actions.shape[1]} Actions over time")

            plt.subplots_adjust(wspace=0.8)

        else:
            raise pyrado.ValueErr(given=layout, eq_constraint="joint or separate")

        # Put legends to the right of the plot
        if dim_pot < 8:  # otherwise it gets too cluttered
            for a in fig.get_axes():
                a.legend(loc="center left", bbox_to_anchor=(1, 0.5))


def plot_statistic_across_rollouts(
    rollouts: Sequence[StepSequence],
    stat_fcn: callable,
    stat_fcn_kwargs=None,
    obs_idcs: Sequence[int] = None,
    act_idcs: Sequence[int] = None,
):
    """
    Plot one statistic of interest (e.g. mean) across a list of rollouts.

    :param rollouts: list of rollouts, they can be of unequal length but are assumed to be from the same type of env
    :param stat_fcn: function to calculate the statistic of interest (e.g. np.mean)
    :param stat_fcn_kwargs: keyword arguments for the stat_fcn (e.g. {'axis': 0})
    :param obs_idcs: indices of the observations to process and plot, pass `None` to select all
    :param act_idcs: indices of the actions to process and plot, pass `None` to select all
    """
    if obs_idcs is None and act_idcs is None:
        raise pyrado.ValueErr(msg="Must select either an observation or an action, but both are None!")

    # Create figure with sub-figures
    num_subplts = 2 if (obs_idcs is not None and act_idcs is not None) else 1
    fix, axs = plt.subplots(num_subplts)

    if stat_fcn_kwargs is not None:
        stat_fcn = functools.partial(stat_fcn, **stat_fcn_kwargs)

    # Determine the longest rollout's length
    max_ro_len = max([ro.length for ro in rollouts])

    # Process observations
    if obs_idcs is not None:
        obs_sel = [ro.observations[:, obs_idcs] for ro in rollouts]
        obs_filled = fill_list_of_arrays(obs_sel, des_len=max_ro_len + 1)  # +1 since obs are of size ro.length+1
        obs_stat = stat_fcn(np.asarray(obs_filled))

        for i, obs_idx in enumerate(obs_idcs):
            axs[0].plot(obs_stat[:, i], label=_get_obs_label(rollouts[0], i), c=f"C{i%10}")
        axs[0].legend()

    # Process actions
    if act_idcs is not None:
        act_sel = [ro.actions[:, act_idcs] for ro in rollouts]
        act_filled = fill_list_of_arrays(act_sel, des_len=max_ro_len)
        act_stats = stat_fcn(np.asarray(act_filled))

        for i, act_idx in enumerate(act_idcs):
            axs[1].plot(act_stats[:, i], label=_get_act_label(rollouts[0], i), c=f"C{i%10}")
        axs[1].legend()


def plot_mean_std_across_rollouts(
    rollouts: Sequence[StepSequence],
    idcs_obs: Sequence[int] = None,
    idcs_act: Sequence[int] = None,
):
    """
    Plot the mean and standard deviation across a selection of rollouts.

    :param rollouts: list of rollouts, they can be of unequal length but are assumed to be from the same type of env
    :param idcs_obs: indices of the observations to process and plot, pass `None` to select all
    :param idcs_act: indices of the actions to process and plot, pass `None` to select all
    """
    dim_obs = rollouts[0].observations.shape[1]  # assuming same for all rollouts
    dim_act = rollouts[0].actions.shape[1]  # assuming same for all rollouts
    if idcs_obs is None:
        idcs_obs = slice(0, dim_obs)
    if idcs_act is None:
        idcs_act = slice(0, idcs_act)

    max_len = 0
    time = None
    data_obs = pd.DataFrame()
    data_act = pd.DataFrame()
    for ro in rollouts:
        ro.numpy()
        if len(ro) > max_len:
            # Extract time
            max_len = len(ro)
            time = getattr(ro, "time", None)

        # Extract observations
        df = pd.DataFrame(ro.observations[:, idcs_obs], columns=ro.rollout_info["env_spec"].obs_space.labels[idcs_obs])
        data_obs = pd.concat([data_obs, df], axis=1)

        # Extract actions
        df = pd.DataFrame(ro.actions[:, idcs_act], columns=ro.rollout_info["env_spec"].act_space.labels[idcs_act])
        data_act = pd.concat([data_act, df], axis=1)

    # Compute statistics
    means_obs = data_obs.groupby(by=data_obs.columns, axis=1).mean()
    stds_obs = data_obs.groupby(by=data_obs.columns, axis=1).std()
    means_act = data_act.groupby(by=data_act.columns, axis=1).mean()
    stds_act = data_act.groupby(by=data_act.columns, axis=1).std()

    # Plot observations
    num_rows, num_cols = num_rows_cols_from_length(dim_obs, transposed=True)
    fig_obs, axs_obs = plt.subplots(num_rows, num_cols, figsize=(18, 9), tight_layout=True)
    fig_obs.canvas.set_window_title("Mean And 2 Standard Deviations of the Observations over Time")
    colors = plt.get_cmap("tab20")(np.linspace(0, 1, dim_obs))

    for idx_o, c in enumerate(data_obs.columns.unique()):
        draw_curve(
            "mean_std",
            axs_obs[idx_o // num_cols, idx_o % num_cols] if isinstance(axs_obs, np.ndarray) else axs_obs,
            pd.DataFrame(dict(mean=means_obs[c], std=stds_obs[c])),
            x_grid=time,
            show_legend=False,
            x_label="time [s]" if time is not None else np.arange(len(data_obs)),
            y_label=str(c),
            plot_kwargs=dict(color=colors[idx_o]),
        )

    # Plot actions
    num_rows, num_cols = num_rows_cols_from_length(dim_act, transposed=True)
    fig_act, axs_act = plt.subplots(num_rows, num_cols, figsize=(18, 9), tight_layout=True)
    fig_obs.canvas.set_window_title("Mean And 2 Standard Deviations of the Actions over Time")
    colors = plt.get_cmap("tab20")(np.linspace(0, 1, dim_act))

    for idx_a, c in enumerate(data_act.columns.unique()):
        draw_curve(
            "mean_std",
            axs_act[idx_a // num_cols, idx_a % num_cols] if isinstance(axs_act, np.ndarray) else axs_act,
            pd.DataFrame(dict(mean=means_act[c], std=stds_act[c])),
            x_grid=time[:-1],
            show_legend=False,
            x_label="time [s]" if time is not None else np.arange(len(data_act)),
            y_label=str(c),
            plot_kwargs=dict(color=colors[idx_a]),
        )


def plot_rollouts_segment_wise(
    segments_ground_truth: List[List[StepSequence]],
    segments_multiple_envs: List[List[List[StepSequence]]],
    segments_nominal: List[List[StepSequence]],
    use_rec: bool,
    idx_iter: int,
    idx_round: Optional[int] = None,
    state_labels: Optional[List[str]] = None,
    save_dir: Optional[str] = None,
) -> List[plt.Figure]:
    """
    Plot the different rollouts in separate figures and the different state dimensions along the columns.

    :param segments_ground_truth: list of lists containing rollout segments from the ground truth environment
    :param segments_multiple_envs: list of lists of lists containing rollout segments from different environment
                                   instances, e.g. samples from a posterior coming from `NDPR`
    :param segments_nominal: list of lists containing rollout segments from the nominal environment
    :param use_rec: `True` if pre-recorded actions have been used to generate the rollouts
    :param idx_iter: selected iteration
    :param idx_round: selected round
    :param state_labels: y-axes labels to override the default value which is extracted from the state space's labels
    :param save_dir: if not `None` create a subfolder plots in `save_dir` and save the plots in there
    :return: list of handles to the created figures
    """
    # Extract the state dimension, and the number of most likely samples from the data
    dim_state = segments_ground_truth[0][0].get_data_values("states")[0, :].size
    num_samples = len(segments_multiple_envs[0][0])

    # Extract the state labels if not explicitly given
    if state_labels is None:
        env_spec = segments_ground_truth[0][0].rollout_info.get("env_spec", None)
        state_labels = env_spec.state_space.labels if env_spec is not None else np.empty(dim_state, dtype=object)
    else:
        if len(state_labels) != dim_state:
            raise pyrado.ShapeErr(given=state_labels, expected_match=(dim_state,))

    colors = plt.get_cmap("Reds")(np.linspace(0.5, 1.0, num_samples))
    fig_list = []

    for idx_r in range(len(segments_ground_truth)):
        fig, axs = plt.subplots(nrows=dim_state, figsize=(16, 9), tight_layout=True, sharex="col")

        for idx_state in range(dim_state):
            # Plot the real segments
            cnt_step = [0]
            for segment_real in segments_ground_truth[idx_r]:
                axs[idx_state].plot(
                    np.arange(cnt_step[-1], cnt_step[-1] + segment_real.length),
                    segment_real.get_data_values("states", truncate_last=True)[:, idx_state],
                    c="black",
                    label="real" if cnt_step[-1] == 0 else "",  # only print once
                )
                cnt_step.append(cnt_step[-1] + segment_real.length)

            # Plot the maximum likely simulated segments
            for idx_seg, sml in enumerate(segments_multiple_envs[idx_r]):
                for idx_dp, smdp in enumerate(sml):
                    axs[idx_state].plot(
                        np.arange(cnt_step[idx_seg], cnt_step[idx_seg] + smdp.length),
                        smdp.get_data_values("states", truncate_last=True)[:, idx_state],
                        c=colors[idx_dp],
                        ls="--",
                        label=f"sim ml {idx_dp}" if cnt_step[idx_seg] == 0 else "",  # only print once for each dp set
                    )

            # Plot the nominal simulation's segments
            for idx_seg, sn in enumerate(segments_nominal[idx_r]):
                axs[idx_state].plot(
                    np.arange(cnt_step[idx_seg], cnt_step[idx_seg] + sn.length),
                    sn.get_data_values("states", truncate_last=True)[:, idx_state],
                    c="steelblue",
                    ls="-.",
                    label="sim nom" if cnt_step[idx_seg] == 0 else "",  # only print once
                )

            axs[idx_state].set_ylabel(state_labels[idx_state])

        # Set window title and the legend, placing the latter above the plot expanding and expanding it fully
        use_rec = ", using rec actions" if use_rec else ""
        rnd = f"round {idx_round}, " if idx_round is not None else ""
        fig.canvas.set_window_title(
            f"Target Domain and Simulated Rollouts (iteration {idx_iter}, {rnd}rollout {idx_r}{use_rec})"
        )
        lg = axs[0].legend(
            ncol=2 + num_samples,
            bbox_to_anchor=(0.0, 1.02, 1.0, 0.102),
            loc="lower left",
            mode="expand",
            borderaxespad=0.0,
        )

        # Save if desired
        if save_dir is not None:
            for fmt in ["pdf", "pgf"]:
                os.makedirs(os.path.join(save_dir, "plots"), exist_ok=True)
                use_rec = "_use_rec" if use_rec else ""
                rnd = f"_round_{idx_round}" if idx_round is not None else ""
                fig.savefig(
                    os.path.join(save_dir, "plots", f"posterior_iter_{idx_iter}{rnd}_rollout_{idx_r}{use_rec}.{fmt}"),
                    bbox_extra_artists=(lg,),
                    dpi=500,
                )

        # Append current figure
        fig_list.append(fig)

    return fig_list
