"""
Here, you can find the the clustering example of the LTN paper. Please, carefully read the example on the paper before
going through the PyTorch example.
"""
import logging
import torch
import numpy as np
import ltn
import matplotlib.pyplot as plt
logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


class MLP_classifier(torch.nn.Module):
    """
    Model to call as P(x,class).
    Here, the problem of clustering is organized as a classification task, where the classifier outputs the probability
    that the point given in input belongs to a specific cluster. The cluster are the classes of the classification
    problem.
    """
    def __init__(self, layer_sizes=(2, 16, 16, 16, 4)):
        super(MLP_classifier, self).__init__()
        self.elu = torch.nn.ELU()
        self.softmax = torch.nn.Softmax(dim=1)
        self.linear_layers = torch.nn.ModuleList([torch.nn.Linear(layer_sizes[i - 1], layer_sizes[i])
                                                  for i in range(1, len(layer_sizes))])

    def forward(self, inputs):
        x, indices = inputs[0], inputs[1].long()
        for layer in self.linear_layers[:-1]:
            x = self.elu(layer(x))
        x = self.softmax(self.linear_layers[-1](x))
        return torch.gather(x, 1, indices)


def main():
    np.random.seed(12)
    # # Data
    #
    # Generate the clustering dataset
    # 4 centers are randomly generated and 50 points near each of these centers are randomly generated

    # Note that based on the given numpy seed it is possible that LTN will make some mistakes while identifying
    # clusters. This depends on how much the clusters are distinct and on the number of outliers generated by
    # the random process.

    nr_of_clusters = 4
    nr_of_points_x_cluster = 50

    close_threshold = 0.2
    distant_threshold = 1.0

    margin = .2
    mean = [np.random.uniform([-1 + margin, -1 + margin], [0 - margin, 0 - margin], 2),
            np.random.uniform([0 + margin, -1 + margin], [1 - margin, 0 - margin], 2),
            np.random.uniform([-1 + margin, 0 + margin], [0 - margin, 1 - margin], 2),
            np.random.uniform([0 + margin, 0 + margin], [1 - margin, 1 - margin], 2)]

    cov = np.array([[[.01, 0], [0, .01]]] * nr_of_clusters)

    cluster_data = {}
    for i in range(nr_of_clusters):
        cluster_data[i] = np.random.multivariate_normal(mean=mean[i], cov=cov[i], size=nr_of_points_x_cluster)

    data = np.concatenate([cluster_data[i] for i in range(nr_of_clusters)]).astype(np.float32)

    for i in range(nr_of_clusters):
        plt.scatter(cluster_data[i][:, 0], cluster_data[i][:, 1])

    # # LTN
    #
    # Classifier for the clustering problem (trainable classifier)

    C = ltn.Predicate(MLP_classifier())

    # LTN variables to train our LTN predicate model
    cluster = ltn.variable("cluster", range(nr_of_clusters))  # this variable contains the labels of the clusters
    x = ltn.variable("x", data)  # this variable contains the cluster examples
    y = ltn.variable("y", data)  # this variable contains the cluster examples again since we need them twice to build
    # our axioms

    # Operators and axioms

    Not = ltn.WrapperConnective(ltn.fuzzy_ops.NotStandard())
    And = ltn.WrapperConnective(ltn.fuzzy_ops.AndProd())
    Equiv = ltn.WrapperConnective(ltn.fuzzy_ops.Equiv(ltn.fuzzy_ops.AndProd(), ltn.fuzzy_ops.ImpliesGoguenStrong()))
    Forall = ltn.WrapperQuantifier(ltn.fuzzy_ops.AggregPMeanError(p=4), quantification_type="forall")
    Exists = ltn.WrapperQuantifier(ltn.fuzzy_ops.AggregPMean(p=6), quantification_type="exists")

    formula_aggregator = ltn.fuzzy_ops.AggregPMeanError(p=2)

    # non-trainable predicate which measures the euclidean distance between two points. More the points are near each
    # other and more the value of the predicate will be near 1 (the truth).
    eucl_dist = lambda x, y: torch.unsqueeze(torch.norm(x - y, dim=1), dim=1)  # function measuring euclidian distance

    # this function defines the knowledge base containing the axioms that are used to train the model
    # the objective is to maximize the satisfaction level of this knowledge base
    # the parameter p_exists is used to create a scheduling for the parameter p of the existential quantifier
    # aggregator
    def axioms(p_exists):
        axioms = [
            Forall(x, Exists(cluster, C([x, cluster]), p=p_exists)),
            Forall(cluster, Exists(x, C([x, cluster]), p=p_exists)),
            Forall([cluster, x, y], Equiv(C([x, cluster]), C([y, cluster])),
                   mask_vars=[x, y],
                   mask_fn=lambda mask_vars: eucl_dist(mask_vars[0], mask_vars[1]) < close_threshold),
            Forall([cluster, x, y], Not(And(C([x, cluster]), C([y, cluster]))),
                   mask_vars=[x, y],
                   mask_fn=lambda mask_vars: eucl_dist(mask_vars[0], mask_vars[1]) > distant_threshold)
        ]
        axioms = torch.stack(axioms)
        sat_level = formula_aggregator(axioms, dim=0)
        return sat_level

    # # Training
    #
    # While training, we measure:
    # The level of satisfiability of the Knowledge Base of the training data.

    optimizer = torch.optim.Adam(C.parameters(), lr=0.001)

    # training of the predicate C using a loss containing the satisfaction level of the knowledge base
    # the objective it to maximize the satisfaction level of the knowledge base
    for epoch in range(1000):
        if epoch <= 100:
            p_exists = 1
        else:
            p_exists = 6
        optimizer.zero_grad()
        sat_agg = axioms(p_exists)
        loss = 1. - sat_agg
        loss.backward()
        optimizer.step()

        # we print metrics every 20 epochs of training
        if epoch % 20 == 0:
            logger.info(" epoch %d | loss %.4f | Train Sat %.3f ", epoch, loss, axioms(p_exists))

    # graphical visualization of the results

    x0 = data[:, 0]
    x1 = data[:, 1]

    prC = [C.model([torch.tensor(data), torch.tensor([[i]] * len(data))]).detach().numpy()
           for i in range(nr_of_clusters)]
    n = 2
    m = (nr_of_clusters + 1) // n + 1

    fig = plt.figure(figsize=(10, m * 3))

    plt.subplots_adjust(wspace=0.2, hspace=0.3)
    ax = plt.subplot2grid((m, 8), (0, 2), colspan=4)
    ax.set_title("groundtruth")
    for i in range(nr_of_clusters):
        ax.scatter(cluster_data[i][:, 0], cluster_data[i][:, 1])

    for i in range(nr_of_clusters):
        fig.add_subplot(m, n, i + 3)
        plt.title("C" + str(i) + "(x)")
        plt.scatter(x0, x1, c=prC[i], vmin=0, vmax=1)
        plt.colorbar()

    plt.show()


if __name__ == "__main__":
    main()