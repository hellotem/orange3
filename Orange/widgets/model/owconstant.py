from Orange.data import Table
from Orange.modelling.constant import ConstantLearner
from Orange.widgets.utils.owlearnerwidget import OWBaseLearner
from Orange.widgets.utils.widgetpreview import WidgetPreview


class OWConstant(OWBaseLearner):
    name = "常数 Constant"
    description = "预测最频繁的类或平均值" \
                  "来自训练集。"
    icon = "icons/Constant.svg"
    replaces = [
        "Orange.widgets.classify.owmajority.OWMajority",
        "Orange.widgets.regression.owmean.OWMean",
    ]
    priority = 10
    keywords = "常数、多数、平均值"

    LEARNER = ConstantLearner


if __name__ == "__main__":  # pragma: no cover
    WidgetPreview(OWConstant).run(Table("iris"))
