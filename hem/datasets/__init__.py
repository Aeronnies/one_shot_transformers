from hem.datasets.savers.trajectory import Trajectory
from hem.datasets.savers.hdf5_trajectory import HDF5Trajectory
import pickle as pkl
import glob
import os
try:
    raise NotImplementedError
    from hem.datasets.savers.render_loader import ImageRenderWrapper
    import_render_wrapper = True
except:
    import_render_wrapper = False


def get_dataset(name):
    if name == 'something something':
        from .something_dataset import SomethingSomething
        return SomethingSomething
    elif name == 'agent teacher':
        from .agent_teacher_dataset import AgentTeacherDataset
        return AgentTeacherDataset
    elif name == 'paired agent teacher':
        from .agent_teacher_dataset import PairedAgentTeacherDataset
        return PairedAgentTeacherDataset
    elif name == 'labeled agent teacher':
        from .agent_teacher_dataset import LabeledAgentTeacherDataset
        return LabeledAgentTeacherDataset
    elif name == 'agent':
        from .agent_dataset import AgentDemonstrations
        return AgentDemonstrations
    elif name == 'paired frames':
        from .frame_datasets import PairedFrameDataset
        return PairedFrameDataset
    elif name == 'synced frames':
        from .frame_datasets import SyncedFramesDataset
        return SyncedFramesDataset
    elif name == 'unpaired frames':
        from .frame_datasets import UnpairedFrameDataset
        return UnpairedFrameDataset
    elif name == 'imitation':
        from .imitation_dataset import ImitationDataset
        return ImitationDataset
    elif name == 'states':
        from .imitation_dataset import StateDataset
        return StateDataset
    elif name == 'states imcontext':
        from .imitation_dataset import StateDatasetVisionContext
        return StateDatasetVisionContext
    elif name == 'pick place':       
        from .imitation_dataset import AuxDataset
        return AuxDataset
    elif name == 'gen grip':
        from .image_gen_dataset import GenGrip
        return GenGrip
    elif name == 'goal image':
        from .image_gen_dataset import GoalImageDataset
        return GoalImageDataset
    elif name == 'aux contrastive':
        from .frame_datasets import AuxContrastiveDataset
        return AuxContrastiveDataset
    raise NotImplementedError


def get_validation_batch(loader, batch_size=8):
    pass


def load_traj(fname):
    if '.pkl' in fname:
        traj = pkl.load(open(fname, 'rb'))['traj']
    elif '.hdf5' in fname:
        traj = HDF5Trajectory()
        traj.load(fname)
    else:
        raise NotImplementedError

    traj = traj if not import_render_wrapper else ImageRenderWrapper(traj)
    return traj


def get_files(root_dir):
    root_dir = os.path.expanduser(root_dir)
    if 'pkl' in root_dir or 'hdf5' in root_dir:
        return sorted(glob.glob(root_dir))
    pkl_files = glob.glob(root_dir + '*.pkl')
    hdf5_files = glob.glob(root_dir + '*.hdf5')
    return sorted(pkl_files + hdf5_files)
