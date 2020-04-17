### run conditional denoising score matching experiments on MNIST
#
#
# much of this could it adapted from: https://github.com/ermongroup/ncsn/
#

import logging
import os
import shutil

import numpy as np
import torch
import torch.optim as optim
import torchvision.transforms as transforms
import tqdm
from torch.utils.data import DataLoader
from torch.utils.data.dataloader import default_collate
from torchvision.datasets import MNIST, CIFAR10, FashionMNIST

from losses.dsm import conditional_dsm
from models.refinenet_dilated_baseline import RefineNetDilated

__all__ = ['mnist_runner'] 


def my_collate(batch, nSeg=8):
    modified_batch = []
    for item in batch:
        image, label = item
        if label in range(nSeg):
            modified_batch.append(item)
    return default_collate(modified_batch)


def my_collate_rev(batch, nSeg=8):
    modified_batch = []
    for item in batch:
        image, label = item
        if label in range(nSeg, 10):
            modified_batch.append(item)
    return default_collate(modified_batch)


class mnist_runner():
    def __init__(self, args, config):
        self.args = args
        self.config = config
        self.nSeg = config.n_labels
        self.seed = args.seed
        self.subsetSize = args.SubsetSize  # subset size, only for baseline transfer learning, otherwise ignored!
        print('USING CONDITIONING DSM')
        print('Number of segments: ' + str(self.nSeg))

    def get_optimizer(self, parameters):
        if self.config.optim.optimizer == 'Adam':
            return optim.Adam(parameters, lr=self.config.optim.lr, weight_decay=self.config.optim.weight_decay,
                              betas=(self.config.optim.beta1, 0.999), amsgrad=self.config.optim.amsgrad)
        elif self.config.optim.optimizer == 'RMSProp':
            return optim.RMSprop(parameters, lr=self.config.optim.lr, weight_decay=self.config.optim.weight_decay)
        elif self.config.optim.optimizer == 'SGD':
            return optim.SGD(parameters, lr=self.config.optim.lr, momentum=0.9)
        else:
            raise NotImplementedError('Optimizer {} not understood.'.format(self.config.optim.optimizer))

    def logit_transform(self, image, lam=1e-6):
        image = lam + (1 - 2 * lam) * image
        return torch.log(image) - torch.log1p(-image)

    def train(self):
        if self.config.data.random_flip is False:
            tran_transform = test_transform = transforms.Compose([
                transforms.Resize(self.config.data.image_size),
                transforms.ToTensor()
            ])
        else:
            tran_transform = transforms.Compose([
                transforms.Resize(self.config.data.image_size),
                transforms.RandomHorizontalFlip(p=0.5),
                transforms.ToTensor()
            ])
            test_transform = transforms.Compose([
                transforms.Resize(self.config.data.image_size),
                transforms.ToTensor()
            ])

        if self.config.data.dataset == 'CIFAR10':
            dataset = CIFAR10(os.path.join(self.args.run, 'datasets', 'cifar10'), train=True, download=True,
                              transform=tran_transform)
            test_dataset = CIFAR10(os.path.join(self.args.run, 'datasets', 'cifar10_test'), train=False, download=True,
                                   transform=test_transform)

        elif self.config.data.dataset == 'MNIST':
            print('RUNNING REDUCED MNIST')
            dataset = MNIST('datasets/', train=True, download=True,
                            transform=tran_transform)
            test_dataset = MNIST('datasets_test/', train=False, download=True,
                                 transform=test_transform)

        elif self.config.data.dataset == 'FashionMNIST':
            dataset = FashionMNIST(os.path.join(self.args.run, 'datasets', 'FashionMNIST'), train=True, download=True,
                                   transform=tran_transform)
            test_dataset = FashionMNIST(os.path.join(self.args.run, 'datasets', 'FashionMNIST_test'), train=False,
                                        download=True, transform=tran_transform)

        elif self.config.data.dataset == 'MNIST_transferBaseline':
            # use same dataset as transfer_nets.py
            test_dataset = MNIST('datasets/mnist_test', train=False, download=True, transform=test_transform)
            print('TRANSFER BASELINES !! Subset size: ' + str(self.subsetSize))
            id_range = list(range(self.subsetSize))
            testset_1 = torch.utils.data.Subset(test_dataset, id_range)

        elif self.config.data.dataset == 'CIFAR10_transferBaseline':
            test_dataset = CIFAR10('datasets/cifar10_test', train=False, download=True, transform=test_transform)
            print('TRANSFER BASELINES !! Subset size: ' + str(self.subsetSize))
            id_range = list(range(self.subsetSize))
            testset_1 = torch.utils.data.Subset(test_dataset, id_range)

        elif self.config.data.dataset == 'FashionMNIST_transferBaseline':
            test_dataset = FashionMNIST(os.path.join(self.args.run, 'datasets', 'FashionMNIST_test'), train=False,
                                        download=True, transform=tran_transform)
            print('TRANSFER BASELINES !! Subset size: ' + str(self.subsetSize))
            id_range = list(range(self.subsetSize))
            testset_1 = torch.utils.data.Subset(test_dataset, id_range)
        else:
            raise ValueError('Unknown config dataset {}'.format(self.config.data.dataset))

        # apply collation for all datasets ! (we only consider MNIST and CIFAR10 anyway!)
        if self.config.data.dataset in ['MNIST', 'CIFAR10', 'FashionMNIST']:
            collate_helper = lambda batch: my_collate(batch, nSeg=self.nSeg)
            dataloader = DataLoader(dataset, batch_size=self.config.training.batch_size, shuffle=True, num_workers=0,
                                    collate_fn=collate_helper)
            test_loader = DataLoader(test_dataset, batch_size=self.config.training.batch_size, shuffle=True,
                                     num_workers=1, drop_last=True, collate_fn=collate_helper)

        elif self.config.data.dataset in ['MNIST_transferBaseline', 'CIFAR10_transferBaseline',
                                          'FashionMNIST_transferBaseline']:
            # trains a model on only digits 8,9 from scratch
            dataloader = DataLoader(testset_1, batch_size=self.config.training.batch_size, shuffle=True, num_workers=0,
                                    drop_last=True, collate_fn=my_collate_rev)
            print('loaded reduced subset')

        else:
            dataloader = DataLoader(dataset, batch_size=self.config.training.batch_size, shuffle=True, num_workers=1)
            test_loader = DataLoader(test_dataset, batch_size=self.config.training.batch_size, shuffle=True,
                                     num_workers=1, drop_last=True)

        self.config.input_dim = self.config.data.image_size ** 2 * self.config.data.channels

        tb_path = os.path.join(self.args.run, 'tensorboard', self.args.doc)
        if os.path.exists(tb_path):
            shutil.rmtree(tb_path)

        # define the final linear layer weights
        energy_net_finalLayer = torch.ones((self.config.data.image_size * self.config.data.image_size, self.nSeg)).to(
            self.config.device)
        energy_net_finalLayer.requires_grad_()

        # tb_logger = tensorboardX.SummaryWriter(log_dir=tb_path)
        enet = RefineNetDilated(self.config).to(self.config.device)

        enet = torch.nn.DataParallel(enet)

        optimizer = self.get_optimizer(list(enet.parameters()) + [energy_net_finalLayer])

        step = 0

        for epoch in range(self.config.training.n_epochs):
            loss_vals = []
            for i, (X, y) in enumerate(dataloader):
                # print(y.max())
                step += 1

                enet.train()
                X = X.to(self.config.device)
                X = X / 256. * 255. + torch.rand_like(X) / 256.
                if self.config.data.logit_transform:
                    X = self.logit_transform(X)

                # replace this with either dsm or dsm_conditional_score_estimation function !!
                y -= y.min()  # need to ensure its zero centered !
                loss = conditional_dsm(enet, X, y, energy_net_finalLayer, sigma=0.01)

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                # tb_logger.add_scalar('loss', loss, global_step=step)
                logging.info("step: {}, loss: {}, maxLabel: {}".format(step, loss.item(), y.max()))
                loss_vals.append(loss.item())
                if step >= self.config.training.n_iters:
                    return 0

                if step % self.config.training.snapshot_freq == 0:
                    if self.config.data.dataset in ['MNIST_transferBaseline', 'CIFAR10_transferBaseline']:
                        print('here!')
                        # just save the losses, thats all we care about
                        if self.config.data.store_loss:
                            # print('only storing losses')
                            import pickle
                            if self.config.data.dataset == 'MNIST_transferBaseline':
                                pickle.dump(loss_vals, open(
                                    'transfer_exp/transferRes/Baseline_Size' + str(self.subsetSize) + "_Seed" + str(
                                        self.seed) + '.p', 'wb'))
                            elif self.config.data.dataset == 'CIFAR10_transferBaseline':
                                pickle.dump(loss_vals, open('transfer_exp/transferRes_cifar/cifar_Baseline_Size' + str(
                                    self.subsetSize) + "_Seed" + str(self.seed) + '.p', 'wb'))
                        else:
                            pass
