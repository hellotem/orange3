from AnyQt.QtCore import Qt

from Orange.data import Table
from Orange.modelling import KNNLearner
from Orange.widgets import gui
from Orange.widgets.settings import Setting
from Orange.widgets.utils.owlearnerwidget import OWBaseLearner
from Orange.widgets.utils.widgetpreview import WidgetPreview


class OWKNNLearner(OWBaseLearner):
    name = "半监督学习 Semisupervised Learning"
    description = "利用较少的标记样本实现分类。 "
    icon = "icons/SSL.svg"
    replaces = [
        "Orange.widgets.classify.owknn.OWKNNLearner",
        "Orange.widgets.regression.owknnregression.OWKNNRegression",
    ]
    priority = 20
    keywords = "ssl、半监督学习、图论、邻居"

    LEARNER = KNNLearner

    weights = ["uniform", "distance"]
    metrics = ["euclidean", "manhattan", "chebyshev", "mahalanobis"]

    weights_options = ["均匀", "按距离"]
    metrics_options = ["欧几里得", "曼哈顿", "切比雪夫", "马哈拉诺比斯"]

    n_neighbors = Setting(5)
    metric_index = Setting(0)
    weight_index = Setting(0)

    def add_main_layout(self):
        # this is part of init, pylint: disable=attribute-defined-outside-init
        box = gui.vBox(self.controlArea, "邻居")
        self.n_neighbors_spin = gui.spin(
            box, self, "n_neighbors", 1, 100, label="邻居数量:",
            alignment=Qt.AlignRight, callback=self.settings_changed,
            controlWidth=80)
        self.metrics_combo = gui.comboBox(
            box, self, "metric_index", orientation=Qt.Horizontal,
            label="度量：", items=self.metrics_options,
            callback=self.settings_changed)
        self.weights_combo = gui.comboBox(
            box, self, "weight_index", orientation=Qt.Horizontal,
            label="加权：", items=self.weights_options,
            callback=self.settings_changed)

    def create_learner(self):
        return self.LEARNER(
            n_neighbors=self.n_neighbors,
            metric=self.metrics[self.metric_index],
            weights=self.weights[self.weight_index],
            preprocessors=self.preprocessors)

    def get_learner_parameters(self):
        return (("邻居数量", self.n_neighbors),
                ("度量", self.metrics_options[self.metric_index]),
                ("权重", self.weights_options[self.weight_index]))


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWKNNLearner).run(Table("iris"))
