from AnyQt.QtCore import Qt

from Orange.base import Learner
from Orange.data import Table
from Orange.modelling import SklAdaBoostLearner, SklTreeLearner
from Orange.widgets import gui
from Orange.widgets.settings import Setting
from Orange.widgets.utils.owlearnerwidget import OWBaseLearner
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.widget import Msg, Input


class OWAdaBoost(OWBaseLearner):
    name = "AdaBoost"
    description = "一种集成元算法,结合弱学习器" \
                  '并适应每个训练样本的"难度"。'
    icon = "icons/AdaBoost.svg"
    replaces = [
        "Orange.widgets.classify.owadaboost.OWAdaBoostClassification",
        "Orange.widgets.regression.owadaboostregression.OWAdaBoostRegression",
    ]
    priority = 80
    keywords = "adaboost, boost"

    LEARNER = SklAdaBoostLearner

    class Inputs(OWBaseLearner.Inputs):
        learner = Input("学习器", Learner)

    #: Algorithms for classification problems
    algorithms = ["SAMME", "SAMME.R"]
    #: Losses for regression problems
    losses = ["线性", "平方", "指数"]

    n_estimators = Setting(50)
    learning_rate = Setting(1.)
    algorithm_index = Setting(1)
    loss_index = Setting(0)
    use_random_seed = Setting(False)
    random_seed = Setting(0)

    DEFAULT_BASE_ESTIMATOR = SklTreeLearner()

    class Error(OWBaseLearner.Error):
        no_weight_support = Msg('基学习器不支持权重。')

    def add_main_layout(self):
        # this is part of init, pylint: disable=attribute-defined-outside-init
        box = gui.widgetBox(self.controlArea, "参数")
        self.base_estimator = self.DEFAULT_BASE_ESTIMATOR
        self.base_label = gui.label(
            box, self, "基估计器: " + self.base_estimator.name.title())

        self.n_estimators_spin = gui.spin(
            box, self, "n_estimators", 1, 10000, label="Number of estimators:",
            alignment=Qt.AlignRight, controlWidth=80,
            callback=self.settings_changed)
        self.learning_rate_spin = gui.doubleSpin(
            box, self, "learning_rate", 1e-5, 1.0, 1e-5,
            label="Learning rate:", decimals=5, alignment=Qt.AlignRight,
            controlWidth=80, callback=self.settings_changed)
        self.random_seed_spin = gui.spin(
            box, self, "random_seed", 0, 2 ** 31 - 1, controlWidth=80,
            label="Fixed seed for random generator:", alignment=Qt.AlignRight,
            callback=self.settings_changed, checked="use_random_seed",
            checkCallback=self.settings_changed)

        # Algorithms
        box = gui.widgetBox(self.controlArea, "提升方法")
        self.cls_algorithm_combo = gui.comboBox(
            box, self, "algorithm_index", label="Classification algorithm:",
            items=self.algorithms,
            orientation=Qt.Horizontal, callback=self.settings_changed)
        self.reg_algorithm_combo = gui.comboBox(
            box, self, "loss_index", label="Regression loss function:",
            items=self.losses,
            orientation=Qt.Horizontal, callback=self.settings_changed)

    def create_learner(self):
        if self.base_estimator is None:
            return None
        return self.LEARNER(
            estimator=self.base_estimator,
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            random_state=self.random_seed,
            preprocessors=self.preprocessors,
            algorithm=self.algorithms[self.algorithm_index],
            loss=self.losses[self.loss_index].lower())

    @Inputs.learner
    def set_base_learner(self, learner):
        # base_estimator is defined in add_main_layout
        # pylint: disable=attribute-defined-outside-init
        self.Error.no_weight_support.clear()
        if learner and not learner.supports_weights:
            # Clear the error and reset to default base learner
            self.Error.no_weight_support()
            self.base_estimator = None
            self.base_label.setText("基估计器: 无效")
        else:
            self.base_estimator = learner or self.DEFAULT_BASE_ESTIMATOR
            self.base_label.setText(
                "基估计器: %s" % self.base_estimator.name.title())
        self.learner = self.model = None

    def get_learner_parameters(self):
        return (("基估计器", self.base_estimator),
                ("估计器数量", self.n_estimators),
                ("算法 (分类)", self.algorithms[
                    self.algorithm_index].capitalize()),
                ("损失 (回归)", self.losses[
                    self.loss_index].capitalize()))


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWAdaBoost).run(Table("iris"))