<<<<<<< HEAD
                        # save checkpoint for transfer learning! !
                        states = [
                            enet.state_dict(),
                            optimizer.state_dict(),
                        ]
                        torch.save(states, os.path.join(self.args.log, 'checkpoint_{}.pth'.format(step)))
                        torch.save(states, os.path.join(self.args.log, 'checkpoint.pth'))
=======
                        if True:
                            # save this one time for transfer learning!
                            states = [
                                enet.state_dict(),
                                optimizer.state_dict(),
                            ]
                            torch.save(states, os.path.join(self.args.log, 'checkpoint_{}.pth'.format(step)))
                            torch.save(states, os.path.join(self.args.log, 'checkpoint.pth'))
                            # and the final layer weights !
                            # import pickle
                            # torch.save( [energy_net_finalLayer], 'finalLayerweights_.pth')
                            # pickle.dump( energy_net_finalLayer, open('finalLayerweights.p', 'wb') )
>>>>>>> d3a3e2084b0306dc450ad54795e3be28bfe77d22
                    else:
                        states = [
                            enet.state_dict(),
                            optimizer.state_dict(),
                        ]
                        torch.save(states, os.path.join(self.args.log, 'checkpoint_{}.pth'.format(step)))
                        torch.save(states, os.path.join(self.args.log, 'checkpoint.pth'))
                        import pickle
                        torch.save([energy_net_finalLayer], os.path.join(self.args.log, 'finalLayerweights_.pth'))
                        pickle.dump(energy_net_finalLayer,
                                    open(os.path.join(self.args.log, 'finalLayerweights.p'), 'wb'))

    def Langevin_dynamics(self, x_mod, scorenet, n_steps=1000, step_lr=0.00002):
        images = []

        with torch.no_grad():
            for _ in range(n_steps):
                images.append(torch.clamp(x_mod, 0.0, 1.0).to('cpu'))
                noise = torch.randn_like(x_mod) * np.sqrt(step_lr * 2)
                grad = scorenet(x_mod)
                x_mod = x_mod + step_lr * grad + noise
                print("modulus of grad components: mean {}, max {}".format(grad.abs().mean(), grad.abs().max()))

            return images

    def test(self):
        states = torch.load(os.path.join(self.args.log, 'checkpoint.pth'), map_location=self.config.device)
        score = RefineNetDilated(self.config).to(self.config.device)
        score = torch.nn.DataParallel(score)

        score.load_state_dict(states[0])

        if not os.path.exists(self.args.image_folder):
            os.makedirs(self.args.image_folder)

        score.eval()

        if self.config.data.dataset == 'MNIST' or self.config.data.dataset == 'FashionMNIST':
            transform = transforms.Compose([
                transforms.Resize(self.config.data.image_size),
                transforms.ToTensor()
            ])

            if self.config.data.dataset == 'MNIST':
                dataset = MNIST(os.path.join(self.args.run, 'datasets', 'mnist'), train=True, download=True,
                                transform=transform)
            else:
                dataset = FashionMNIST(os.path.join(self.args.run, 'datasets', 'fmnist'), train=True, download=True,
                                       transform=transform)

            dataloader = DataLoader(dataset, batch_size=100, shuffle=True, num_workers=4)
            data_iter = iter(dataloader)
            samples, _ = next(data_iter)
            samples = samples.cuda()

            samples = torch.rand_like(samples)
            all_samples = self.Langevin_dynamics(samples, score, 1000, 0.00002)

            for i, sample in enumerate(tqdm.tqdm(all_samples)):
                sample = sample.view(100, self.config.data.channels, self.config.data.image_size,
                                     self.config.data.image_size)

                if self.config.data.logit_transform:
                    sample = torch.sigmoid(sample)

                torch.save(sample, os.path.join(self.args.image_folder, 'samples_{}.pth'.format(i)))


        else:
            transform = transforms.Compose([
                transforms.Resize(self.config.data.image_size),
                transforms.ToTensor()
            ])

            if self.config.data.dataset == 'CIFAR10':
                dataset = CIFAR10(os.path.join(self.args.run, 'datasets', 'cifar10'), train=True, download=True,
                                  transform=transform)

            dataloader = DataLoader(dataset, batch_size=100, shuffle=True, num_workers=4)
            data_iter = iter(dataloader)
            samples, _ = next(data_iter)
            samples = samples.cuda()
            samples = torch.rand_like(samples)

            all_samples = self.Langevin_dynamics(samples, score, 1000, 0.00002)

            for i, sample in enumerate(tqdm.tqdm(all_samples)):
                sample = sample.view(100, self.config.data.channels, self.config.data.image_size,
                                     self.config.data.image_size)

                if self.config.data.logit_transform:
                    sample = torch.sigmoid(sample)

                torch.save(sample, os.path.join(self.args.image_folder, 'samples_{}.pth'.format(i)))
