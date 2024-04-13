from AnyQt.QtCore import Qt

from Orange.data import Table
from Orange.modelling import RandomForestLearner
from Orange.widgets import settings, gui
from Orange.widgets.utils.owlearnerwidget import OWBaseLearner
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.widget import Msg


class OWRandomForest(OWBaseLearner):
    name = "随机森林 Random Forest"
    description = "使用决策树集合进行预测。"
    icon = "icons/RandomForest.svg"
    replaces = [
        "Orange.widgets.classify.owrandomforest.OWRandomForest",
        "Orange.widgets.regression.owrandomforestregression.OWRandomForestRegression",
    ]
    priority = 40
    keywords = "random forest"

    LEARNER = RandomForestLearner

    n_estimators = settings.Setting(10)
    max_features = settings.Setting(5)
    use_max_features = settings.Setting(False)
    use_random_state = settings.Setting(False)
    max_depth = settings.Setting(3)
    use_max_depth = settings.Setting(False)
    min_samples_split = settings.Setting(5)
    use_min_samples_split = settings.Setting(True)
    index_output = settings.Setting(0)
    class_weight = settings.Setting(False)

    class Error(OWBaseLearner.Error):
        not_enough_features = Msg("属性数量不足 ({})")

    class Warning(OWBaseLearner.Warning):
        class_weights_used = Msg("按类加权可能会降低性能。")

    def add_main_layout(self):
        # this is part of init, pylint: disable=attribute-defined-outside-init
        box = gui.vBox(self.controlArea, '基本属性')
        self.n_estimators_spin = gui.spin(
            box, self, "n_estimators", minv=1, maxv=10000, controlWidth=80,
            alignment=Qt.AlignRight, label="树木数量:",
            callback=self.settings_changed)
        self.max_features_spin = gui.spin(
            box, self, "max_features", 1, 50, controlWidth=80,
            label="每次分裂时考虑的属性数量:",
            callback=self.settings_changed, checked="use_max_features",
            checkCallback=self.settings_changed, alignment=Qt.AlignRight,)
        self.random_state = gui.checkBox(
            box, self, "use_random_state", label="可复制训练",
            callback=self.settings_changed,
            attribute=Qt.WA_LayoutUsesWidgetRect)
        self.weights = gui.checkBox(
            box, self,
            "class_weight", label="平衡类别分布",
            callback=self.settings_changed,
            tooltip="根据类别频率的倒数加权。",
            attribute=Qt.WA_LayoutUsesWidgetRect
        )

        box = gui.vBox(self.controlArea, "生长控制")
        self.max_depth_spin = gui.spin(
            box, self, "max_depth", 1, 50, controlWidth=80,
            label="限制单棵树的深度:", alignment=Qt.AlignRight,
            callback=self.settings_changed, checked="use_max_depth",
            checkCallback=self.settings_changed)
        self.min_samples_split_spin = gui.spin(
            box, self, "min_samples_split", 2, 1000, controlWidth=80,
            label="不拆分小于:",
            callback=self.settings_changed, checked="use_min_samples_split",
            checkCallback=self.settings_changed, alignment=Qt.AlignRight)

    def create_learner(self):
        self.Warning.class_weights_used.clear()
        common_args = {"n_estimators": self.n_estimators}
        if self.use_max_features:
            common_args["max_features"] = self.max_features
        if self.use_random_state:
            common_args["random_state"] = 0
        if self.use_max_depth:
            common_args["max_depth"] = self.max_depth
        if self.use_min_samples_split:
            common_args["min_samples_split"] = self.min_samples_split
        if self.class_weight:
            common_args["class_weight"] = "balanced"
            self.Warning.class_weights_used()

        return self.LEARNER(preprocessors=self.preprocessors, **common_args)

    def check_data(self):
        self.Error.not_enough_features.clear()
        if super().check_data():
            n_features = len(self.data.domain.attributes)
            if self.use_max_features and self.max_features > n_features:
                self.Error.not_enough_features(n_features)
                self.valid_data = False
        return self.valid_data

    def get_learner_parameters(self):
        """Called by send report to list the parameters of the learner."""
        return (
            ("树木数量", self.n_estimators),
            ("考虑的最大特征数",
             self.max_features if self.use_max_features else "无限制"),
            ("可复制训练", ["否", "是"][self.use_random_state]),
            ("最大树深度",
             self.max_depth if self.use_max_depth else "无限制"),
            ("达到最大实例数时停止分裂节点",
             self.min_samples_split if self.use_min_samples_split else
             "无限制"),
            ("类权重", self.class_weight)
        )


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWRandomForest).run(Table("iris"))
