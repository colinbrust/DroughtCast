import argparse
from crdm.loaders.SmartLoader import SmartLoader
from crdm.classification.SeqConvLSTM import SeqLSTM
from crdm.utils.MakeModelDir import make_model_dir
import pickle
import torch
from torch.utils.data import DataLoader
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch import nn

FEATS = ['pr', 'vpd', 'tmmx', 'sm-rootzone', 'vapor']


def train_model(feature_dir, epochs=50, batch_size=64, hidden_size=64, n_weeks=25, max_lead_time=12, crop_size=16):

    test_loader = SmartLoader(feature_dir, train=False, max_lead_time=max_lead_time, n_weeks=n_weeks,
                              pixel=False, crop_size=crop_size, feats=FEATS)

    train_loader = SmartLoader(feature_dir, train=True, max_lead_time=max_lead_time, n_weeks=n_weeks,
                               pixel=False, crop_size=crop_size, feats=FEATS)

    train_loader = DataLoader(dataset=train_loader, batch_size=batch_size, shuffle=True)
    test_loader = DataLoader(dataset=test_loader,  batch_size=batch_size, shuffle=True)

    # Define model, loss and optimizer.
    model = SeqLSTM(nf=hidden_size, in_chan=len(FEATS))

    if torch.cuda.is_available():
        print('Using GPU')
        model.cuda()

    # Provide relative frequency weights to use in loss function.
    criterion = nn.MSELoss()
    lr = 3e-4
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = ReduceLROnPlateau(optimizer, mode='min', patience=2, threshold=1e-5, verbose=True, factor=0.5)

    prev_best_loss = 1e6
    err_out = {}

    make_model_dir()

    metadata = {'epochs': epochs,
                'batch_size': batch_size,
                'hidden_size': hidden_size,
                'n_weeks': n_weeks,
                'max_lead_time': max_lead_time,
                'crop_size': crop_size,
                'feats': FEATS}

    with open('metadata.p', 'wb') as f:
        pickle.dump(metadata, f)

    for epoch in range(epochs):
        total_loss = 0
        train_loss = []
        test_loss = []

        model.train()

        # Loop over each subset of data
        for i, item in enumerate(train_loader, 1):

            features, target = item[0], item[1]

            # Zero out the optimizer's gradient buffer
            optimizer.zero_grad()

            # Make prediction with model

            outputs = model(features)
            print(outputs.shape)
            outputs = outputs.squeeze()
            outputs = outputs[:, -1, :, :]

            # Compute the loss and step the optimizer
            loss = criterion(outputs, target)
            loss.backward()
            optimizer.step()
            if i % 10 == 0:
                print('Epoch: {}, Train Loss: {}'.format(epoch, loss.item()))

            # Store loss info
            train_loss.append(loss.item())

        # Switch to evaluation mode
        model.eval()

        for i, item in enumerate(test_loader, 1):

            features, target = item[0], item[1]

            # Make prediction with model

            outputs = model(features)
            outputs = outputs.squeeze()
            outputs = outputs[:, -1, :, :]

            # Compute the loss and step the optimizer
            loss = criterion(outputs, target)
            if i % 10 == 0:
                print('Epoch: {}, Test Loss: {}'.format(epoch, loss.item()))

            # Save loss info
            total_loss += loss.item()
            test_loss.append(loss.item())

        # If our new loss is better than old loss, save the model
        if prev_best_loss > total_loss:
            torch.save(model.state_dict(), 'model.p')
            prev_best_loss = total_loss

        scheduler.step(total_loss)

        # Save out train and test set loss.
        err_out[epoch] = {'train': train_loss,
                          'test': test_loss}

        with open('err.p', 'wb') as f:
            pickle.dump(err_out, f)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Train Drought Prediction Model')
    parser.add_argument('-td', '--target_dir', type=str, help='Directory containing output classes.')
    parser.add_argument('-if', '--in_features', type=str, help='Directory containing training features.')
    parser.add_argument('-e', '--epochs', type=int, default=25, help='Number of epochs.')
    parser.add_argument('-bs', '--batch_size', type=int, default=64, help='Batch size to train model with.')
    parser.add_argument('-hs', '--hidden_size', type=int, default=64, help='LSTM hidden dimension size.')
    parser.add_argument('-nw', '--n_weeks', type=int, default=25, help='Number of week history to use for prediction')
    parser.add_argument('-mx', '--max_lead', type=int, default=8, help='How many weeks into the future to make predictions.')
    parser.add_argument('-cs', '--crop_size', type=int, default=16, help='Crop size to use for prediction.')

    args = parser.parse_args()

    train_model(feature_dir=args.feature_dir, epochs=args.epochs,
                batch_size=args.batch_size, hidden_size=args.hidden_size,
                n_weeks=args.n_weeks, max_lead_time=args.max_lead, crop_size=args.crop_size)
