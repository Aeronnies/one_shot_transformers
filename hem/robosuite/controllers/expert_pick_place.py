from pyquaternion import Quaternion
from robosuite.controllers.sawyer_ik_controller import SawyerIKController
from robosuite.controllers.baxter_ik_controller import BaxterIKController
from robosuite.environments.baxter import BaxterEnv
from robosuite.environments.sawyer import SawyerEnv
import robosuite
import os
import numpy as np


def _clip_delta(delta, max_step=0.015):
    norm_delta = np.linalg.norm(delta)

    if norm_delta < max_step:
        return np.zeros_like(delta)
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
        self._target_loc = self._env.target_bin_placements[self._env.object_id] + [0, 0, 0.25]
        # TODO this line violates abstraction barriers but so does the reference implementation in robosuite
        self._jpos_getter = lambda : np.array(self._env._joint_positions)
        bullet_path = os.path.join(robosuite.models.assets_root, "bullet_data")

        if isinstance(self._env, SawyerEnv):
            self._ik = SawyerIKController(bullet_path, self._jpos_getter)
            self._obs_name = 'eef_pos'
            self._default_speed = 0.015
            self._final_thresh = 1e-2
            self._clearance = 0.03
        elif isinstance(self._env, BaxterEnv):
            self._ik = BaxterIKController(bullet_path, self._jpos_getter)
            self._obs_name = 'right_eef_pos'
            self._default_speed = 0.004
            self._final_thresh = 6e-2
            self._clearance = 0.02
        else:
            raise NotImplementedError

        self._t = 0
        self._intermediate_reached = False
        self._base_rot = np.array([[-1., 0., 0.], [0., 1., 0.], [0., 0., -1.]])
        self._base_quat = Quaternion(matrix=self._base_rot)
        self._intermediate_point = np.array([0.44969246 + 0.2, 0.16029991, 1.05])
    
    def _get_velocities(self, delta_pos, quat, max_step=None):
        if max_step is None:
            max_step = self._default_speed
        
        if isinstance(self._env, BaxterEnv):
            right_delta = {'dpos': _clip_delta(delta_pos, max_step), 'rotation': quat.transformation_matrix[:3,:3]}
            left_delta = {'dpos': np.zeros(3), 'rotation': self._base_rot}
            velocities = self._ik.get_control(right_delta, left_delta)
            return velocities[:7]
        return self._ik.get_control(_clip_delta(delta_pos, max_step), quat.transformation_matrix[:3,:3])
    
    def act(self, obs):
        if self._t == 0:
            y = -(obs['{}_pos'.format(self._object_name)][1] - obs[self._obs_name][1])
            x = obs['{}_pos'.format(self._object_name)][0] - obs[self._obs_name][0]
            self._target_quat = self._calculate_quat(np.arctan2(y, x))
        
        if self._t < 150:
            quat_t = Quaternion.slerp(self._base_quat, self._target_quat, min(1, float(self._t) / 50))
            velocities = self._get_velocities(obs['{}_pos'.format(self._object_name)] - obs[self._obs_name] + [0, 0, 0.05], quat_t)
            action = np.concatenate((velocities, [-1]))
        elif self._t < 200:
            velocities = self._get_velocities(obs['{}_pos'.format(self._object_name)] - obs[self._obs_name] - [0, 0, self._clearance], self._target_quat)   
            if self._t  < 175:
                action = np.concatenate((velocities, [-1]))
            else:
                action = np.concatenate((velocities, [1]))
        elif np.linalg.norm(self._target_loc - obs[self._obs_name]) > self._final_thresh: 
            if self._intermediate_reached:
                target = self._target_loc
            elif np.linalg.norm(self._intermediate_point - obs[self._obs_name]) < 1e-2:
                target = self._target_loc
                self._intermediate_reached = True
            else:
                target = self._intermediate_point
            
            velocities = self._get_velocities(target - obs[self._obs_name], self._target_quat)
            action = np.concatenate((velocities, [10]))
        else:
            action = np.zeros(8)
            action[-1] = -1
        
        self._t += 1
        return action
    