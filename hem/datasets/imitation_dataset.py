from torch.utils.data import Dataset
from .agent_dataset import AgentDemonstrations
from .teacher_dataset import TeacherDemonstrations
from hem.datasets import load_traj
from hem.datasets.util import randomize_video, split_files
import torch
import os
import numpy as np
import json


class _AgentDatasetNoContext(AgentDemonstrations):
    def __init__(self, **params):
        params.pop('T_context', None)
        super().__init__(T_context=0, **params)


class ImitationDataset(Dataset):
    def __init__(self, root_dir, mode='train', split=[0.9, 0.1], before_grip=False, recenter_actions=False, **params):
        self._root = os.path.expanduser(root_dir)
        mappings_file = os.path.join(self._root, 'mappings.json')
        with open(mappings_file, 'r') as f:
            self._mappings = json.load(f)
        
        teacher_files = sorted(list(self._mappings.keys()))
        order = split_files(len(teacher_files), split, mode)
        self._teacher_files = [teacher_files[o] for o in order]
        self._teacher_dataset = TeacherDemonstrations(files=[], **params)
        self._agent_dataset = _AgentDatasetNoContext(files=[], **params)
        self._before_grip = before_grip
        self._recenter_actions = recenter_actions

    def __len__(self):
        return len(self._teacher_files)
    
    def __getitem__(self, index):
        if torch.is_tensor(index):
            index = index.tolist()
        
        # retrieve trajectory from mapping
        teacher_traj, agent_traj = self._teacher_files[index], self._mappings[self._teacher_files[index]]
        teacher_traj, agent_traj = [load_traj(os.path.join(self._root, f_name)) for f_name in (teacher_traj, agent_traj)]

        obj_detected = np.concatenate([agent_traj.get(t, False)['obs']['object_detected'] for t in range(len(agent_traj))])
        qpos = np.concatenate([agent_traj.get(t, False)['obs']['gripper_qpos'] for t in range(len(agent_traj))])
        if obj_detected.any():
            grip_t = int(np.argmax(obj_detected))
            drop_t = min(len(agent_traj) - 1, int(len(agent_traj) - np.argmax(obj_detected[::-1])))
        else:
            closed = np.isclose(qpos, 0)
            grip_t = int(np.argmax(closed))
            drop_t = min(len(agent_traj) - 1, int(len(agent_traj) - np.argmax(closed[::-1])))
        grip, drop = agent_traj.get(grip_t, False), agent_traj.get(drop_t, False)
        grip = np.concatenate((grip['obs']['ee_pos'][:3], grip['obs']['axis_angle'])).astype(np.float32)
        drop = np.concatenate((drop['obs']['ee_pos'][:3], drop['obs']['axis_angle'])).astype(np.float32)

        if self._before_grip: # make this hack more elegant
            agent_pairs = self._agent_dataset._get_pairs(agent_traj, grip_t)
        else:
            agent_pairs, _ = self._agent_dataset.proc_traj(agent_traj)
        agent_pairs['grip_location'], agent_pairs['drop_location'] = grip, drop

        if self._recenter_actions:
            agent_pairs['actions'][:,:3] -= np.array([0.65, 0.06, 0.15]).reshape((1, -1)).astype(np.float32)
            agent_pairs['actions'][:,:3] /= np.array([0.2, 0.41, 0.3166]).reshape((1, -1)).astype(np.float32)
        return self._teacher_dataset.proc_traj(teacher_traj), agent_pairs
