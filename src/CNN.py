# CNN.py

import torch
import torch.nn as nn
from torch import Tensor
from typing import Sequence
from collections import defaultdict
import torchvision.models as models  # Added for ResNet integration

POOLINGS = {"avg": nn.AvgPool2d, "max": nn.MaxPool2d}

ACTIVATIONS = {
    "relu": nn.ReLU,
    "tanh": nn.Tanh,
    "sigmoid": nn.Sigmoid,
    "softmax": nn.Softmax,
    "logsoftmax": nn.LogSoftmax,
    "lrelu": nn.LeakyReLU,
    "none": nn.Identity,
    None: nn.Identity,
}

# Default keyword arguments to pass to activation class constructors, e.g.
# activation_cls(**ACTIVATION_DEFAULT_KWARGS[name])
ACTIVATION_DEFAULT_KWARGS = defaultdict(
    dict,
    {
        "softmax": dict(dim=1),
        "logsoftmax": dict(dim=1),
    },
)


class CNN(nn.Module):
    """
    A simple convolutional neural network model based on PyTorch nn.Modules.

    Has a convolutional part at the beginning and an MLP at the end.
    The architecture is:
    [(CONV -> ACT)*P -> POOL]*(N/P) -> (FC -> ACT)*M -> FC
    """

    def __init__(
        self,
        in_size,
        out_classes: int,
        channels: Sequence[int],
        pool_every: int,
        hidden_dims: Sequence[int],
        conv_params: dict = {},
        activation_type: str = "relu",
        activation_params: dict = {},
        pooling_type: str = "max",
        pooling_params: dict = {},
    ):
        """
        :param in_size: Size of input images, e.g. (C,H,W).
        :param out_classes: Number of classes to output in the final layer.
        :param channels: A list of of length N containing the number of
            (output) channels in each conv layer.
        :param pool_every: P, the number of conv layers before each max-pool.
        :param hidden_dims: List of of length M containing hidden dimensions of
            each Linear layer (not including the output layer).
        :param conv_params: Parameters for convolution layers.
        :param activation_type: Type of activation function; supports either 'relu' or
            'lrelu' for leaky relu.
        :param activation_params: Parameters passed to activation function.
        :param pooling_type: Type of pooling to apply; supports 'max' for max-pooling or
            'avg' for average pooling.
        :param pooling_params: Parameters passed to pooling layer.
        """
        super().__init__()
        assert channels and hidden_dims, "Channels and hidden_dims must be non-empty lists."

        self.in_size = in_size
        self.out_classes = out_classes
        self.channels = channels
        self.pool_every = pool_every
        self.hidden_dims = hidden_dims
        self.conv_params = conv_params
        self.activation_type = activation_type
        self.activation_params = activation_params
        self.pooling_type = pooling_type
        self.pooling_params = pooling_params

        if activation_type not in ACTIVATIONS or pooling_type not in POOLINGS:
            raise ValueError("Unsupported activation or pooling type")

        # Initialize ResNet18 as the ResNet architecture with updated weights parameter
        resnet = models.resnet18(weights=None)  # Replaced pretrained=False with weights=None

        # Modify ResNet's first convolutional layer to accept the number of channels output by CNN
        # Original ResNet expects 3-channel input; adjust to match CNN's output channels
        resnet.conv1 = nn.Conv2d(
            in_channels=self.channels[-1],
            out_channels=64,
            kernel_size=7,
            stride=2,
            padding=3,
            bias=False
        )

        # Remove ResNet's maxpool layer to preserve spatial dimensions (optional)
        resnet.maxpool = nn.Identity()

        # Remove ResNet's fully connected layer to use it as a feature extractor
        self.resnet_feature_extractor = nn.Sequential(*list(resnet.children())[:-1])

        # Now create the feature extractor for the CNN part
        self.feature_extractor = self._make_feature_extractor()

        # Now that resnet_feature_extractor is initialized, create the MLP
        self.mlp = self._make_mlp()

    def _make_feature_extractor(self):
        in_channels, in_h, in_w = tuple(self.in_size)

        layers = []
        conv_channels = [in_channels] + self.channels  # Add the input channel into the channel list

        for i in range(len(self.channels)):
            # Create convolution layer
            conv_layer = nn.Conv2d(conv_channels[i], conv_channels[i+1], **self.conv_params)
            layers.append(conv_layer)

            # Apply activation
            activation_fn = ACTIVATIONS.get(self.activation_type)(**self.activation_params)
            layers.append(activation_fn)

            # Pooling every `pool_every` layers
            if (i + 1) % self.pool_every == 0:
                pooling_layer = POOLINGS[self.pooling_type](**self.pooling_params)
                layers.append(pooling_layer)

        seq = nn.Sequential(*layers)
        return seq

    def _n_features(self) -> int:
        """
        Calculates the number of extracted features going into the classifier part.
        :return: Number of features.
        """
        # Make sure to not mess up the random state.
        rng_state = torch.get_rng_state()
        try:
            # Set up dummy input to pass through the layers
            dummy_input = torch.rand(2, *self.in_size)  # Changed batch size from 1 to 2
            dummy_output = self.feature_extractor(dummy_input)  # Pass it through the feature extractor
            dummy_output = self.resnet_feature_extractor(dummy_output)  # Pass through ResNet feature extractor
            extracted_features = int(torch.prod(torch.tensor(dummy_output.shape[1:])))  # (channels * height * width)
        finally:
            torch.set_rng_state(rng_state)
        return extracted_features

    def _make_mlp(self):
        # Create the MLP part of the model: (FC -> ACT)*M -> Linear
        mlp_layers = []
        in_features = self._n_features()

        activation_fn = ACTIVATIONS.get(self.activation_type)(**self.activation_params)

        # Create hidden layers
        for dim in self.hidden_dims:
            mlp_layers.append(nn.Linear(in_features, dim))
            mlp_layers.append(activation_fn)  # Activation function
            in_features = dim

        # Create output layer
        mlp_layers.append(nn.Linear(in_features, self.out_classes))

        mlp = nn.Sequential(*mlp_layers)
        return mlp

    def forward(self, x: Tensor):
        # Implement the forward pass.
        # Extract features from the input using the feature extractor
        features = self.feature_extractor(x)

        # Pass through ResNet feature extractor
        features = self.resnet_feature_extractor(features)

        # Flatten the features to feed them to the MLP
        features = features.view(features.size(0), -1)

        # Pass through the MLP classifier
        out: Tensor = self.mlp(features)
        return out  # Corrected to return 'out' only
