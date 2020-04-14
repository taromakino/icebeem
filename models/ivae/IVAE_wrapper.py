import numpy as np
import torch
from torch import optim
from torch.utils.data import DataLoader

from models.ivae.IVAE import iVAE, CustomSyntheticDataset, to_one_hot

def IVAE_wrapper(X, U, batch_size=256, max_iter=7e4, seed=0, n_layers=3, hidden_dim=20, lr=1e-3, cuda=True):
    
    torch.manual_seed(seed)
    np.random.seed(seed)

    device = torch.device('cuda:0' if cuda else 'cpu')
    print('training on {}'.format(torch.cuda.get_device_name(device) if cuda else 'cpu'))

    # load data
    print('Creating shuffled dataset..')
    dset = CustomSyntheticDataset(X.astype(np.float32), U.astype(np.float32), device)
    loader_params = {'num_workers': 1, 'pin_memory': True} if cuda else {}
    train_loader = DataLoader(dset, shuffle=True, batch_size=batch_size, **loader_params)
    data_dim, latent_dim, aux_dim = dset.get_dims()
    N = len(dset)
    max_epochs = int(max_iter // len(train_loader) + 1)

    # define model and optimizer
    print('Defining model and optimizer..')
    model = iVAE(latent_dim, data_dim, aux_dim, activation='lrelu', device=device,
                 n_layers=n_layers, hidden_dim=hidden_dim)
    optimizer = optim.Adam(model.parameters(), lr=lr)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, factor=0.1, patience=3, verbose=True)

    # training loop
    print("Training..")
    it = 0
    model.train()
    while it < max_iter:
        elbo_train = 0
        epoch = it // len(train_loader) + 1
        for _, (x, u) in enumerate(train_loader):
            #x.to('cuda', non_blocking=True)
            #u.to('cuda', non_blocking=True)
            it += 1
            optimizer.zero_grad()

            x, u = x.to(device), u.to(device)

            elbo, z_est = model.elbo(x, u)
            elbo.mul(-1).backward()
            optimizer.step()

            elbo_train += -elbo.item()

        elbo_train /= len(train_loader)

        scheduler.step(elbo_train)
        #print('epoch {}/{} \tloss: {}'.format(epoch, max_epochs, elbo_train))

    Xt, Ut = dset.x, dset.u
    decoder_params, encoder_params, z, prior_params = model(Xt, Ut)
    params = {'decoder': decoder_params, 'encoder': encoder_params, 'prior': prior_params}

    return z, model, params
