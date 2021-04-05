from crdm.classification.ConvLSTM import ConvLSTMCell
import torch
import torch.nn as nn


# Credit to: https://github.com/holmdk/Video-Prediction-using-PyTorch/blob/master/models/seq2seq_ConvLSTM.py
class SeqLSTM(nn.Module):
    def __init__(self, nf, in_chan, in_consts, n_weeks):
        super(SeqLSTM, self).__init__()

        """ ARCHITECTURE 
        # Encoder (ConvLSTM)
        # Encoder Vector (final hidden state of encoder)
        # Decoder (ConvLSTM) - takes Encoder Vector as input
        # Decoder (3D CNN) - produces regression predictions for our model
        """

        # Add dimension for the encoded constants.
        in_chan = in_chan + 1

        self.n_weeks = n_weeks
        self.encoder_1_convlstm = ConvLSTMCell(input_dim=in_chan,
                                               hidden_dim=nf,
                                               kernel_size=(3, 3),
                                               bias=True)

        self.encoder_2_convlstm = ConvLSTMCell(input_dim=nf,
                                               hidden_dim=nf,
                                               kernel_size=(3, 3),
                                               bias=True)

        self.decoder_1_convlstm = ConvLSTMCell(input_dim=nf,  # nf + 1
                                               hidden_dim=nf,
                                               kernel_size=(3, 3),
                                               bias=True)

        self.decoder_2_convlstm = ConvLSTMCell(input_dim=nf,
                                               hidden_dim=nf,
                                               kernel_size=(3, 3),
                                               bias=True)

        self.decoder_CNN = nn.Conv3d(in_channels=nf,
                                     out_channels=1,
                                     kernel_size=(1, 3, 3),
                                     padding=(0, 1, 1))

        self.constant_encoder = nn.Sequential(
            nn.Conv2d(in_channels=in_consts,
                      out_channels=16,
                      kernel_size=(3, 3),
                      padding=1),
            nn.Conv2d(in_channels=16,
                      out_channels=8,
                      kernel_size=(3, 3),
                      padding=1),
            nn.Conv2d(in_channels=8,
                      out_channels=1,
                      kernel_size=(3, 3),
                      padding=1)
        )

        self.drop = nn.Dropout3d(p=0.5)
        
    def autoencoder(self, x, seq_len, future_step, h_t, c_t, h_t2, c_t2, h_t3, c_t3, h_t4, c_t4):

        outputs = []

        # encoder
        for t in range(seq_len):
            h_t, c_t = self.encoder_1_convlstm(input_tensor=x[:, t, :, :],
                                               cur_state=[h_t, c_t])
            h_tD = self.drop(h_t)

            h_t2, c_t2 = self.encoder_2_convlstm(input_tensor=h_tD,
                                                 cur_state=[h_t2, c_t2])

        # encoder_vector
        encoder_vector = h_t2

        # decoder
        for t in range(future_step):
            h_t3, c_t3 = self.decoder_1_convlstm(input_tensor=encoder_vector,
                                                 cur_state=[h_t3, c_t3])
            h_t3D = self.drop(h_t3)

            h_t4, c_t4 = self.decoder_2_convlstm(input_tensor=h_t3D,
                                                 cur_state=[h_t4, c_t4])

            encoder_vector = h_t4
            outputs += [h_t4]  # predictions

        outputs = torch.stack(outputs, 1)
        outputs = outputs.permute(0, 2, 1, 3, 4)
        outputs = self.drop(outputs)
        outputs = self.decoder_CNN(outputs)
        outputs = torch.nn.Sigmoid()(outputs)

        return outputs

    def forward(self, x, const, future_seq=0, hidden_state=None):

        """
        Parameters
        ----------
        input_tensor:
            5-D Tensor of shape (b, t, c, h, w)        #   batch, time, channel, height, width
        """

        # find size of different input dimensions
        b, seq_len, _, h, w = x.size()

        # initialize hidden states
        h_t, c_t = self.encoder_1_convlstm.init_hidden(batch_size=b, image_size=(h, w))
        h_t2, c_t2 = self.encoder_2_convlstm.init_hidden(batch_size=b, image_size=(h, w))
        h_t3, c_t3 = self.decoder_1_convlstm.init_hidden(batch_size=b, image_size=(h, w))
        h_t4, c_t4 = self.decoder_2_convlstm.init_hidden(batch_size=b, image_size=(h, w))
        
        encoded_constants = self.constant_encoder(const)
        encoded_constants = encoded_constants.squeeze()
        print(encoded_constants.shape)
        encoded_constants = encoded_constants.unsqueeze(0).unsqueeze(1).unsqueeze(1).expand(-1, self.n_weeks, -1, -1, -1)

        print(encoded_constants.shape)
        print(x.shape)

        x = torch.cat((encoded_constants, x), dim=2)

        # autoencoder forward
        outputs = self.autoencoder(x, seq_len, future_seq, h_t, c_t, h_t2, c_t2, h_t3, c_t3, h_t4, c_t4)

        return outputs
