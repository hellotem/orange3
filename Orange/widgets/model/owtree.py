"""Tree learner widget"""

from collections import OrderedDict

from AnyQt.QtCore import Qt

from Orange.data import Table
from Orange.modelling.tree import TreeLearner
from Orange.widgets import gui
from Orange.widgets.settings import Setting
from Orange.widgets.utils.localization import pl
from Orange.widgets.utils.owlearnerwidget import OWBaseLearner
from Orange.widgets.utils.widgetpreview import WidgetPreview


class OWTreeLearner(OWBaseLearner):
    """Tree algorithm with forward pruning."""
    name = "决策树 Decision Tree"
    description = "一种带有前向剪枝的树算法。"
    icon = "icons/Tree.svg"
    replaces = [
        "Orange.widgets.classify.owclassificationtree.OWClassificationTree",
        "Orange.widgets.regression.owregressiontree.OWRegressionTree",
        "Orange.widgets.classify.owclassificationtree.OWTreeLearner",
        "Orange.widgets.regression.owregressiontree.OWTreeLearner",
    ]
    priority = 30
    keywords = "tree, classification tree"

    LEARNER = TreeLearner

    binary_trees = Setting(True)
    limit_min_leaf = Setting(True)
    min_leaf = Setting(2)
    limit_min_internal = Setting(True)
    min_internal = Setting(5)
    limit_depth = Setting(True)
    max_depth = Setting(100)

    # Classification only settings
    limit_majority = Setting(True)
    sufficient_majority = Setting(95)

    spin_boxes = (
        ("叶节点中实例的最小数量:",
         "limit_min_leaf", "min_leaf", 1, 1000),
        ("不拆分小于:",
         "limit_min_internal", "min_internal", 1, 1000),
        ("限制最大树深度为:",
         "limit_depth", "max_depth", 1, 1000))

    classification_spin_boxes = (
        ("当多数达到 [%] 时停止:",
         "limit_majority", "sufficient_majority", 51, 100),)

    def add_main_layout(self):
        box = gui.widgetBox(self.controlArea, '参数')
        # the checkbox is put into vBox for alignemnt with other checkboxes
        gui.checkBox(box, self, "binary_trees", "归纳二叉树",
                     callback=self.settings_changed,
                     attribute=Qt.WA_LayoutUsesWidgetRect)
        for label, check, setting, fromv, tov in self.spin_boxes:
            gui.spin(box, self, setting, fromv, tov, label=label,
                     checked=check, alignment=Qt.AlignRight,
                     callback=self.settings_changed,
                     checkCallback=self.settings_changed, controlWidth=80)

    def add_classification_layout(self, box):
        for label, check, setting, minv, maxv in self.classification_spin_boxes:
            gui.spin(box, self, setting, minv, maxv,
                     label=label, checked=check, alignment=Qt.AlignRight,
                     callback=self.settings_changed, controlWidth=80,
                     checkCallback=self.settings_changed)

    def learner_kwargs(self):
        # Pylint doesn't get our Settings
        # pylint: disable=invalid-sequence-index
        return dict(
            max_depth=(None, self.max_depth)[self.limit_depth],
            min_samples_split=(2, self.min_internal)[self.limit_min_internal],
            min_samples_leaf=(1, self.min_leaf)[self.limit_min_leaf],
            binarize=self.binary_trees,
            preprocessors=self.preprocessors,
            sufficient_majority=(1, self.sufficient_majority / 100)[
                self.limit_majority])

    def create_learner(self):
        # pylint: disable=not-callable
        return self.LEARNER(**self.learner_kwargs())

    def get_learner_parameters(self):
        from Orange.widgets.report import plural_w
        items = OrderedDict()
        items["剪枝"] = ",".join(s for s, c in (
            (f'至少 {self.min_leaf}'
             f'{pl(self.min_leaf, "实例")} 在叶节点中',
             self.limit_min_leaf),
            (f'至少 {self.min_internal}'
             f'{pl(self.min_internal, "实例")} 在内部节点中',
             self.limit_min_internal),
            (f'最大深度 {self.max_depth}',
             self.limit_depth)
        ) if c) or "无"
        if self.limit_majority:
            items["分裂"] = "当多数达到 %d%% 时停止分裂" \
                                 "(仅分类)" % \
                                 self.sufficient_majority
        items["二叉树"] = ("否", "是")[self.binary_trees]
        return items


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWTreeLearner).run(Table("iris"))
