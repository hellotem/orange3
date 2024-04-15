import warnings

import sklearn.cluster

from Orange.clustering.clustering import Clustering, ClusteringModel
from Orange.data import Table


__all__ = ["SpectralClustering"]


class SpectralClusteringModel(ClusteringModel):

    def __init__(self, projector):
        super().__init__(projector)
        # self.centroids = projector.cluster_centers_
        self.k = projector.get_params()["n_clusters"]

    def predict(self, X):
        return self.projector.predict(X)


class SpectralClustering(Clustering):

    __wraps__ = sklearn.cluster.SpectralClustering
    __returns__ = SpectralClusteringModel

    def __init__(self, n_clusters=8, n_components=None,  gamma=1.0, affinity='rbf', n_neighbors=10,n_init=10,
                 random_state=None, preprocessors=None, compute_silhouette_score=None):
        if compute_silhouette_score is not None:
            warnings.warn(
                "compute_silhouette_score is deprecated. Please use "
                "sklearn.metrics.silhouette_score to compute silhouettes.",
                DeprecationWarning)
        super().__init__(
            preprocessors, {k: v for k, v in vars().items()
                            if k != "compute_silhouette_score"})


if __name__ == "__main__":
    d = Table("iris")
    km = SpectralClusteringModel(preprocessors=None, n_clusters=3)
    clusters = km(d)
    model = km.fit_storage(d)
