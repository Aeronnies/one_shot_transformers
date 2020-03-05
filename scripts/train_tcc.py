from hem.util import parse_basic_config
import torch
import argparse
from hem.datasets import get_dataset
from hem.models import get_model
from torch.utils.data import DataLoader
from multiprocessing import cpu_count
from torch.utils.tensorboard import SummaryWriter
import torch.nn as nn
import numpy as np
import datetime


if __name__ == '__main__':
    now = datetime.datetime.now()
    parser = argparse.ArgumentParser(description="test")
    parser.add_argument('experiment_file', type=str, help='path to YAML experiment config file')
    parser.add_argument('--device', type=int, default=None, nargs='+', help='target device (uses all if not specified)')
    args = parser.parse_args()
    config = parse_basic_config(args.experiment_file)
    
    # initialize device
    def_device = 0 if args.device is None else args.device[0]
    device = torch.device("cuda:{}".format(def_device))

    # parse dataset
    dataset_class = get_dataset(config['dataset'].pop('type'))
    dataset = dataset_class(**config['dataset'], mode='train')
    val_dataset = dataset_class(**config['dataset'], mode='val')
    train_loader = DataLoader(dataset, batch_size=config['batch_size'], shuffle=True, num_workers=config.get('loader_workers', cpu_count()))
    val_loader = DataLoader(val_dataset, batch_size=config['batch_size'], shuffle=True, num_workers=1)
    
    # parser model
    model_class = get_model(config['model'].pop('type'))
    model = model_class(**config['model'])
    if torch.cuda.device_count() > 1 and args.device is None:
        model = nn.DataParallel(model)
    elif args.device is not None and len(args.device) > 1:
        model = nn.DataParallel(model, device_ids=args.device)
    model.to(device)

    # optimizer
    cross_entropy = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), config['lr'])
    writer = SummaryWriter(log_dir=config.get('summary_log_dir', './tcc_log_{}-{}_{}-{}-{}'.format(now.hour, now.minute, now.day, now.month, now.year)))
    save_path = config.get('save_path', './tcc_weights_{}-{}_{}-{}-{}'.format(now.hour, now.minute, now.day, now.month, now.year))

    step = 0
    loss_stat, accuracy_stat, error_stat = 0, 0, 0
    val_iter = iter(val_loader)
    for _ in range(config.get('epochs', 10)):
        for t1, t2, _ in train_loader:
            t1, t2 = t1.to(device), t2.to(device)
            optimizer.zero_grad()

            U = model(t1)
            V = model(t2)

            B, chosen_i = np.arange(config['batch_size']), np.random.randint(t1.shape[1], size=config['batch_size'])
            deltas = torch.sum((U[B,chosen_i][:,None] - V) ** 2, dim=2)
            v_hat = torch.sum(torch.nn.functional.softmax(-deltas, dim=1)[:,:,None] * V, dim=1)
            class_logits = -torch.sum((v_hat[:,None] - U) ** 2, dim=2)
            
            loss = cross_entropy(class_logits, torch.from_numpy(chosen_i).to(device)) 
            loss.backward()
            optimizer.step()
            
            # calculate iter stats
            log_freq = config.get('log_freq', 50)
            mod_step = step % log_freq
            loss_stat = (loss.item() + mod_step * loss_stat) / (mod_step + 1)
            argmaxes = np.argmax(class_logits.detach().cpu().numpy(), 1)
            accuracy_stat = (np.sum(argmaxes == chosen_i) / config['batch_size'] + mod_step * accuracy_stat) / (mod_step + 1)
            error_stat = (np.sqrt(np.sum(np.square(argmaxes - chosen_i))) / config['batch_size'] + mod_step * error_stat) / (mod_step + 1)
            
            if mod_step == log_freq - 1:
                try:
                    t1, t2, _ = next(val_iter)
                except StopIteration:
                    val_iter = iter(val_loader)
                    t1, t2, _ = next(val_iter)

                with torch.no_grad():
                    t1, t2 = t1.to(device), t2.to(device)
                    U = model(t1)
                    V = model(t2)

                    B, chosen_i = np.arange(config['batch_size']), np.random.randint(t1.shape[1], size=config['batch_size'])
                    deltas = torch.sum((U[B,chosen_i][:,None] - V) ** 2, dim=2)
                    v_hat = torch.sum(torch.nn.functional.softmax(-deltas, dim=1)[:,:,None] * V, dim=1)
                    class_logits = -torch.sum((v_hat[:,None] - U) ** 2, dim=2)
                    
                    loss_val = cross_entropy(class_logits, torch.from_numpy(chosen_i).to(device)).item()
                    argmaxes = np.argmax(class_logits.detach().cpu().numpy(), 1)
                    accuracy_val = np.sum(argmaxes == chosen_i) / config['batch_size']
                    error_val = np.sqrt(np.sum(np.square(argmaxes - chosen_i))) / config['batch_size']

                writer.add_scalar('loss/train', loss_stat, step)
                writer.add_scalar('accuracy/train', accuracy_stat, step)
                writer.add_scalar('error/train', error_stat, step)
                writer.add_scalar('loss/val', loss_val, step)
                writer.add_scalar('accuracy/val', accuracy_val, step)
                writer.add_scalar('error/val', error_val, step)
                writer.file_writer.flush()
                print('step {0}: loss={1:.4f} \t\t accuracy={2:2.3f} \t\t error={3:2.3f} \t\t val loss={4:.4f}'.format(step, loss_stat, accuracy_stat, error_stat, loss_val))
            else:
                print('step {0}: loss={1:.4f} \t\t accuracy={2:2.3f} \t\t error={3:2.3f}'.format(step, loss_stat, accuracy_stat, error_stat), end='\r')
            
            step += 1
            if step % config.get('save_freq', 10000) == 0:
                torch.save(model, save_path + '-{}.pt'.format(step))
