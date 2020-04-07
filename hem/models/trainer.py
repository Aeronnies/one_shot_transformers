from hem.util import parse_basic_config
import torch
from torch.utils.data import DataLoader
import argparse
from hem.datasets import get_dataset
from multiprocessing import cpu_count
from torch.utils.tensorboard import SummaryWriter
import numpy as np
import datetime
import torch.nn as nn
import os
import shutil
import copy


class Trainer:
    def __init__(self, save_name='train', description="Default model trainer", comp_grad=True, drop_last=False):
        now = datetime.datetime.now()
        parser = argparse.ArgumentParser(description=description)
        parser.add_argument('experiment_file', type=str, help='path to YAML experiment config file')
        parser.add_argument('--device', type=int, default=None, nargs='+', help='target device (uses all if not specified)')
        args = parser.parse_args()
        self._config = parse_basic_config(args.experiment_file)

        # initialize device
        def_device = 0 if args.device is None else args.device[0]
        self._device = torch.device("cuda:{}".format(def_device))
        self._device_list = args.device

        # parse dataset class and create train/val loaders
        dataset_class = get_dataset(self._config['dataset'].pop('type'))
        dataset = dataset_class(**self._config['dataset'], mode='train')
        val_dataset = dataset_class(**self._config['dataset'], mode='val')
        self._train_loader = DataLoader(dataset, batch_size=self._config['batch_size'], shuffle=True, num_workers=self._config.get('loader_workers', cpu_count()), drop_last=drop_last)
        self._val_loader = DataLoader(val_dataset, batch_size=self._config['batch_size'], shuffle=True, num_workers=1, drop_last=drop_last)

        # set of file saving
        save_dir = os.path.join(self._config.get('save_path', './'), '{}_ckpt-{}-{}_{}-{}-{}'.format(save_name, now.hour, now.minute, now.day, now.month, now.year))
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        shutil.copyfile(args.experiment_file, os.path.join(save_dir, 'config.yaml'))
        self._writer = SummaryWriter(log_dir=os.path.join(save_dir, 'log'))
        self._save_fname = os.path.join(save_dir, 'model_save')
        self._comp_grad = comp_grad

    @property
    def config(self):
        return copy.deepcopy(self._config)

    def train(self, model, forward_fn, weights_fn=None):
        # wrap model in DataParallel if needed and transfer to correct device
        if self.device_count > 1:
            model = nn.DataParallel(model, device_ids=self.device_list)
        model = model.to(self._device)
        
        # initializer optimizer and lr scheduler
        optimizer = torch.optim.Adam(model.parameters(), self._config['lr'])
        vlm_alpha = self._config.get('vlm_alpha', 0.6)
        lr_schedule = self._config.get('lr_schedule', None)
        if lr_schedule == 'ReduceLROnPlateau':
            scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, 'min')
        elif lr_schedule is None:
            scheduler = None
        else:
            raise NotImplementedError

        # initialize constants:
        epochs = self._config.get('epochs', 1)
        log_freq = self._config.get('log_freq', 20)
        save_freq = self._config.get('save_freq', 5000)

        step = 0
        train_stats = {'loss': 0}
        val_iter = iter(self._val_loader)
        vl_running_mean = None
        for e in range(epochs):
            for inputs in self._train_loader:
                optimizer.zero_grad()
                loss_i, stats_i = forward_fn(model, self._device, *inputs)
                if self._comp_grad:
                    loss_i.backward()
                optimizer.step()
                
                # calculate iter stats
                mod_step = step % log_freq
                train_stats['loss'] = (loss_i.item() + mod_step * train_stats['loss']) / (mod_step + 1)
                for k, v in stats_i.items():
                    if k not in train_stats:
                        train_stats[k] = 0
                    train_stats[k] = (v + mod_step * train_stats[k]) / (mod_step + 1)
                
                if mod_step == log_freq - 1:
                    try:
                        val_inputs = next(val_iter)
                    except StopIteration:
                        val_iter = iter(self._val_loader)
                        val_inputs = next(val_iter)

                    with torch.no_grad():
                        val_loss, val_stats = forward_fn(model, self._device, *val_inputs)

                    # update running mean stat
                    if vl_running_mean is None:
                        vl_running_mean = val_loss.item()
                    vl_running_mean = val_loss.item() * vlm_alpha + vl_running_mean * (1 - vlm_alpha)

                    self._writer.add_scalar('loss/val', val_loss.item(), step)
                    for k, v in val_stats.items():
                        self._writer.add_scalar('{}/val'.format(k), v, step)
                    for k, v in train_stats.items():
                        self._writer.add_scalar('{}/train'.format(k), v, step)
                    self._writer.file_writer.flush()
                    print('epoch {3}/{4}, step {0}: loss={1:.4f} \t val loss={2:.4f}'.format(step, train_stats['loss'], vl_running_mean, e, epochs))
                else:
                    print('step {0}: loss={1:.4f}'.format(step, train_stats['loss']), end='\r')
                step += 1

                if step % save_freq == 0:
                    save_module = model
                    if weights_fn is not None:
                        save_module = weights_fn()
                    elif isinstance(model, nn.DataParallel):
                        save_module = model.module
                    torch.save(save_module, self._save_fname + '-{}.pt'.format(step))

            if scheduler is not None:
                scheduler.step(vl_running_mean)

    @property
    def device_count(self):
        if self._device_list is None:
            return torch.cuda.device_count()
        return len(self._device_list)

    @property
    def device_list(self):
        if self._device_list is None:
            return [i for i in range(torch.cuda.device_count())]
        return copy.deepcopy(self._device_list)

    @property
    def device(self):
        return copy.deepcopy(self._device)
