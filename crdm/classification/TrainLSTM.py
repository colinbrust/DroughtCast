import torch
from torch import nn
from torch.utils.data import DataLoader
from torch.utils.data.sampler import SubsetRandomSampler
from torch.optim.lr_scheduler import ReduceLROnPlateau
import numpy as np
from sklearn.model_selection import train_test_split
from collections import Counter
import pickle
import argparse
from crdm.utils.ParseFileNames import parse_fname
from crdm.loaders.PixelLoader import PixelLoader

device = torch.device('cuda:0' if torch.cuda.is_available() else "cpu")


class LSTM(nn.Module):
    def __init__(self, monthly_size=1, weekly_size=1, hidden_size=64, output_size=1, batch_size=64, const_size=18):
        super().__init__()

        self.hidden_size = hidden_size
        self.batch_size = batch_size

        self.weekly_lstm = nn.LSTM(weekly_size, hidden_size)
        self.monthly_lstm = nn.LSTM(monthly_size, hidden_size)

        # Downscale to output size
        self.classifier = nn.Sequential(
            nn.Linear(2*hidden_size + const_size, 128),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.Dropout(0.25),
            nn.Linear(128, 256),
            nn.BatchNorm1d(256),
            nn.ReLU(),
            nn.Dropout(0.25),
            nn.Linear(256, 128),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.Dropout(0.25),
            nn.Linear(128, 64),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Dropout(0.25),
            nn.Linear(64, 32),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.Dropout(0.25),
            nn.Linear(32, 16),
            nn.BatchNorm1d(16),
            nn.ReLU(),
            nn.Dropout(0.25),
            nn.Linear(16, output_size),
            nn.ReLU()
        )

        self.hidden_cell = (torch.zeros(1, batch_size, self.hidden_size, device=device),
                            torch.zeros(1, batch_size, self.hidden_size, device=device))

    def forward(self, weekly_seq, monthly_seq, constants):
        # Run the LSTM forward
        weekly_out, _ = self.weekly_lstm(weekly_seq, self.hidden_cell)
        monthly_out, _ = self.monthly_lstm(monthly_seq, self.hidden_cell)

        # Concatenate the last output of the LSTM timeseries with the constant inputs
        lstm_and_const = torch.cat((weekly_out[-1], monthly_out[-1], constants), dim=1)

        # Make predictions
        preds = self.classifier(lstm_and_const)
        return preds


