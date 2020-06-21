from pyquaternion import Quaternion
from robosuite.wrappers.ik_wrapper import IKWrapper
from robosuite.environments.baxter import BaxterEnv
from robosuite.environments.sawyer import SawyerEnv
from robosuite.environments.panda import PandaEnv
import robosuite
import os
import numpy as np
from hem.robosuite import get_env
from hem.datasets import Trajectory
import pybullet as p
from pyquaternion import Quaternion
import random
import robosuite.utils.transform_utils as T


def _clip_delta(delta, max_step=0.015):
    norm_delta = np.linalg.norm(delta)

    if norm_delta < max_step:
        return delta
    return delta / norm_delta * max_step


class PickPlaceController:
    def __init__(self, env):
        assert env.single_object_mode == 2, "only supports single object environments at this point!"
        self._env = env
        self.reset()
        
    def _calculate_quat(self, angle):
        if isinstance(self._env, SawyerEnv):
            new_rot = np.array([[np.cos(angle), -np.sin(angle), 0],[np.sin(angle), np.cos(angle), 0],[0, 0, 1]])
            return Quaternion(matrix=self._base_rot.dot(new_rot))
        return self._base_quat
    
    def reset(self):
        self._object_name = self._env.item_names_org[self._env.object_id] + '0'
        self._target_loc = self._env.target_bin_placements[self._env.object_id] + [0, 0, 0.3]
        # TODO this line violates abstraction barriers but so does the reference implementation in robosuite
        self._jpos_getter = lambda : np.array(self._env._joint_positions)

        self._rise_t = 23
        if isinstance(self._env, SawyerEnv):
            self._obs_name = 'eef_pos'
            self._default_speed = 0.15
            self._final_thresh = 1e-2
            self._clearance = 0.03
        elif isinstance(self._env, PandaEnv):
            self._obs_name = 'eef_pos'
            self._default_speed = 0.15
            self._final_thresh = 6e-2
            self._clearance = 0.03
        else:
            raise NotImplementedError

        self._t = 0
        self._intermediate_reached = False
        self._base_rot = np.array([[-1., 0., 0.], [0., 1., 0.], [0., 0., -1.]])
        self._base_quat = Quaternion(matrix=self._base_rot)
        self._hover_delta = 0.2
        if 'Milk' in self._object_name:
            self._clearance = -0.03
    
    def _get_target_pose(self, delta_pos, quat, max_step=None):
        if max_step is None:
            max_step = self._default_speed

        delta_pos = _clip_delta(delta_pos, max_step)
        quat = np.array([quat.x, quat.y, quat.z, quat.w])
        quat = T.quat_multiply(T.quat_inverse(self._env._right_hand_quat), quat)
        return np.concatenate((delta_pos, quat))

    def act(self, obs):
        if self._t == 0:
            y = -(obs['{}_pos'.format(self._object_name)][1] - obs[self._obs_name][1])
            x = obs['{}_pos'.format(self._object_name)][0] - obs[self._obs_name][0]
            angle = np.arctan2(y, x) - np.pi/3 if 'Cereal' in self._object_name else np.arctan2(y, x)
            self._target_quat = self._calculate_quat(angle)

        if self._t < 15:
            quat_t = Quaternion.slerp(self._base_quat, self._target_quat, min(1, float(self._t) / 5))
            eef_pose = self._get_target_pose(obs['{}_pos'.format(self._object_name)] - obs[self._obs_name] + [0, 0, self._hover_delta], quat_t)
            action = np.concatenate((eef_pose, [-1]))
        elif self._t < 25: 
            if self._t  < self._rise_t:
                eef_pose = self._get_target_pose(obs['{}_pos'.format(self._object_name)] - obs[self._obs_name] - [0, 0, self._clearance], self._target_quat)  
                action = np.concatenate((eef_pose, [-1]))
            else:
                eef_pose = self._get_target_pose(obs['{}_pos'.format(self._object_name)] - obs[self._obs_name] + [0, 0, self._hover_delta], self._target_quat)
                action = np.concatenate((eef_pose, [1]))

        elif np.linalg.norm(self._target_loc - obs[self._obs_name]) > self._final_thresh: 
            target = self._target_loc
            # if self._intermediate_reached:
            #     target = self._target_loc
            # elif np.linalg.norm(self._intermediate_point - obs[self._obs_name]) < 1e-2:
            #     target = self._target_loc
            #     self._intermediate_reached = True
            # else:
            #     target = self._intermediate_point
            
            eef_pose = self._get_target_pose(target - obs[self._obs_name], self._target_quat)
            action = np.concatenate((eef_pose, [1]))
        else:
            eef_pose = self._get_target_pose(np.zeros(3), self._target_quat)
            action = np.concatenate((eef_pose, [-1]))
        
        self._t += 1
        return action

    def disconnect(self):
        p.disconnect()


def post_proc_obs(obs):
    if 'image' in obs:
        obs['image'] = obs['image'][80:]
    if 'depth' in obs:
        obs['depth'] = obs['depth'][80:]

    quat = Quaternion(obs['eef_quat'][[3, 0, 1, 2]])
    aa = np.concatenate(([quat.angle / np.pi], quat.axis)).astype(np.float32)
    if aa[0] < 0:
        aa[0] += 2
    obs['ee_aa'] = np.concatenate((obs['eef_pos'], aa)).astype(np.float32)
    return obs


def get_expert_trajectory(env_type, camera_obs=True, renderer=False, rng=None):
    success, use_object = False, ''
    if rng is not None:
        use_object = rng.choice(['milk', 'bread', 'cereal', 'can'])
        rg, db, = False, rng.randint(0,3)
    else:
        rg, db = True, None

    while not success:
        np.random.seed()
        env = get_env(env_type)(force_object=use_object, randomize_goal=rg, default_bin=db, has_renderer=renderer, reward_shaping=False, use_camera_obs=camera_obs, camera_height=320, camera_width=320)
        controller = PickPlaceController(env)
        env = IKWrapper(env, action_repeat=10)
        obs = env.reset()
        mj_state = env.sim.get_state().flatten()
        sim_xml = env.model.get_xml()
        traj = Trajectory(sim_xml)

        env.reset_from_xml_string(sim_xml)
        env.sim.reset()
        env.sim.set_state_from_flattened(mj_state)
        env.sim.forward()
        use_object = env.item_names_org[env.object_id].lower()

        traj.append(post_proc_obs(obs), raw_state=mj_state)
        for _ in range(int(env.horizon // 10)):
            action = controller.act(obs)
            obs, reward, done, info = env.step(action)
            if renderer:
                env.render()

            mj_state = env.sim.get_state().flatten()
            traj.append(post_proc_obs(obs), reward, done, info, action, mj_state)
            
            if reward:
                success = True
                break
    
    if renderer:
        env.close()
    
    controller.disconnect()
    return traj
