import torch
from hem.models import get_model, Trainer
from hem.models.util import batch_inputs
from hem.models.mdn_loss import MixtureDensityLoss, MixtureDensityTop
import torch.nn as nn


class ImitationModule(nn.Module):
    def __init__(self, config):
        super().__init__()
        # initialize visual embeddings
        embed = get_model(config['embedding'].pop('type'))
        self._embed = embed(**config['embedding'])

        # processes observation embeddings into action latents
        action_model = get_model(config['action_model'].pop('type'))
        self._action_model = action_model(**config['action_model'])

        # creates mixture density output
        self._mdn = MixtureDensityTop(**config['mdn'])

        self._aux = False
        if 'auxillary' in config:
            self._aux_linear = nn.Linear(config['auxillary']['in_dim'], config['auxillary']['out_dim'])
    
    def forward(self, images, depth=None):
        vis_embed = self._embed(images, depth)
        mean, sigma_inv, alpha = self._mdn(self._action_model(vis_embed))

        if self._aux:
            return mean, sigma_inv, alpha, self._aux_linear(vis_embed)
        return mean, sigma_inv, alpha, None


if __name__ == '__main__':
    trainer = Trainer('bc', "Trains Behavior Clone model on input data")
    config = trainer.config
    
    # build Imitation Module and MDN Loss
    model = ImitationModule(config)
    loss = MixtureDensityLoss()

    def forward(m, device, pairs, _):
        states, actions = batch_inputs(pairs, device)
        images = states['images'][:,:-1]
        depth = None
        if 'depth' in states:
            depth = states['depth'][:,:-1]

        if config.get('output_pos', True):
            actions = torch.cat((states['joints'][:,1:], actions[:,:,-1][:,:,None]), 2)
        
        mean, sigma_inv, alpha, pred_state = m(images, depth)
        l_mdn = loss(actions, mean, sigma_inv, alpha)

        stats = dict(mdn=l_mdn.item())
        if pred_state is not None:
            state_loss = torch.mean(torch.sqrt(torch.sum(torch.square(pred_state - states['joints'][:,:-1]), (1, 2))))
            stats['aux_loss'] = state_loss.item()
        return l_mdn + state_loss, stats
    trainer.train(model, forward)