def train_lstm(const_f, week_f, mon_f, target_f, epochs=50, batch_size=64, hidden_size=64):
    # const_f ='/mnt/e/PycharmProjects/CRDM/data/premade/featType-constant_trainingType-pixelPremade_nWeeks-25_leadTime-6_size-100_rmFeatures-False.dat'
    # mon_f = '/mnt/e/PycharmProjects/CRDM/data/premade/featType-monthly_trainingType-pixelPremade_nWeeks-25_leadTime-6_size-100_rmFeatures-False.dat'
    # target_f = '/mnt/e/PycharmProjects/CRDM/data/premade/featType-target_trainingType-pixelPremade_nWeeks-25_leadTime-6_size-100_rmFeatures-False.dat'
    # week_f = '/mnt/e/PycharmProjects/CRDM/data/premade/featType-weekly_trainingType-pixelPremade_nWeeks-25_leadTime-6_size-100_rmFeatures-False.dat'
    # epochs = 10
    # batch_size = 64
    # hidden_size = 64

    info = parse_fname(const_f)
    lead_time = info['leadTime']
    const_size = 1 if info['rmFeatures'] == 'True' else 3

    # Make data loader
    loader = PixelLoader(const_f, week_f, mon_f, target_f)

    # Split into training and test sets
    train, test = train_test_split([x for x in range(len(loader))], test_size=0.25)
    train_sampler = SubsetRandomSampler(train)
    test_sampler = SubsetRandomSampler(test)

    train_loader = DataLoader(dataset=loader, batch_size=batch_size, sampler=train_sampler)
    test_loader = DataLoader(dataset=loader, batch_size=batch_size, sampler=test_sampler)

    # Define model, loss and optimizer.
    hyperparams = loader[0]
    model = LSTM(weekly_size=hyperparams['week'].shape[1], monthly_size=hyperparams['mon'].shape[1], hidden_size=hidden_size, output_size=6,
                 batch_size=batch_size, const_size=hyperparams['const'].shape[0])

    model.to(device)

    if torch.cuda.is_available():
        print('Using GPU')
        model.cuda()

    # Provide relative frequency weights to use in loss function. 
    targets = np.memmap(target_f, dtype='int8', mode='r')
    counts = list(Counter(targets).values())
    weights = torch.Tensor([1 - (x / sum(counts)) for x in counts]).type(
        torch.cuda.FloatTensor if torch.cuda.is_available() else torch.FloatTensor)
    criterion = nn.CrossEntropyLoss(weight=weights)
    lr = 1e-3
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = ReduceLROnPlateau(optimizer, mode='min', patience=3, threshold=1e-4, verbose=True)

    prev_best_loss = 1e6
    err_out = {}

    out_name_mod = 'modelType-LSTM_epochs-{}_batch-{}_nMonths-{}_hiddenSize-{}_leadTime-{}_rmFeatures-{}_fType-model.p'.format(
        epochs, batch_size, info['nWeeks'], hidden_size, lead_time, info['rmFeatures'])
    out_name_err = 'modelType-LSTM_epochs-{}_batch-{}_nMonths-{}_hiddenSize-{}_leadTime-{}_rmFeatures-{}_fType-err.p'.format(
        epochs, batch_size, info['nWeeks'], hidden_size, lead_time, info['rmFeatures'])

    for epoch in range(epochs):
        total_loss = 0
        train_loss = []
        test_loss = []
        model.train()

        # Loop over each subset of data
        for i, item in enumerate(train_loader, 1):

            try:

                mon = item['mon'].permute(1, 0, 2)
                week = item['week'].permute(1, 0, 2)
                const = item['const'].permute(0, 1)

                mon = mon.type(torch.cuda.FloatTensor if torch.cuda.is_available() else torch.FloatTensor)
                week = week.type(torch.cuda.FloatTensor if torch.cuda.is_available() else torch.FloatTensor)
                const = const.type(torch.cuda.FloatTensor if torch.cuda.is_available() else torch.FloatTensor)

                # Zero out the optimizer's gradient buffer
                optimizer.zero_grad()

                # Make prediction with model
                outputs = model(week, mon, const)

                # Compute the loss and step the optimizer
                loss = criterion(
                    outputs.type(torch.cuda.FloatTensor if torch.cuda.is_available() else torch.FloatTensor),
                    item['target'].type(torch.cuda.LongTensor if torch.cuda.is_available() else torch.LongTensor))
                loss.backward(retain_graph=True)
                optimizer.step()

                if i % 500 == 0:
                    print('Epoch: {}, Train Loss: {}'.format(epoch, loss.item()))

                # Store loss info
                train_loss.append(loss.item())

            except RuntimeError as e:
                # For some reason the SubsetRandomSampler makes uneven batch sizes at the end of the batch,
                # so this is done as a workaound.
                print(e, '\nSkipping this mini-batch.')

        # Switch to evaluation mode
        model.eval()
        for i, item in enumerate(test_loader, 1):

            try:

                mon = item['mon'].permute(1, 0, 2)
                week = item['week'].permute(1, 0, 2)
                const = item['const'].permute(0, 1)

                mon = mon.type(torch.cuda.FloatTensor if torch.cuda.is_available() else torch.FloatTensor)
                week = week.type(torch.cuda.FloatTensor if torch.cuda.is_available() else torch.FloatTensor)
                const = const.type(torch.cuda.FloatTensor if torch.cuda.is_available() else torch.FloatTensor)

                # Run model on test set
                outputs = model(week, mon, const)
                loss = criterion(
                    outputs.type(torch.cuda.FloatTensor if torch.cuda.is_available() else torch.FloatTensor),
                    item['target'].type(torch.cuda.LongTensor if torch.cuda.is_available() else torch.LongTensor))

                if i % 500 == 0:
                    print('Epoch: {}, Test Loss: {}\n'.format(epoch, loss.item()))

                # Save loss info
                total_loss += loss.item()
                test_loss.append(loss.item())

            except RuntimeError as e:
                # For some reason the SubsetRandomSampler makes uneven batch sizes at the end of the batch,
                # so this is done as a workaound.
                print(e, '\nSkipping this mini-batch.')

        # If our new loss is better than old loss, save the model
        if prev_best_loss > total_loss:
            torch.save(model.state_dict(), out_name_mod)
            prev_best_loss = total_loss

        scheduler.step(total_loss)

        # Save out train and test set loss. 
        err_out[epoch] = {'train': train_loss,
                          'test': test_loss}

        with open(out_name_err, 'wb') as f:
            pickle.dump(err_out, f)


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Train Drought Prediction Model')
    parser.add_argument('-c', '--const_f', type=str, help='File of memmap of constants.')
    parser.add_argument('-m', '--mon_f', type=str, help='File of memmap of monthlys.')
    parser.add_argument('-t', '--target_f', type=str, help='File of memmap of targets.')
    parser.add_argument('-e', '--epochs', type=int, default=25, help='Number of epochs.')
    parser.add_argument('-bs', '--batch_size', type=int, help='Batch size to train model with.')
    parser.add_argument('-hs', '--hidden_size', type=int, help='LSTM hidden dimension size.')
    parser.add_argument('--search', dest='search', action='store_true',
                        help='Perform gridsearch for hyperparameter selection.')
    parser.add_argument('--no-search', dest='search', action='store_false',
                        help='Do not perform gridsearch for hyperparameter selection.')
    parser.set_defaults(search=False)

    args = parser.parse_args()

    if args.search:
        for hidden in [32, 64, 128, 256, 512, 1024]:
            for batch in [32, 64, 128, 256, 512, 1024]:
                train_lstm(const_f=args.const_f, mon_f=args.mon_f, target_f=args.target_f,
                           epochs=args.epochs, batch_size=batch, hidden_size=hidden)

    else:
        try:
            train_lstm(const_f=args.const_f, mon_f=args.mon_f, target_f=args.target_f,
                       epochs=args.epochs, batch_size=args.batch_size, hidden_size=args.hidden_size)
        except AttributeError as e:
            print('-bs and -hs flags must be used when you are not using the search option.')
