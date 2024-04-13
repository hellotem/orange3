import numpy as np

from AnyQt.QtCore import Qt

from Orange.data import Table, Domain, ContinuousVariable
from Orange.data.util import get_unique_names
from Orange.preprocess import RemoveNaNColumns, Impute
from Orange import distance
from Orange.widgets import gui
from Orange.widgets.settings import Setting
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import OWWidget, Msg
from Orange.widgets.utils.widgetpreview import WidgetPreview

METRICS = [
    ("欧几里得", distance.Euclidean),
    ("曼哈顿", distance.Manhattan),
    ("马哈拉诺比斯", distance.Mahalanobis),
    ("余弦", distance.Cosine),
    ("杰卡德", distance.Jaccard),
    ("斯皮尔曼", distance.SpearmanR),
    ("绝对斯皮尔曼", distance.SpearmanRAbsolute),
    ("皮尔逊", distance.PearsonR),
    ("绝对皮尔逊", distance.PearsonRAbsolute),
]


class OWNeighbors(OWWidget):
    name = "近邻 Neighbors"
    description = "根据参考计算数据中最近邻"
    icon = "icons/Neighbors.svg"
    category = "无监督"
    replaces = ["orangecontrib.prototypes.widgets.owneighbours.OWNeighbours"]

    class Inputs:
        data = Input("数据", Table)
        reference = Input("参考", Table)

    class Outputs:
        data = Output("邻居", Table)

    class Info(OWWidget.Warning):
        removed_references = \
            Msg("输入数据包括参考实例。\n"
                "参考实例被排除在输出之外。")

    class Warning(OWWidget.Warning):
        all_data_as_reference = \
            Msg("每个数据实例与某些参考相同")

    class Error(OWWidget.Error):
        diff_domains = Msg("数据和参考具有不同的特征")

    n_neighbors: int
    distance_index: int

    n_neighbors = Setting(10)
    limit_neighbors = Setting(True)
    distance_index = Setting(0)
    auto_apply = Setting(True)

    want_main_area = False
    resizing_enabled = False

    def __init__(self):
        super().__init__()

        self.data = None
        self.reference = None
        self.distances = None

        box = gui.vBox(self.controlArea, box=True)
        gui.comboBox(
            box, self, "distance_index", orientation=Qt.Horizontal,
            label="距离度量: ", items=[d[0] for d in METRICS],
            callback=self.recompute)
        gui.spin(
            box, self, "n_neighbors", label="Limit number of neighbors to:",
            step=1, spinType=int, minv=0, maxv=100, checked='limit_neighbors',
            # call apply by gui.auto_commit, pylint: disable=unnecessary-lambda
            checkCallback=self.commit.deferred,
            callback=self.commit.deferred)

        self.apply_button = gui.auto_apply(self.buttonsArea, self)

    @Inputs.data
    def set_data(self, data):
        self.controls.n_neighbors.setMaximum(len(data) if data else 100)
        self.data = data

    @Inputs.reference
    def set_ref(self, refs):
        self.reference = refs

    def handleNewSignals(self):
        self.compute_distances()
        self.commit.now()

    def recompute(self):
        self.compute_distances()
        self.commit.deferred()

    def compute_distances(self):
        self.Error.diff_domains.clear()
        if not self.data or not self.reference:
            self.distances = None
            return
        if set(self.reference.domain.attributes) != \
                set(self.data.domain.attributes):
            self.Error.diff_domains()
            self.distances = None
            return

        metric = METRICS[self.distance_index][1]
        n_ref = len(self.reference)

        # comparing only attributes, no metas and class-vars
        new_domain = Domain(self.data.domain.attributes)
        reference = self.reference.transform(new_domain)
        data = self.data.transform(new_domain)

        all_data = Table.concatenate([reference, data], 0)
        pp_all_data = Impute()(RemoveNaNColumns()(all_data))
        pp_reference, pp_data = pp_all_data[:n_ref], pp_all_data[n_ref:]
        self.distances = metric(pp_data, pp_reference).min(axis=1)

    @gui.deferred
    def commit(self):
        indices = self._compute_indices()

        if indices is None:
            neighbors = None
        else:
            neighbors = self._data_with_similarity(indices)
        self.Outputs.data.send(neighbors)

    def _compute_indices(self):
        self.Warning.all_data_as_reference.clear()
        self.Info.removed_references.clear()

        if self.distances is None:
            return None

        inrefs = np.isin(self.data.ids, self.reference.ids)
        if np.all(inrefs):
            self.Warning.all_data_as_reference()
            return None
        if np.any(inrefs):
            self.Info.removed_references()

        dist = np.copy(self.distances)
        dist[inrefs] = np.max(dist) + 1
        up_to = len(dist) - np.sum(inrefs)
        if self.limit_neighbors and self.n_neighbors < up_to:
            up_to = self.n_neighbors
        # get indexes of N neighbours in unsorted order - faster than argsort
        idx = np.argpartition(dist, up_to - 1)[:up_to]
        # sort selected N neighbours according to distances
        sorted_subset_idx = np.argsort(dist[idx])
        # map sorted indexes back to original index space
        return idx[sorted_subset_idx]

    def _data_with_similarity(self, indices):
        domain = self.data.domain
        dist_var = ContinuousVariable(get_unique_names(domain, "distance"))
        metas = domain.metas + (dist_var, )
        domain = Domain(domain.attributes, domain.class_vars, metas)
        neighbours = self.data.from_table(domain, self.data, row_indices=indices)
        distances = self.distances[indices]
        with neighbours.unlocked(neighbours.metas):
            if distances.size > 0:
                neighbours.set_column(dist_var, distances)
        return neighbours


if __name__ == "__main__":  # pragma: no cover
    iris = Table("iris.tab")
    WidgetPreview(OWNeighbors).run(
        set_data=iris,
        set_ref=iris[:1])
