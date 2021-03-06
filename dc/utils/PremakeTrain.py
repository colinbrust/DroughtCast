import argparse
from dc.classification.TrainLSTMCategorical import train_lstm as cat_train
from dc.classification.TrainLSTMContinuous import train_lstm as con_train
from dc.utils.MakeLSTMPixelTS import make_lstm_pixel_ts
import os
import pickle

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Make training data, then train model.')
    parser.add_argument('-td', '--target_dir', type=str, help='Directory containing target memmap images.')
    parser.add_argument('-if', '--in_features', type=str,
                        help='Directory containing directorys with memmaps of training features')
    parser.add_argument('-nw', '--n_weeks', type=int, help='Number of week "history" to use as model inputs.')
    parser.add_argument('-sz', '--size', type=int, help='Number of pixels to use to train model.')
    parser.add_argument('-od', '--out_dir', type=str, help='Directory to put new files into.')
    parser.add_argument('-rep', '--reps', type=int, help='How many new models to train.')
    parser.add_argument('-e', '--epochs', type=int, help='Number of epochs to use.')
    parser.add_argument('--cat', dest='cat', action='store_true',
                        help='Train model that treats drought as categorical variables.')
    parser.add_argument('--no-cat', dest='cat', action='store_false',
                        help='Train model that treats drought as continuous variable.')
    parser.add_argument('--cuda', dest='cuda', action='store_true', help='Train model on GPU.')
    parser.add_argument('--no-cuda', dest='cuda', action='store_false', help='Train model on CPU.')
    parser.add_argument('--state', dest='state', action='store_true', help='Train Model as stateful.')
    parser.add_argument('--no-state', dest='state', action='store_false', help='Train model as stateless.')
    parser.set_defaults(cuda=True)
    parser.set_defaults(cat=True)
    parser.set_defaults(state=False)
    parser.set_defaults(cuda=True)
    parser.set_defaults(cat=True)

    args = parser.parse_args()

    target_dir = os.path.abspath(args.target_dir)
    in_features = os.path.abspath(args.in_features)
    out_dir = os.path.abspath(args.out_dir)
    base_dir = os.getcwd()
    model = cat_train if args.cat else con_train
    
    for i in range(args.reps):

        new_dir = os.path.join(base_dir, 'model'+str(i))
        os.mkdir(new_dir)
        os.chdir(new_dir)

        pickle_name = make_lstm_pixel_ts(
            target_dir=target_dir, in_features=in_features, n_weeks=args.n_weeks,
            size=args.size, out_dir=out_dir, rm_years=True, init=True
        )

        infile = open(pickle_name, 'rb')
        pick = pickle.load(infile)
        infile.close()
        print(pickle_name)
        week_f = os.path.join(out_dir, pick['featType-weekly'])
        mon_f = os.path.join(out_dir, pick['featType-monthly'])
        const_f = os.path.join(out_dir, pick['featType-constant'])
        target_f = os.path.join(out_dir, pick['featType-target'])

        model(
            week_f=week_f, mon_f=mon_f, const_f=const_f, target_f=target_f,
            epochs=args.epochs, batch_size=1024, hidden_size=1024,
            cuda=args.cuda, init=True, num_layers=1
        )

        os.chdir(base_dir)

        os.remove(pickle_name)
        os.remove(week_f)
        os.remove(mon_f)
        os.remove(const_f)
        os.remove(target_f)




